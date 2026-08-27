"""L3 报告 → session 功能区词汇表提取器。

Vocabulary extraction follows the current materialization boundary in
docs/design/03_PLANNING_EXECUTION.md.

v5 设计：LLM 只产严格的 typed rule union；提取器负责：
- 判别联合校验与 ``extra='forbid'`` fail-close
- bundle 闭集 DLBM/zone/POI/road ID 校验
- 递归深度 / 节点数 / 数值范围限制
- deterministic dry-run + quarantine
- 仅将已验证类别注册为可执行 Vocabulary
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Dict, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.contracts.domain.custom_zone_contracts import (
    TypingRule,
    Vocabulary,
    VocabularyCategory,
)
from app.data.encodings.dicts.vocabularies.loader import register_vocabulary
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_MAX_RULE_DEPTH = 6
_MAX_RULE_NODES = 48
_MAX_DLBM_IDS = 24
_MAX_COMPOSITE_CHILDREN = 12
_MAX_SOURCE_SPAN_CHARS = 400
_MAX_NAME_CHARS = 80
_MAX_CATEGORIES = 32
_MAX_REPORT_CHARS = 9000
_SLOPE_RANGE = (0.0, 90.0)
_ROAD_DISTANCE_RANGE = (0.0, 20000.0)


def _clean_text(value: Any, *, limit: int = 200) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _clean_source_span(value: Any) -> str:
    return _clean_text(value, limit=_MAX_SOURCE_SPAN_CHARS)


def _is_hex_color(value: str) -> bool:
    if len(value) != 7 or value[0] != "#":
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value[1:])


class _StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DlbmInRule(_StrictBaseModel):
    rule: Literal["dlbm_in"]
    dlbm_ids: list[str] = Field(min_length=1, max_length=_MAX_DLBM_IDS)
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "DlbmInRule":
        self.dlbm_ids = [_clean_text(item, limit=32) for item in self.dlbm_ids if _clean_text(item, limit=32)]
        self.source_span = _clean_source_span(self.source_span)
        if not self.dlbm_ids:
            raise ValueError("dlbm_ids must not be empty")
        return self


class WithinZoneRule(_StrictBaseModel):
    rule: Literal["within_zone"]
    zone_id: str
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "WithinZoneRule":
        self.zone_id = _clean_text(self.zone_id, limit=120)
        self.source_span = _clean_source_span(self.source_span)
        if not self.zone_id:
            raise ValueError("zone_id is required")
        return self


class NotWithinZoneRule(_StrictBaseModel):
    rule: Literal["not_within_zone"]
    zone_id: str
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "NotWithinZoneRule":
        self.zone_id = _clean_text(self.zone_id, limit=120)
        self.source_span = _clean_source_span(self.source_span)
        if not self.zone_id:
            raise ValueError("zone_id is required")
        return self


class SlopeLtRule(_StrictBaseModel):
    rule: Literal["slope_lt"]
    max_slope_deg: float = Field(ge=_SLOPE_RANGE[0], le=_SLOPE_RANGE[1])
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "SlopeLtRule":
        self.source_span = _clean_source_span(self.source_span)
        return self


class RoadDistanceLtRule(_StrictBaseModel):
    rule: Literal["road_distance_lt"]
    max_distance_m: float = Field(ge=_ROAD_DISTANCE_RANGE[0], le=_ROAD_DISTANCE_RANGE[1])
    road_id: str | None = None
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "RoadDistanceLtRule":
        self.road_id = _clean_text(self.road_id, limit=120) or None
        self.source_span = _clean_source_span(self.source_span)
        return self


class NearPoiRule(_StrictBaseModel):
    rule: Literal["near_poi"]
    poi_id: str
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "NearPoiRule":
        self.poi_id = _clean_text(self.poi_id, limit=120)
        self.source_span = _clean_source_span(self.source_span)
        if not self.poi_id:
            raise ValueError("poi_id is required")
        return self


class AllRule(_StrictBaseModel):
    rule: Literal["all"]
    children: list["RuleNode"] = Field(min_length=1, max_length=_MAX_COMPOSITE_CHILDREN)
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "AllRule":
        self.source_span = _clean_source_span(self.source_span)
        return self


class AnyRule(_StrictBaseModel):
    rule: Literal["any"]
    children: list["RuleNode"] = Field(min_length=1, max_length=_MAX_COMPOSITE_CHILDREN)
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "AnyRule":
        self.source_span = _clean_source_span(self.source_span)
        return self


class NotRule(_StrictBaseModel):
    rule: Literal["not"]
    children: list["RuleNode"] = Field(min_length=1, max_length=1)
    source_span: str = ""

    @model_validator(mode="after")
    def normalize_fields(self) -> "NotRule":
        self.source_span = _clean_source_span(self.source_span)
        return self


RuleNode = Annotated[
    Union[
        DlbmInRule,
        WithinZoneRule,
        NotWithinZoneRule,
        SlopeLtRule,
        RoadDistanceLtRule,
        NearPoiRule,
        AllRule,
        AnyRule,
        NotRule,
    ],
    Field(discriminator="rule"),
]

_RULE_ADAPTER = TypeAdapter(RuleNode)


class _VocabularyCategoryOutput(_StrictBaseModel):
    name_zh: str
    color: str
    is_protection: bool
    source_span: str
    rules: list[RuleNode] = Field(min_length=1, max_length=_MAX_RULE_NODES)

    @model_validator(mode="after")
    def normalize_fields(self) -> "_VocabularyCategoryOutput":
        self.name_zh = _clean_text(self.name_zh, limit=_MAX_NAME_CHARS)
        self.color = _clean_text(self.color, limit=16)
        self.source_span = _clean_source_span(self.source_span)
        if not self.name_zh:
            raise ValueError("name_zh is required")
        if not self.source_span:
            raise ValueError("source_span is required")
        return self


class _VocabularyOutput(_StrictBaseModel):
    categories: list[_VocabularyCategoryOutput] = Field(default_factory=list, max_length=_MAX_CATEGORIES)


@dataclass
class VocabularyQuarantineItem:
    name_zh: str
    reason: str
    source_span: str = ""
    rule: str = ""


@dataclass
class VocabularyDryRunResult:
    category_code: str
    name_zh: str
    matched_bsms: list[str]
    matched_count: int
    matched_area_ha: float
    source_span: str = ""
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class VocabularyCompileResult:
    vocabulary: Vocabulary
    dry_run: list[VocabularyDryRunResult] = field(default_factory=list)
    quarantine: list[VocabularyQuarantineItem] = field(default_factory=list)


@dataclass(frozen=True)
class _BundleClosedSet:
    dlbm_ids: frozenset[str] = frozenset()
    zone_ids: frozenset[str] = frozenset()
    poi_ids: frozenset[str] = frozenset()
    road_ids: frozenset[str] = frozenset()
    parcel_count: int = 0
    total_area_ha: float = 0.0
    parcel_contexts: tuple[dict[str, Any], ...] = ()


def _bundle_items(group: Any, keys: tuple[str, ...]) -> list[Any]:
    items: list[Any] = []
    if group is None:
        return items
    for key in keys:
        getter = getattr(group, "get", None)
        if callable(getter):
            try:
                items.extend(list(getter(key) or []))
            except Exception:
                continue
    return items


def _feature_value(feature: Any, *names: str) -> str:
    for name in names:
        value = ""
        if isinstance(feature, dict):
            value = feature.get(name, "")
            if not value and isinstance(feature.get("properties"), dict):
                value = feature["properties"].get(name, "")
        else:
            value = getattr(feature, name, "")
            properties = getattr(feature, "properties", None)
            if not value and isinstance(properties, dict):
                value = properties.get(name, "")
        text = _clean_text(value, limit=120)
        if text:
            return text
    return ""


def _parcel_context_from_feature(feature: Any) -> dict[str, Any]:
    area_sqm = getattr(feature, "area_sqm", 0.0) if not isinstance(feature, dict) else feature.get("area_sqm", 0.0)
    zone_membership = []
    for value in (
        _feature_value(feature, "zone_type"),
        _feature_value(feature, "planning_zone"),
        _feature_value(feature, "primary_zone"),
    ):
        if value and value not in zone_membership:
            zone_membership.append(value)
    raw_poi_hits = (
        getattr(feature, "poi_hits", [])
        if not isinstance(feature, dict)
        else feature.get("poi_hits", [])
        or []
    )
    poi_hits: list[dict[str, Any]] = []
    for hit in raw_poi_hits:
        if isinstance(hit, dict):
            name = _clean_text(hit.get("name", hit.get("poi_id", hit.get("id", ""))), limit=120)
            record = dict(hit)
            if name and not record.get("name"):
                record["name"] = name
            poi_hits.append(record)
            continue
        name = _clean_text(hit, limit=120)
        if name:
            poi_hits.append({"name": name})
    ctx = {
        "bsm": _feature_value(feature, "bsm", "BSM"),
        "dlbm": _feature_value(feature, "dlbm", "DLBM", "QMDLBM"),
        "area_ha": float(area_sqm or 0.0) / 10000.0,
        "slope_deg": float(
            getattr(feature, "slope_deg", 999.0) if not isinstance(feature, dict) else feature.get("slope_deg", 999.0)
        ),
        "road_distance_m": float(
            getattr(feature, "road_distance_m", 99999.0)
            if not isinstance(feature, dict)
            else feature.get("road_distance_m", 99999.0)
        ),
        "zone_membership": zone_membership,
        "poi_hits": poi_hits,
    }
    return ctx


def _build_bundle_closed_set(bundle: Any) -> _BundleClosedSet:
    if bundle is None:
        return _BundleClosedSet()

    parcels = _bundle_items(getattr(bundle, "polygons", None), ("landuse_current", "landuse_planned"))
    points = _bundle_items(
        getattr(bundle, "points", None),
        ("annotations_current", "annotations_planned", "facilities_current", "facilities_planned"),
    )
    roads = _bundle_items(getattr(bundle, "lines", None), ("roads_current", "roads_planned", "external_roads"))
    zone_features = []
    polygon_group = getattr(bundle, "polygons", None)
    if polygon_group is not None:
        for key in getattr(polygon_group, "keys", lambda: [])():
            key_text = str(key or "")
            if "zone" in key_text or "boundary" in key_text or "redline" in key_text:
                zone_features.extend(list(polygon_group.get(key) or []))

    dlbm_ids = {
        _feature_value(parcel, "dlbm", "DLBM", "QMDLBM")
        for parcel in parcels
        if _feature_value(parcel, "dlbm", "DLBM", "QMDLBM")
    }
    zone_ids = set()
    for item in [*parcels, *zone_features]:
        for name in (
            "zone_type",
            "planning_zone",
            "primary_zone",
            "zone_id",
            "zone_name",
            "ytfqmc",
            "gzfqmc",
            "tdyfqqbh",
            "tdyfqbh",
            "subtype",
            "bsm",
            "BSM",
        ):
            value = _feature_value(item, name)
            if value:
                zone_ids.add(value)

    poi_ids = set()
    for item in points:
        for name in ("bsm", "BSM", "facility_name", "facility_type", "text", "name", "注记"):
            value = _feature_value(item, name)
            if value:
                poi_ids.add(value)

    road_ids = set()
    for item in roads:
        for name in ("bsm", "BSM", "road_name", "name"):
            value = _feature_value(item, name)
            if value:
                road_ids.add(value)

    parcel_contexts = tuple(_parcel_context_from_feature(parcel) for parcel in parcels)
    total_area_ha = round(sum(float(item.get("area_ha", 0.0) or 0.0) for item in parcel_contexts), 6)
    return _BundleClosedSet(
        dlbm_ids=frozenset(sorted(dlbm_ids)),
        zone_ids=frozenset(sorted(zone_ids)),
        poi_ids=frozenset(sorted(poi_ids)),
        road_ids=frozenset(sorted(road_ids)),
        parcel_count=len(parcel_contexts),
        total_area_ha=total_area_ha,
        parcel_contexts=parcel_contexts,
    )


def _rule_depth_and_nodes(rule: RuleNode, depth: int = 1) -> tuple[int, int]:
    children = getattr(rule, "children", []) or []
    if not children:
        return depth, 1
    max_depth = depth
    node_count = 1
    for child in children:
        child_depth, child_nodes = _rule_depth_and_nodes(child, depth + 1)
        max_depth = max(max_depth, child_depth)
        node_count += child_nodes
    return max_depth, node_count


def _typing_rule_from_node(rule: RuleNode) -> TypingRule:
    if isinstance(rule, DlbmInRule):
        return TypingRule(kind="dlbm_in", value=list(rule.dlbm_ids))
    if isinstance(rule, WithinZoneRule):
        return TypingRule(kind="within_zone", value=rule.zone_id)
    if isinstance(rule, NotWithinZoneRule):
        return TypingRule(kind="not_within_zone", value=rule.zone_id)
    if isinstance(rule, SlopeLtRule):
        return TypingRule(kind="slope_lt", value=float(rule.max_slope_deg))
    if isinstance(rule, RoadDistanceLtRule):
        return TypingRule(kind="road_distance_lt", value=float(rule.max_distance_m))
    if isinstance(rule, NearPoiRule):
        return TypingRule(kind="near_poi", value=rule.poi_id)
    if isinstance(rule, AllRule):
        return TypingRule(kind="and", children=[_typing_rule_from_node(child) for child in rule.children])
    if isinstance(rule, AnyRule):
        return TypingRule(kind="any", children=[_typing_rule_from_node(child) for child in rule.children])
    if isinstance(rule, NotRule):
        return TypingRule(kind="not", children=[_typing_rule_from_node(child) for child in rule.children])
    raise TypeError(f"unsupported rule node: {type(rule).__name__}")


def _validate_rule_against_closed_set(
    rule: RuleNode,
    closed_set: _BundleClosedSet,
) -> str | None:
    if isinstance(rule, DlbmInRule):
        unknown = sorted(code for code in rule.dlbm_ids if code not in closed_set.dlbm_ids)
        if unknown:
            return f"unknown_dlbm_ids:{','.join(unknown)}"
    elif isinstance(rule, (WithinZoneRule, NotWithinZoneRule)):
        if closed_set.zone_ids and rule.zone_id not in closed_set.zone_ids:
            return f"unknown_zone_id:{rule.zone_id}"
    elif isinstance(rule, NearPoiRule):
        if closed_set.poi_ids and rule.poi_id not in closed_set.poi_ids:
            return f"unknown_poi_id:{rule.poi_id}"
    elif isinstance(rule, RoadDistanceLtRule):
        if rule.road_id and closed_set.road_ids and rule.road_id not in closed_set.road_ids:
            return f"unknown_road_id:{rule.road_id}"
    for child in getattr(rule, "children", []) or []:
        reason = _validate_rule_against_closed_set(child, closed_set)
        if reason:
            return reason
    return None


def _run_deterministic_dry_run(
    category_code: str,
    category: _VocabularyCategoryOutput,
    rules: list[TypingRule],
    closed_set: _BundleClosedSet,
    sanity_hook: Callable[[VocabularyDryRunResult], str | None] | None = None,
) -> VocabularyDryRunResult:
    from app.domain.materialization.zoning.vocab_rules import evaluate_rules, parcel_to_context

    diagnostics: list[str] = []
    matched_bsms: list[str] = []
    matched_area_ha = 0.0
    if not rules:
        diagnostics.append("dry_run_skipped_no_rules")
    else:
        for parcel in closed_set.parcel_contexts:
            if evaluate_rules(rules, parcel_to_context(parcel)):
                bsm = _clean_text(parcel.get("bsm", ""), limit=120)
                if bsm:
                    matched_bsms.append(bsm)
                matched_area_ha += float(parcel.get("area_ha", 0.0) or 0.0)
        if rules and not matched_bsms:
            diagnostics.append("dry_run_empty")
        if closed_set.parcel_count and len(matched_bsms) > closed_set.parcel_count:
            diagnostics.append("cardinality_invalid")
        if closed_set.total_area_ha and matched_area_ha > closed_set.total_area_ha + 1e-6:
            diagnostics.append("area_invalid")
    result = VocabularyDryRunResult(
        category_code=category_code,
        name_zh=category.name_zh,
        matched_bsms=matched_bsms,
        matched_count=len(matched_bsms),
        matched_area_ha=round(matched_area_ha, 6),
        source_span=category.source_span,
        diagnostics=diagnostics,
    )
    if sanity_hook is not None:
        hook_reason = sanity_hook(result)
        if hook_reason:
            result.diagnostics.append(_clean_text(hook_reason, limit=160))
    return result


def _category_code(item: _VocabularyCategoryOutput, rules: list[TypingRule]) -> str:
    identity = {
        "name_zh": item.name_zh,
        "is_protection": item.is_protection,
        "rules": [rule.model_dump(mode="json") for rule in rules],
        "source_span": item.source_span,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"FZ-{digest.upper()}"


def _compile_vocabulary_output(
    data: _VocabularyOutput,
    *,
    bundle: Any = None,
    max_rule_depth: int = _MAX_RULE_DEPTH,
    max_rule_nodes: int = _MAX_RULE_NODES,
    sanity_hook: Callable[[VocabularyDryRunResult], str | None] | None = None,
) -> VocabularyCompileResult:
    closed_set = _build_bundle_closed_set(bundle)
    categories: list[VocabularyCategory] = []
    quarantine: list[VocabularyQuarantineItem] = []
    dry_run: list[VocabularyDryRunResult] = []

    for item in data.categories:
        if not item.name_zh:
            quarantine.append(VocabularyQuarantineItem(name_zh="", reason="category_name_missing"))
            continue
        if not _is_hex_color(item.color):
            quarantine.append(
                VocabularyQuarantineItem(
                    name_zh=item.name_zh,
                    reason="category_color_invalid",
                    source_span=item.source_span,
                )
            )
            continue

        rule_nodes = list(item.rules or [])
        if not rule_nodes:
            quarantine.append(
                VocabularyQuarantineItem(
                    name_zh=item.name_zh,
                    reason="typed_rule_missing",
                    source_span=item.source_span,
                )
            )
            continue

        typed_rules: list[TypingRule] = []
        category_invalid_reason = ""
        for rule_node in rule_nodes:
            depth, nodes = _rule_depth_and_nodes(rule_node)
            if depth > max_rule_depth:
                category_invalid_reason = f"rule_depth_exceeded:{depth}>{max_rule_depth}"
                quarantine.append(
                    VocabularyQuarantineItem(
                        name_zh=item.name_zh,
                        reason=category_invalid_reason,
                        source_span=getattr(rule_node, "source_span", "") or item.source_span,
                        rule=getattr(rule_node, "rule", ""),
                    )
                )
                break
            if nodes > max_rule_nodes:
                category_invalid_reason = f"rule_nodes_exceeded:{nodes}>{max_rule_nodes}"
                quarantine.append(
                    VocabularyQuarantineItem(
                        name_zh=item.name_zh,
                        reason=category_invalid_reason,
                        source_span=getattr(rule_node, "source_span", "") or item.source_span,
                        rule=getattr(rule_node, "rule", ""),
                    )
                )
                break
            closed_set_reason = _validate_rule_against_closed_set(rule_node, closed_set)
            if closed_set_reason:
                category_invalid_reason = closed_set_reason
                quarantine.append(
                    VocabularyQuarantineItem(
                        name_zh=item.name_zh,
                        reason=closed_set_reason,
                        source_span=getattr(rule_node, "source_span", "") or item.source_span,
                        rule=getattr(rule_node, "rule", ""),
                    )
                )
                break
            typed_rules.append(_typing_rule_from_node(rule_node))

        if category_invalid_reason:
            continue

        category_code = _category_code(item, typed_rules)
        dry_run_result = _run_deterministic_dry_run(
            category_code,
            item,
            typed_rules,
            closed_set,
            sanity_hook=sanity_hook,
        )
        if any(diag in {"cardinality_invalid", "area_invalid"} for diag in dry_run_result.diagnostics):
            quarantine.append(
                VocabularyQuarantineItem(
                    name_zh=item.name_zh,
                    reason="dry_run_sanity_failed",
                    source_span=item.source_span,
                )
            )
            continue
        dry_run.append(dry_run_result)
        categories.append(
            VocabularyCategory(
                code=category_code,
                name_zh=item.name_zh,
                color=item.color,
                typing_rules=typed_rules,
                is_protection=item.is_protection,
            )
        )

    return VocabularyCompileResult(
        vocabulary=Vocabulary(name="l3_extracted", categories=categories),
        dry_run=dry_run,
        quarantine=quarantine,
    )


_VOCAB_PROMPT = """你是村庄规划功能区词汇提取助手。从下列 L3 报告的功能分区内容中提取功能区类别定义。

