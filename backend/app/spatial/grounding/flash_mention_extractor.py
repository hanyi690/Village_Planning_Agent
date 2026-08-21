"""Flash-LLM semantic place-entity extractor for GROUND place-name resolution.

Design 12 (PLACE_NAME_RESOLUTION): GROUND resolves closed-set specs through a
deterministic EvidenceGraph; mentions that still cannot bind go to the gate.
This module is the *self-service* middle step: before deferring to a HUMAN,
GROUND asks the flash model to rewrite/segment the raw planning prose into a
small list of typed place entities (mention / entity_type / role /
canonical_name / confidence).  The LLM only produces *semantic text and closed
set labels* - it never invents BSMs, coordinates or geometry.  Final BSMs still
come exclusively from EvidenceGraph / gazetteer / bundle.

The primary path uses Instructor/Pydantic so GROUND
receives typed entities it can match to specific named features (road/water/
facility/village) instead of falling back to a whole-DLMC parcel class. When
the structured call fails, the enhancer returns an explicit unresolved result;
no text-line protocol is accepted into GROUND.

Determinism & resume:
- Results are cached by sha256(content) in an in-memory dict plus an optional
  JSON file under the run directory, so LangGraph replay / resume never
  re-invokes the model for the same text.
- If the flash call fails or is disabled, the enhancer returns ``[]`` and
  GROUND falls back to its existing deterministic path (gate + HUMAN).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec
from app.infrastructure.logging import get_logger
from app.infrastructure.llm.factory import create_flash_llm

logger = get_logger(__name__)

_ROLE_SET = ("village", "water", "road", "facility", "landmark", "area")
_DIRECTION_SET = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}
_QUERY_SPEC_CACHE: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_QUERY_SPEC_CACHE_MAXSIZE = 256


def _ground_llm_disabled() -> bool:
    """Keep real flash calls opt-in while allowing explicitly injected models."""
    enabled = str(os.getenv("GROUND_LLM_ENABLED", "false")).strip().lower() in {
        "1", "true", "yes", "on"
    }
    disabled = any(
        str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}
        for name in ("DISABLE_GROUND_LLM", "DISABLE_GROUND_REPORT_LLM")
    )
    return not enabled or disabled


class SemanticPlaceEntity(BaseModel):
    """One typed place entity produced by the flash model.

    ``mention`` is the raw span; ``canonical_name`` is the core locatable name
    with prefixes/suffixes stripped.  Neither field is a BSM or coordinate.
    """

    mention: str = ""
    entity_type: str = "unknown"
    role: str = "unknown"
    canonical_name: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticPlaceEntitySet(BaseModel):
    entities: list[SemanticPlaceEntity] = []


_STRUCTURED_SYSTEM = """你是村庄规划 GIS 地名实体提取器。请从给定规划文本中提取所有“可在地图上定位的具体地名实体”。

规则：
1. 只输出地名文本与语义类型；严禁输出坐标、地块编号、BSM 或任何几何信息。
2. 优先提取：自然村/行政村名、河流水塘等水体名、道路名（含编号，如 122乡道）、设施名（祠堂/学校/广场/村委会/卫生站等）、地标与区域名。
3. 忽略无专名的纯类别词（如“道路”“水塘”“广场”“村内”等）。
4. 忽略方位与动作前缀（沿、村内、现状、新建、改造等）。
5. role 只能是：{roles}
6. 提取不到时返回空列表。

对每个实体，mention 保留规划文本原文片段，canonical_name 为去掉前后缀后的核心地名，confidence 为 0-1 的提取置信度。

待提取文本：{text}"""


_QUERY_SPEC_SYSTEM = """你是村庄规划 GIS 查询语义解析器。
请把用户的自然语言空间查询转换成一个受限 SpatialReferenceSpec。

硬性规则：
1. 只输出空间语义：方向（N/NE/E/SE/S/SW/W/NW）、nearby/within/
   sfIntersects/connected_via_road 等关系，以及查询中原文出现的村名、自然村、
   聚落、设施、道路、水体或地块类别词。
2. 方向必须表示“目标区域相对于村级规划范围或明确锚点的方位”。
   “东西向道路”“南北向道路”“东北-西南走向”是线的走向，不是区域方向，
   此时不要填写 direction。
3. 严禁输出 BSM、地块编号、source_feature_id、坐标、WKT、geometry、端点，
   也不得凭空补全任何地名。严禁输出规划执行对象 ID。
4. reference.filter 只允许 label_contains 或 rdf_type；label_contains 必须来自
   用户原文。没有可验证的空间语义时，返回一个没有 direction、reference、topo、
   distance_m 和 children 的 attributive spec。
5. type 只能是 directional、distance、topological、attributive、composed；
   composed 只能使用 and/or，并且 children 不超过 6 个。
6. semantic_terms 最多 8 个，只能逐字取自用户原文，用于在 L1、KG、Bundle
   标签和地址中召回候选，不得改写或补造同义词。
7. retrieval_scopes 只能从 facilities/hazards/roads/waters/parcels/zones 中选择。
   必须列出所有可能帮助定位的本地空间类别，而不只是最终对象。例如查询一个
   只在地质灾害点地址中出现的自然村时，应包含 hazards；需要返回周边建设地块时
   还应包含 parcels。它只控制候选召回，不代表最终选择。
8. 复杂查询优先把 semantic_terms 和 retrieval_scopes 填在根对象；不要为了表达
   “相关”“相邻”“适合”等普通语义而创建 children。若没有可验证的方向、距离或
   拓扑关系，type 使用 attributive，reference、direction、relation、distance_m、
   topo、attr_filter、children 保持空值/空数组。
9. 除 semantic_terms、retrieval_scopes 以及确实可验证的 direction/topo/reference
   外，其余字段必须保持默认空值：不要填写 target_id、spec_id、project_ref、
   intervention_id、source_*、l1_fact_refs 或任何执行对象信息。

例如对“请利用炉池地址相关的地质灾害点及其相邻地块，定位炉池自然村内适合建设文化服务设施的一小片用地”，
必须使用 type=attributive 且 children=[]；semantic_terms 从原文逐字选择
[“炉池”, “地质灾害点”, “相邻地块”, “炉池自然村”, “文化服务设施”] 中的一部分，
retrieval_scopes 至少包含 [“hazards”, “parcels”, “facilities”]；不要输出 BSM、坐标
或自行创建“炉池村”等改写名称。