报告内容：
{reports}

当前运行时闭集（只能引用其中出现的 ID）：
{closed_set}

要求：
- 每个 category 必须给出 name_zh、合法 hex color、source_span、is_protection 和至少一个 rules
- rule 必须使用 discriminator 字段 `rule`，且只能来自：
  dlbm_in / within_zone / not_within_zone / slope_lt / road_distance_lt /
  near_poi / all / any / not
- 各 rule 只能填写自己允许的 typed 字段；不要输出旧 `kind/value/children` 格式或其他杂项
- source_span 保留原文依据短句
- color 必须是合法 hex（#RRGGBB）
- 没有直接原文依据或无法绑定到当前闭集 ID 的类别不要猜测
"""


async def _extract_vocabulary_llm(
    llm: Any,
    reports: Dict[str, str],
    *,
    bundle: Any = None,
    max_rule_depth: int = _MAX_RULE_DEPTH,
    max_rule_nodes: int = _MAX_RULE_NODES,
    sanity_hook: Callable[[VocabularyDryRunResult], str | None] | None = None,
) -> VocabularyCompileResult:
    reports_text = "\n\n".join(
        f"[{key}]\n{str(value or '')[:3000]}"
        for key, value in (reports or {}).items()
    )
    closed_set = _build_bundle_closed_set(bundle)
    prompt = _VOCAB_PROMPT.format(
        reports=reports_text[:_MAX_REPORT_CHARS],
        closed_set=json.dumps(
            {
                "dlbm_ids": sorted(closed_set.dlbm_ids),
                "zone_ids": sorted(closed_set.zone_ids),
                "poi_ids": sorted(closed_set.poi_ids),
                "road_ids": sorted(closed_set.road_ids),
            },
            ensure_ascii=False,
        ),
    )
    from app.infrastructure.llm.manager import LLMCallSpec, get_llm_manager
    from app.core.llm_config import get_llm_settings

    settings = get_llm_settings()
    stage_policy = settings.stage_policy("l3")
    data = await get_llm_manager().run_structured(
        LLMCallSpec(
            stage="L3",
            contract_key="materialization.vocabulary",
            response_model=_VocabularyOutput,
            call_type="closed_set",
            max_retries=2,
            timeout_s=stage_policy.timeout_s,
            max_tokens=min(2400, stage_policy.max_tokens),
            incomplete_output_max_tokens=4096,
            max_concurrent=stage_policy.max_concurrent,
            semaphore_scope="l3-materialization",
            temperature=0.1,
            allow_content_json=True,
        ),
        [{"role": "user", "content": prompt}],
        llm=llm,
        context={
            "closed_set": {
                "dlbm_ids": sorted(closed_set.dlbm_ids),
                "zone_ids": sorted(closed_set.zone_ids),
                "poi_ids": sorted(closed_set.poi_ids),
                "road_ids": sorted(closed_set.road_ids),
            }
        },
    )
    return _compile_vocabulary_output(
        data,
        bundle=bundle,
        max_rule_depth=max_rule_depth,
        max_rule_nodes=max_rule_nodes,
        sanity_hook=sanity_hook,
    )


async def extract_vocabulary_from_reports(
    reports: Dict[str, str],
    llm: Any = None,
    *,
    bundle: Any = None,
    max_rule_depth: int = _MAX_RULE_DEPTH,
    max_rule_nodes: int = _MAX_RULE_NODES,
    sanity_hook: Callable[[VocabularyDryRunResult], str | None] | None = None,
) -> Vocabulary:
    """Extract a session vocabulary from L3 reports.

    Invalid categories/rules are quarantined inside the compilation step and
    never registered as executable typing rules.
    """
    if llm is None:
        from app.core.settings import GIS_EXPLORE_LLM_ENABLED

        if not GIS_EXPLORE_LLM_ENABLED:
            raise RuntimeError("typed_vocabulary_extraction_unavailable")
        from app.core.settings import (
            GIS_EXPLORE_MAX_TOKENS,
            GIS_EXPLORE_TEMPERATURE,
        )
        from app.infrastructure.llm.factory import create_llm

        llm = create_llm(
            model=None,
            temperature=GIS_EXPLORE_TEMPERATURE,
            max_tokens=GIS_EXPLORE_MAX_TOKENS,
            streaming=False,
        )

    try:
        result = await _extract_vocabulary_llm(
            llm,
            reports,
            bundle=bundle,
            max_rule_depth=max_rule_depth,
            max_rule_nodes=max_rule_nodes,
            sanity_hook=sanity_hook,
        )
        if result.quarantine:
            logger.warning(
                "[VocabExtractor] quarantined %s categories/rules during validation",
                len(result.quarantine),
            )
        return result.vocabulary
    except Exception as exc:
        logger.error("[VocabExtractor] typed LLM extraction failed: %s", type(exc).__name__)
        raise RuntimeError("typed_vocabulary_extraction_failed") from exc


def register_session_vocabulary(session_id: str, vocab: Vocabulary) -> str:
    """Register the vocabulary under a session-scoped name and return it."""
    if not list(vocab.categories or []):
        raise ValueError("vocabulary_has_no_verified_categories")
    name = f"{session_id}_vocab"
    register_vocabulary(name, vocab)
    return name


__all__ = [
    "AllRule",
    "AnyRule",
    "DlbmInRule",
    "NearPoiRule",
    "NotRule",
    "NotWithinZoneRule",
    "RoadDistanceLtRule",
    "SlopeLtRule",
    "WithinZoneRule",
    "VocabularyCompileResult",
    "VocabularyDryRunResult",
    "VocabularyQuarantineItem",
    "_VocabularyCategoryOutput",
    "_VocabularyOutput",
    "_compile_vocabulary_output",
    "extract_vocabulary_from_reports",
    "register_session_vocabulary",
]