用户查询：{query}"""


@dataclass
class MentionCandidate:
    """A typed place entity produced by the enhancer."""

    mention: str = ""
    entity_type: str = "unknown"
    role: str = "unknown"
    canonical_name: str = ""
    confidence: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)


def _query_term_in_text(term: str, query: str) -> bool:
    """Accept only source text terms, allowing Chinese village suffixes."""
    folded_term = "".join(str(term or "").casefold().split())
    folded_query = "".join(str(query or "").casefold().split())
    if not folded_term or folded_term in folded_query:
        return bool(folded_term)
    for suffix in ("自然村", "村"):
        if folded_term.endswith(suffix) and folded_term[: -len(suffix)] in folded_query:
            return True
    return False


def _validate_query_spec(spec: Any, query: str, *, depth: int = 0) -> bool:
    """Reject model output that crosses the semantic-only query boundary."""
    if not isinstance(spec, SpatialReferenceSpec) or depth > 3:
        return False
    if spec.type not in {"directional", "distance", "topological", "attributive", "composed"}:
        return False
    if spec.direction and spec.direction not in _DIRECTION_SET:
        return False
    if spec.distance_m is not None and not (0.0 <= float(spec.distance_m) <= 5000.0):
        return False
    if spec.op and spec.op not in {"and", "or"}:
        return False
    if spec.topo and spec.topo not in {
        "sfTouches", "sfWithin", "sfIntersects", "nearby", "connected_via_road"
    }:
        return False
    if any(
        str(getattr(spec, field, "") or "").strip()
        for field in ("intervention_id", "target_id", "spec_id", "project_ref")
    ):
        return False
    if spec.type == "composed" and (spec.op not in {"and", "or"} or len(spec.children) > 6):
        return False
    if spec.type != "composed" and spec.children:
        return False
    if spec.reference is not None:
        filters = dict(spec.reference.filter or {})
        if set(filters) - {"label_contains", "rdf_type"}:
            return False
        label = str(filters.get("label_contains") or "").strip()
        if label and not _query_term_in_text(label, query):
            return False
        rdf_type = str(filters.get("rdf_type") or "").strip()
        if rdf_type and len(rdf_type) > 80:
            return False
    for key, value in dict(spec.attr_filter or {}).items():
        key_text = str(key or "").casefold()
        if any(token in key_text for token in ("bsm", "geometry", "coordinate", "wkt", "source_feature")):
            return False
        if isinstance(value, str) and value and not _query_term_in_text(value, query):
            return False
    if any(not _query_term_in_text(term, query) for term in spec.semantic_terms):
        return False
    return all(_validate_query_spec(child, query, depth=depth + 1) for child in spec.children)


def _query_spec_has_semantics(spec: SpatialReferenceSpec) -> bool:
    if (
        spec.direction
        or spec.topo
        or spec.distance_m is not None
        or spec.semantic_terms
        or spec.retrieval_scopes
    ):
        return True
    if spec.reference and any(str(value or "").strip() for value in (spec.reference.filter or {}).values()):
        return True
    if any(str(value or "").strip() for value in (spec.attr_filter or {}).values()):
        return True
    return any(_query_spec_has_semantics(child) for child in spec.children)


def _query_spec_cache_key(query: str) -> str:
    return hashlib.sha256((query or "").strip().encode("utf-8")).hexdigest()


def _cache_query_spec(query: str, spec: SpatialReferenceSpec) -> None:
    key = _query_spec_cache_key(query)
    _QUERY_SPEC_CACHE[key] = spec.model_dump(mode="json")
    _QUERY_SPEC_CACHE.move_to_end(key)
    while len(_QUERY_SPEC_CACHE) > _QUERY_SPEC_CACHE_MAXSIZE:
        _QUERY_SPEC_CACHE.popitem(last=False)


async def extract_spatial_reference_spec(
    query: str,
    *,
    llm: Any = None,
    budget: Optional[Dict[str, Any]] = None,
    raise_on_failure: bool = False,
) -> Optional[SpatialReferenceSpec]:
    """Parse query semantics with one bounded LLM call.

    The result is deliberately a pre-geometric ``SpatialReferenceSpec``.  It
    is cached by query text and is never trusted as a BSM/geometry source.
    ``None`` means the provider is unavailable or the output did not pass the
    closed-set/source-text validation; callers must use deterministic graph
    fallback and preserve ambiguity.
    """
    key_text = str(query or "").strip()
    if not key_text:
        return None
    cached = _QUERY_SPEC_CACHE.get(_query_spec_cache_key(key_text))
    if cached is not None:
        try:
            return SpatialReferenceSpec.model_validate(cached)
        except Exception:
            _QUERY_SPEC_CACHE.pop(_query_spec_cache_key(key_text), None)
    model = llm
    if model is None:
        if _ground_llm_disabled():
            logger.info("[flash-query-spec] real grounding LLM is disabled")
            return None
        try:
            from app.core.settings import GROUND_QUERY_SPEC_MAX_TOKENS

            model = create_flash_llm(
                max_tokens=GROUND_QUERY_SPEC_MAX_TOKENS,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[flash-query-spec] flash LLM unavailable: %s", exc)
            if raise_on_failure:
                raise RuntimeError("ground query parser provider unavailable") from exc
            return None
    try:
        from app.infrastructure.llm.structured import run_structured_output
        from app.core.settings import GROUND_QUERY_SPEC_MAX_TOKENS
        from app.spatial.grounding.call_budget import (
            reserve_ground_llm_call,
            run_ground_llm_call,
        )

        timeout = reserve_ground_llm_call(budget)
        if timeout is None:
            return None
        messages = [
            {"role": "system", "content": _QUERY_SPEC_SYSTEM.format(query=key_text[:800])},
            {"role": "user", "content": "请只返回 SpatialReferenceSpec 的 JSON 结构。"},
        ]

        async def _invoke():
            return await run_structured_output(
                SpatialReferenceSpec,
                messages,
                max_retries=1,
                timeout=timeout,
                temperature=0.0,
                max_tokens=GROUND_QUERY_SPEC_MAX_TOKENS,
                llm=model,
                allow_content_json_fallback=False,
            )

        response = await run_ground_llm_call(budget, timeout, _invoke)
        spec = response if isinstance(response, SpatialReferenceSpec) else SpatialReferenceSpec.model_validate(response)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[flash-query-spec] structured call failed: %s", exc)
        if raise_on_failure:
            raise RuntimeError("ground query parser structured output failed") from exc
        return None
    if not _validate_query_spec(spec, key_text) or not _query_spec_has_semantics(spec):
        logger.warning(
            "[flash-query-spec] output rejected by source-text contract: "
            "type=%s semantic_terms=%r retrieval_scopes=%r reference=%r "
            "children=%d forbidden_fields=%r",
            getattr(spec, "type", ""),
            list(getattr(spec, "semantic_terms", []) or []),
            list(getattr(spec, "retrieval_scopes", []) or []),
            getattr(spec, "reference", None),
            len(getattr(spec, "children", []) or []),
            {
                field: getattr(spec, field, "")
                for field in (
                    "intervention_id",
                    "target_id",
                    "spec_id",
                    "project_ref",
                    "source_binding_ref",
                    "source_collection_key",
                    "source_snapshot_ref",
                    "source_feature_digest",
                    "l1_fact_refs",
                )
                if getattr(spec, field, None)
            },
        )
        logger.warning(
            "[flash-query-spec] rejected child details: %r",
            [
                child.model_dump(mode="json")
                if hasattr(child, "model_dump")
                else str(child)
                for child in (getattr(spec, "children", []) or [])
            ],
        )
        if raise_on_failure:
            raise ValueError("ground query parser output rejected by source-text contract")
        return None
    _cache_query_spec(key_text, spec)
    return spec


def create_flash_llm_safe():
    """Return a flash LLM or None when the provider is unavailable.

    GROUND enhancement is best-effort; callers must tolerate None.
    """
    if _ground_llm_disabled():
        logger.info("[flash-mention] real grounding LLM is disabled")
        return None
    try:
        return create_flash_llm(max_tokens=300, temperature=0.1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[flash-mention] flash LLM unavailable: %s", exc)
        return None


def _content_key(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class MentionCache:
    """sha256(text) -> parsed mention list, backed by memory + optional JSON."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self._data: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8")
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                self._data = {str(k): v for k, v in loaded.items()}
        except Exception as exc:  # noqa: BLE001 - cache must never break GROUND
            logger.warning("[flash-mention] cache load failed: %s", exc)

    def _flush(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[flash-mention] cache flush failed: %s", exc)

    def get(self, text: str) -> Optional[List[Dict[str, Any]]]:
        return self._data.get(_content_key(text))

    def put(self, text: str, mentions: List[Dict[str, Any]]) -> None:
        self._data[_content_key(text)] = mentions
        self._flush()


def _parse_structured_payload(payload: Any) -> List[MentionCandidate]:
    """Parse a structured-output response into typed ``MentionCandidate``s.

    Handles only typed ``SemanticPlaceEntitySet`` or a strict mapping. Invalid
    roles/mentions are dropped, never fabricated.
    """
    raw: Any = None
    if isinstance(payload, SemanticPlaceEntitySet):
        raw = payload.entities
    else:
        try:
            raw = SemanticPlaceEntitySet.model_validate(payload).entities
        except Exception:
            return []
    if not isinstance(raw, list):
        return []

    results: List[MentionCandidate] = []
    seen = set()
    for item in raw:
        try:
            entity = (
                item
                if isinstance(item, SemanticPlaceEntity)
                else SemanticPlaceEntity.model_validate(item)
            )
        except Exception:
            continue
        mention = (entity.mention or "").strip()
        if not mention or len(mention) < 2 or mention in seen:
            continue
        role = entity.role if entity.role in _ROLE_SET else "unknown"
        canonical = (entity.canonical_name or "").strip() or mention
        seen.add(mention)
        results.append(
            MentionCandidate(
                mention=mention,
                entity_type=entity.entity_type if entity.entity_type else role,
                role=role,
                canonical_name=canonical,
                confidence=float(entity.confidence or 0.0),
                evidence={"source": "flash_llm_structured"},
            )
        )
    return results


async def _extract_structured(
    model: Any,
    key_text: str,
    *,
    budget: Optional[Dict[str, Any]] = None,
) -> Optional[List[MentionCandidate]]:
    """Run the only authoritative mention path; failures remain unresolved."""
    prompt = _STRUCTURED_SYSTEM.format(
        roles="|".join(_ROLE_SET), text=key_text[:600]
    )
    try:
        # MiniMax rejects a system-only request with error 2013
        # ("chat content is empty"), so always pair the instructions with a
        # non-empty user turn that carries the text to process.
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请从上述文本中提取地点实体。"},
        ]
        from app.infrastructure.llm.structured import run_structured_output
        from app.spatial.grounding.call_budget import (
            reserve_ground_llm_call,
            run_ground_llm_call,
        )

        timeout = reserve_ground_llm_call(budget)
        if timeout is None:
            return None
        async def _invoke_structured():
            return await run_structured_output(
                SemanticPlaceEntitySet,
                messages,
                max_retries=1,
                timeout=timeout,
                temperature=0.1,
                max_tokens=300,
                llm=model,
                allow_content_json_fallback=False,
            )

        response = await run_ground_llm_call(budget, timeout, _invoke_structured)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[flash-mention] structured call failed: %s", exc)
        return None
    return _parse_structured_payload(response)


async def extract_mentions(
    text: str,
    cache: Optional[MentionCache] = None,
    llm: Any = None,
    budget: Optional[Dict[str, Any]] = None,
) -> List[MentionCandidate]:
    """Enhance raw prose into typed place entities (text + closed-set labels)."""
    if not text or not text.strip():
        return []
    key_text = text.strip()
    if cache is not None:
        hit = cache.get(key_text)
        if hit is not None:
            return [_candidate_from_dict(item) for item in hit]

    model = llm
    if model is None:
        if _ground_llm_disabled():
            logger.info("[flash-mention] real grounding LLM is disabled")
            return []
        try:
            model = create_flash_llm(max_tokens=300, temperature=0.1)
        except Exception as exc:  # noqa: BLE001 - unresolved is explicit
            logger.warning("[flash-mention] flash LLM unavailable: %s", exc)
            return []

    # Only typed structured output can enter GROUND.  There is deliberately no
    # A failed or empty model response is an explicit unresolved result and the
    # caller must preserve the HUMAN/defer path.
    mentions = await _extract_structured(model, key_text, budget=budget)
    if mentions is None:
        logger.warning(
            "[flash-mention] structured semantic extraction unresolved; no text fallback is permitted"
        )
        return []
    if not mentions:
        logger.info("[flash-mention] structured semantic extraction returned no locatable entities")
    if cache is not None:
        cache.put(key_text, [_candidate_to_dict(m) for m in mentions])
    return mentions


def _candidate_to_dict(c: MentionCandidate) -> Dict[str, Any]:
    return {
        "mention": c.mention,
        "entity_type": c.entity_type,
        "role": c.role,
        "canonical_name": c.canonical_name,
        "confidence": c.confidence,
        "evidence": c.evidence,
    }


def _candidate_from_dict(item: Dict[str, Any]) -> MentionCandidate:
    return MentionCandidate(
        mention=str(item.get("mention") or ""),
        entity_type=str(item.get("entity_type") or "unknown"),
        role=str(item.get("role") or "unknown"),
        canonical_name=str(item.get("canonical_name") or ""),
        confidence=float(item.get("confidence") or 0.0),
        evidence=dict(item.get("evidence") or {}),
    )


__all__ = [
    "MentionCandidate",
    "MentionCache",
    "SemanticPlaceEntity",
    "SemanticPlaceEntitySet",
    "extract_mentions",
    "extract_spatial_reference_spec",
]
