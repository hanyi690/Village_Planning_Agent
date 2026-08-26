"""Natural-village -> residential-cluster(s) mapping for L1/GROUND resolution.

A natural village is a first-class spatial anchor: it is NOT one-to-one with a
residential cluster.  One village may span several 宅基地 clusters.  This module
derives *real* residential clusters from the bundle's 宅基地 (DLBM 1340) parcels
and lets the flash LLM decide which cluster(s) belong to each report-named
natural village (many-to-one), using only report evidence + cluster geometry.

Evidence-first / fail-closed:
- Geometry and BSMs always come from the bundle clusters, never from the LLM.
- A village is assigned only when the report provides a verifiable evidence
  snippet (verbatim substring); villages without evidence stay unresolved.
- The LLM only produces stable entity_ref -> candidate_id decisions; no coordinates.

Determinism & resume:
- The cluster derivation is fully deterministic.
- The mapping is cached by sha256(report excerpt + village order) and can be
  replayed on resume; llm=None or no report evidence yields an empty mapping.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional

from app.infrastructure.logging import get_logger
from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict as _ConfigDict
from pydantic import Field as _Field
from pydantic import model_validator as _model_validator

logger = get_logger(__name__)

_RESIDENTIAL_DLMC = ("1340", "0702")
_CLUSTER_DISTANCE_DEG = 0.008  # ~800m at 24N
_MAPPING_SCHEMA_VERSION = "grounding-stable-id-batch-v1"
_REPORT_SEGMENT_ID = "report"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _stable_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def stable_entity_ref(kind: str, value: str) -> str:
    """Build a stable input reference without exposing a positional ordinal."""
    normalized_kind = str(kind or "entity").strip().lower() or "entity"
    normalized_value = " ".join(str(value or "").split())
    return f"{normalized_kind}:{_stable_digest(normalized_value)[:24]}"


class SourceSpan(_BaseModel):
    """A source-bound report span carried by every accepted place decision."""

    model_config = _ConfigDict(extra="forbid")

    segment_id: str = _Field(min_length=1)
    start: int = _Field(ge=0)
    end: int = _Field(gt=0)
    quote_hash: str = _Field(min_length=1)

    @_model_validator(mode="after")
    def _valid_range(self) -> "SourceSpan":
        if self.end <= self.start:
            raise ValueError("source span end must be greater than start")
        return self


class _GMappingDecision(_BaseModel):
    """The only proposal shape accepted from the grounding provider."""

    model_config = _ConfigDict(extra="forbid")

    entity_ref: str = _Field(min_length=1)
    status: Literal["mapped", "unresolved", "pending"]
    candidate_ids: list[str] = _Field(default_factory=list)
    source_span: Optional[SourceSpan] = None
    reason_code: str = ""

    @_model_validator(mode="after")
    def _shape_closed(self) -> "_GMappingDecision":
        self.candidate_ids = [str(value).strip() for value in self.candidate_ids if str(value).strip()]
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate_ids must not contain duplicates")
        if self.status == "mapped" and not self.candidate_ids:
            raise ValueError("mapped decision requires candidate_ids")
        if self.status == "mapped" and self.source_span is None:
            raise ValueError("mapped decision requires source_span")
        if self.status != "mapped" and self.candidate_ids:
            raise ValueError("unresolved/pending decisions cannot cite candidates")
        if self.status != "mapped" and not self.reason_code.strip():
            raise ValueError("unresolved/pending decision requires reason_code")
        return self


class _GMappingSet(_BaseModel):
    """Strict provider envelope; membership is checked after parsing."""

    model_config = _ConfigDict(extra="forbid")

    decisions: list[_GMappingDecision] = _Field(default_factory=list)


class MappingResult(dict):
    """Exact-batch mapping keyed only by stable input refs.

    The dictionary contains one decision for every expected input ref.  Provider
    refs outside that closed set are retained in ``unknown_refs`` for audit and
    never converted into a candidate by guessing.
    """

    def __init__(
        self,
        decisions: Iterable[Mapping[str, Any]] = (),
        *,
        unknown_refs: Iterable[str] = (),
        duplicate_refs: Iterable[str] = (),
        schema_digest: str = "",
        input_digest: str = "",
        candidate_set_digest: str = "",
    ) -> None:
        super().__init__((str(item["entity_ref"]), dict(item)) for item in decisions)
        self.unknown_refs = list(dict.fromkeys(str(value) for value in unknown_refs if str(value)))
        self.duplicate_refs = list(dict.fromkeys(str(value) for value in duplicate_refs if str(value)))
        self.schema_digest = schema_digest
        self.input_digest = input_digest
        self.candidate_set_digest = candidate_set_digest

    @property
    def pending(self) -> dict[str, dict[str, Any]]:
        return {key: value for key, value in self.items() if value.get("status") == "pending"}

    @property
    def unresolved(self) -> dict[str, dict[str, Any]]:
        return {key: value for key, value in self.items() if value.get("status") == "unresolved"}


@dataclass
class VillageCluster:
    index: int
    centroid: tuple
    bsms: List[str] = field(default_factory=list)
    parcel_count: int = 0
    area_ha: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)
    cluster_id: str = ""

    @property
    def entity_id(self) -> str:
        return self.cluster_id


def _candidate_identity(
    *,
    role: str,
    bsms: Iterable[str],
    centroid: Optional[tuple] = None,
    source_identity: str = "",
) -> str:
    """Return an order-independent ID for one input candidate."""
    normalized_bsms = sorted({str(value).strip() for value in bsms if str(value).strip()})
    identity = {
        "role": str(role or "candidate"),
        "bsms": normalized_bsms,
        "source_identity": str(source_identity or ""),
        "centroid": [round(float(value), 12) for value in centroid] if centroid else None,
    }
    return f"cluster:{_stable_digest(identity)[:24]}"


def _finalize_cluster_ids(clusters: List[VillageCluster], role: str) -> None:
    for cluster in clusters:
        if not cluster.cluster_id:
            cluster.cluster_id = _candidate_identity(
                role=role,
                bsms=cluster.bsms,
                centroid=cluster.centroid,
                source_identity=str(cluster.features.get("source_identity") or ""),
            )


def build_landuse_bodies(
    parcels: List[Any],
    markers: tuple,
    distance_deg: float = _CLUSTER_DISTANCE_DEG,
) -> List[VillageCluster]:
    """Cluster landuse parcels whose DLBM/DLMC/name carries any marker into
    deterministic spatial bodies (e.g. 宅基地 -> residential settlements,
    水域/河流 -> water bodies).  Geometry always comes from the parcels.
    """
    from app.spatial.grounding.grounding import build_parcel_centroid_cache

    cache = build_parcel_centroid_cache(parcels)
    selected = []
    for parcel in parcels:
        code = str(getattr(parcel, "dlbm", "") or "") or str(getattr(parcel, "dlmc", "") or "")
        name = str(getattr(parcel, "name", "") or "")
        text = f"{code} {name}"
        if not any(marker in text for marker in markers):
            continue
        bsm = str(getattr(parcel, "bsm", "") or "")
        centroid = cache.get(bsm) or cache.get(str(getattr(parcel, "bsm", None)))
        if centroid is None:
            continue
        area = float(getattr(parcel, "area_sqm", 0) or 0) / 10000.0
        selected.append((bsm, centroid, area))
    if not selected:
        return []

    clusters: List[VillageCluster] = []
    member_pts: List[List[tuple]] = []
    for bsm, centroid, area in selected:
        placed = False
        for cluster in clusters:
            if math.hypot(centroid[0] - cluster.centroid[0], centroid[1] - cluster.centroid[1]) < distance_deg:
                cluster.bsms.append(bsm)
                cluster.parcel_count += 1
                cluster.area_ha += area
                n = cluster.parcel_count
                cluster.centroid = (
                    (cluster.centroid[0] * (n - 1) + centroid[0]) / n,
                    (cluster.centroid[1] * (n - 1) + centroid[1]) / n,
                )
                member_pts[clusters.index(cluster)].append(centroid)
                placed = True
                break
        if not placed:
            clusters.append(VillageCluster(
                index=len(clusters),
                centroid=centroid,
                bsms=[bsm],
                parcel_count=1,
                area_ha=area,
            ))
            member_pts.append([centroid])
    # Stable ordering: largest settlement first, then west->east, south->north
    # and finally the sorted BSM set.  Candidate identity is independent of
    # the provider's response order.
    ordered = sorted(
        zip(clusters, member_pts),
        key=lambda pair: (
            -pair[0].parcel_count,
            round(pair[0].centroid[0], 12),
            round(pair[0].centroid[1], 12),
            tuple(sorted(str(bsm) for bsm in pair[0].bsms)),
        ),
    )
    clusters = [pair[0] for pair in ordered]
    member_pts = [pair[1] for pair in ordered]
    for i, cluster in enumerate(clusters):
        cluster.index = i
    _finalize_cluster_ids(clusters, "landuse")
    _attach_body_features(clusters, member_pts)
    return clusters


def _relative_position(dx: float, dy: float) -> str:
    """Map a vector from the village centre to a compass-ish label."""
    ns = "北" if dy > 0 else ("南" if dy < 0 else "")
    ew = "东" if dx > 0 else ("西" if dx < 0 else "")
    if ns and ew:
        # dominant axis decides 东北/东南/西北/西南 vs plain 北/东
        return f"{ew}{ns}" if abs(dx) > abs(dy) else f"{ns}{ew}"
    return f"{ns}{ew}" or "中部"


def _attach_body_features(
    clusters: List[VillageCluster],
    member_pts: List[List[tuple]],
) -> None:
    """Give every body candidate semantic features the LLM can match report
    clues to (GER-LLM featurizer): position relative to the village centre,
    span (km) and shape (elongated vs compact)."""
    pts = [p for group in member_pts for p in group]
    if not pts:
        return
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    for cluster, group in zip(clusters, member_pts):
        if not group:
            continue
        rel = _relative_position(cluster.centroid[0] - cx, cluster.centroid[1] - cy)
        xs = [p[0] for p in group]
        ys = [p[1] for p in group]
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        span_km = max(math.hypot(dx * 102.0, dy * 111.0), 0.05)
        shape = "长条" if (max(dx, dy) > 0 and max(dx, dy) > 3 * min(dx, dy) + 0.0005) else "面状"
        cluster.features["方位"] = rel
        cluster.features["跨度km"] = round(span_km, 2)
        cluster.features["形态"] = shape


def build_village_clusters(parcels: List[Any]) -> List[VillageCluster]:
    """Cluster 宅基地 parcels into residential settlements (deterministic)."""
    return build_landuse_bodies(
        parcels,
        (*_RESIDENTIAL_DLMC, "宅基地", "村庄建设用地", "农村居民点"),
    )


_PROMPT_TEMPLATE = """你是村庄规划 GIS 证据编译器。只做闭集候选选择，不创造地点。
待核对实体闭集（必须逐项返回 entity_ref）：
{villages}

候选闭集（只能引用 candidate_id）：
{clusters}

任务：把候选分配到输入实体；一个实体可以引用多个候选，但同一候选只能归属于一个实体。
只允许根据报告摘录中明确出现的名称、方位、坐标或可核对空间关系建立映射。
禁止按名称顺序、候选顺序、规模、常识或猜测分配；候选为空或多解时返回 pending 或 unresolved，不能默认选择。

只输出严格 JSON：
{{"decisions": [{{"entity_ref": "输入闭集中的 ref", "status": "mapped|unresolved|pending", "candidate_ids": ["候选闭集中的 candidate_id"], "source_span": {{"segment_id": "report", "start": 0, "end": 1, "quote_hash": "sha256"}}, "reason_code": ""}}]}}。
mapped 必须有至少一个 candidate_id 和报告原文 source_span；unresolved/pending 不得携带候选，并填写 reason_code。
必须对输入闭集每个 entity_ref 恰好返回一次；不要输出其它字段或文字。"""


_WATER_PROMPT_TEMPLATE = """你是村庄规划 GIS 证据编译器。只做闭集候选选择，不创造水体。
待核对实体闭集（必须逐项返回 entity_ref）：
{villages}

候选闭集（只能引用 candidate_id）：
{clusters}

一个水体可能由多个地块组成；同一候选只能归属于一个实体。
只允许根据报告摘录中明确出现的名称、方位、流向或可核对空间关系建立映射。
禁止按名称顺序、候选顺序、规模、常识或猜测分配；候选为空或多解时返回 pending 或 unresolved，不能默认选择。

只输出严格 JSON，字段与上面的 decisions 合同完全一致。
必须对输入闭集每个 entity_ref 恰好返回一次；不要输出其它字段或文字。"""


def _cache_path(run_root: Optional[Path]) -> Optional[Path]:
    if run_root is None:
        return None
    return (run_root / "village-cluster-map.json").resolve()


def _candidate_line(candidate: VillageCluster) -> str:
    features = dict(candidate.features or {})
    features.pop("source_identity", None)
    extra = " ".join(f"{key}={value}" for key, value in features.items())
    return (
        f"- candidate_id={candidate.cluster_id} "
        f"centroid=({candidate.centroid[0]:.5f},{candidate.centroid[1]:.5f}) "
        f"parcel_count={candidate.parcel_count} area_ha={candidate.area_ha:.2f} {extra}"
    ).rstrip()


def _expected_entities(names: Iterable[str], entity_kind: str) -> list[dict[str, str]]:
    expected: list[dict[str, str]] = []
    for name in names or []:
        display_name = " ".join(str(name or "").split())
        if not display_name:
            continue
        expected.append({
            "entity_ref": stable_entity_ref(entity_kind, display_name),
            "display_name": display_name,
        })
    return expected


def _candidate_set_digest(bodies: Iterable[VillageCluster]) -> str:
    descriptors = []
    for candidate in bodies or []:
        descriptors.append({
            "candidate_id": candidate.cluster_id,
            "bsms": sorted(str(value) for value in candidate.bsms),
            "centroid": [round(float(value), 12) for value in candidate.centroid],
            "parcel_count": int(candidate.parcel_count),
            "area_ha": round(float(candidate.area_ha), 8),
            "features": dict(candidate.features or {}),
        })
    return _stable_digest(sorted(descriptors, key=lambda item: item["candidate_id"]))


def _mapping_input_digest(
    *,
    cache_key_prefix: str,
    report_text: str,
    expected: list[dict[str, str]],
    prompt_kwargs: Optional[Dict[str, Any]],
    source_artifact_ref: str,
    source_artifact_digest: str,
    spatial_evidence: Optional[Mapping[str, Any]],
) -> str:
    return _stable_digest({
        "cache_key_prefix": cache_key_prefix,
        "report_text": report_text,
        "expected": expected,
        "prompt_kwargs": prompt_kwargs or {},
        "source_artifact_ref": source_artifact_ref,
        "source_artifact_digest": source_artifact_digest,
        "spatial_evidence": spatial_evidence or {},
    })


def _empty_decision(item: Mapping[str, str], status: str, reason_code: str) -> dict[str, Any]:
    return {
        "entity_ref": item["entity_ref"],
        "display_name": item["display_name"],
        "status": status,
        "candidate_ids": [],
        "source_span": None,
        "reason_code": reason_code,
    }


def _pending_result(expected: list[dict[str, str]], reason_code: str) -> MappingResult:
    return MappingResult(
        [_empty_decision(item, "pending", reason_code) for item in expected]
    )


def _unresolved_result(expected: list[dict[str, str]], reason_code: str) -> MappingResult:
    return MappingResult(
        [_empty_decision(item, "unresolved", reason_code) for item in expected]
    )


def _annotate_result(
    result: MappingResult,
    *,
    schema_digest: str,
    input_digest: str,
    candidate_set_digest: str,
) -> MappingResult:
    result.schema_digest = schema_digest
    result.input_digest = input_digest
    result.candidate_set_digest = candidate_set_digest
    return result


def _source_span_valid(span: Optional[SourceSpan], report_text: str, expected_name: str) -> bool:
    if span is None or span.segment_id != _REPORT_SEGMENT_ID:
        return False
    if span.start < 0 or span.end > len(report_text) or span.end <= span.start:
        return False
    quote = report_text[span.start:span.end]
    if not quote or hashlib.sha256(quote.encode("utf-8")).hexdigest() != span.quote_hash:
        return False
    return expected_name in quote or expected_name.removesuffix("村") in quote


def _load_mapping_cache(
    cache: Optional[Path],
    *,
    schema_digest: str,
    input_digest: str,
    candidate_digest: str,
    expected: list[dict[str, str]],
    report_text: str,
    candidate_ids: set[str],
) -> Optional[MappingResult]:
    if cache is None or not cache.exists():
        return None
    try:
        raw = json.loads(cache.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        if (
            raw.get("schema_version") != _MAPPING_SCHEMA_VERSION
            or raw.get("schema_digest") != schema_digest
            or raw.get("input_digest") != input_digest
            or raw.get("candidate_set_digest") != candidate_digest
        ):
            return None
        result = _validate_mapping_batch(
            _GMappingSet.model_validate(raw.get("value")),
            expected,
            [
                VillageCluster(index=0, centroid=(0.0, 0.0), cluster_id=cid)
                for cid in candidate_ids
            ],
            report_text,
            allowed_candidate_ids=None,
        )
        if set(result) != {item["entity_ref"] for item in expected}:
            return None
        return _annotate_result(
            result,
            schema_digest=schema_digest,
            input_digest=input_digest,
            candidate_set_digest=candidate_digest,
        )
    except Exception as exc:  # noqa: BLE001 - malformed cache is a miss
        logger.warning("[village-cluster] invalid cache treated as miss: %s", exc)
        return None


def _write_mapping_cache(
    cache: Optional[Path],
    schema_digest: str,
    input_digest: str,
    candidate_digest: str,
    result: MappingResult,
) -> None:
    if cache is None:
        return
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "schema_version": _MAPPING_SCHEMA_VERSION,
                    "schema_digest": schema_digest,
                    "input_digest": input_digest,
                    "candidate_set_digest": candidate_digest,
                    "value": {
                        "decisions": [
                            {
                                "entity_ref": item["entity_ref"],
                                "status": item["status"],
                                "candidate_ids": item.get("candidate_ids") or [],
                                "source_span": item.get("source_span"),
                                "reason_code": item.get("reason_code", ""),
                            }
                            for item in result.values()
                        ]
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp.replace(cache)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[village-cluster] cache flush failed: %s", exc)


def _validate_mapping_batch(
    response: _GMappingSet | Mapping[str, Any],
    expected: list[dict[str, str]],
    bodies: list[VillageCluster],
    report_text: str,
    *,
    allowed_candidate_ids: Optional[Mapping[str, set[str]]],
) -> MappingResult:
    """Validate exact membership and references without repairing semantics."""
    try:
        proposal = response if isinstance(response, _GMappingSet) else _GMappingSet.model_validate(response)
    except Exception:
        return _pending_result(expected, "proposal_schema_invalid")

    expected_counts = Counter(item["entity_ref"] for item in expected)
    expected_by_ref = {item["entity_ref"]: item for item in expected}
    raw_decisions = list(proposal.decisions)
    decision_counts = Counter(item.entity_ref for item in raw_decisions)
    unknown_refs = [
        ref for ref in decision_counts
        if ref not in expected_by_ref
    ]
    known_candidate_ids = {candidate.cluster_id for candidate in bodies}
    decisions: list[dict[str, Any]] = []
    for item in expected:
        ref = item["entity_ref"]
        if expected_counts[ref] > 1:
            decisions.append(_empty_decision(item, "pending", "duplicate_input_entity_ref"))
            continue
        matches = [decision for decision in raw_decisions if decision.entity_ref == ref]
        if len(matches) == 0:
            decisions.append(
                _empty_decision(
                    item,
                    "pending" if unknown_refs else "unresolved",
                    "unknown_entity_ref_in_batch" if unknown_refs else "missing_batch_member",
                )
            )
            continue
        if len(matches) != 1:
            decisions.append(_empty_decision(item, "pending", "duplicate_entity_ref"))
            continue

        proposal_item = matches[0]
        value = proposal_item.model_dump(mode="json")
        value["display_name"] = item["display_name"]
        if proposal_item.status != "mapped":
            decisions.append(value)
            continue
        selected = list(proposal_item.candidate_ids)
        if not selected or not set(selected).issubset(known_candidate_ids):
            value["status"] = "pending"
            value["candidate_ids"] = []
            value["source_span"] = None
            value["reason_code"] = "unknown_or_empty_candidate_id"
            decisions.append(value)
            continue
        if allowed_candidate_ids is not None:
            allowed = allowed_candidate_ids.get(ref, set())
            if not set(selected).issubset(allowed):
                value["status"] = "pending"
                value["candidate_ids"] = []
                value["source_span"] = None
                value["reason_code"] = "candidate_outside_source_anchor"
                decisions.append(value)
                continue
        if not _source_span_valid(proposal_item.source_span, report_text, item["display_name"]):
            value["status"] = "pending"
            value["candidate_ids"] = []
            value["source_span"] = None
            value["reason_code"] = "source_span_invalid"
            decisions.append(value)
            continue
        decisions.append(value)

    owner_by_candidate: dict[str, list[str]] = {}
    for item in decisions:
        if item.get("status") != "mapped":
            continue
        for candidate_id in item.get("candidate_ids") or []:
            owner_by_candidate.setdefault(candidate_id, []).append(item["entity_ref"])
    duplicate_candidate_refs: set[str] = set()
    duplicate_refs: list[str] = []
    for candidate_id, owners in owner_by_candidate.items():
        unique_owners = list(dict.fromkeys(owners))
        if len(unique_owners) <= 1:
            continue
        duplicate_refs.extend(unique_owners)
        duplicate_candidate_refs.update(unique_owners)
    if duplicate_candidate_refs:
        for item in decisions:
            if item["entity_ref"] in duplicate_candidate_refs:
                item["status"] = "pending"
                item["candidate_ids"] = []
                item["source_span"] = None
                item["reason_code"] = "duplicate_candidate_membership"
    return MappingResult(
        decisions,
        unknown_refs=unknown_refs,
        duplicate_refs=duplicate_refs,
    )


async def _map_bodies(
    bodies: List[VillageCluster],
    names: List[str],
    *,
    prompt_template: str,
    cache_key_prefix: str,
    prompt_kwargs: Optional[Dict[str, Any]] = None,
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
    entity_kind: str = "entity",
) -> MappingResult:
    """Run one typed closed-set mapping and preserve every disposition."""
    _finalize_cluster_ids(bodies, entity_kind)
    expected = _expected_entities(names, entity_kind)
    candidate_digest = _candidate_set_digest(bodies)
    input_digest = _mapping_input_digest(
        cache_key_prefix=cache_key_prefix,
        report_text=report_text,
        expected=expected,
        prompt_kwargs=prompt_kwargs,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        spatial_evidence=spatial_evidence,
    )
    schema_digest = _stable_digest(_GMappingSet.model_json_schema())
    cached = _load_mapping_cache(
        cache,
        schema_digest=schema_digest,
        input_digest=input_digest,
        candidate_digest=candidate_digest,
        expected=expected,
        report_text=report_text,
        candidate_ids={candidate.cluster_id for candidate in bodies},
    )
    if cached is not None:
        return cached

    def _finish(result: MappingResult) -> MappingResult:
        result = _annotate_result(
            result,
            schema_digest=schema_digest,
            input_digest=input_digest,
            candidate_set_digest=candidate_digest,
        )
        _write_mapping_cache(cache, schema_digest, input_digest, candidate_digest, result)
        return result

    if not expected:
        return _finish(MappingResult())
    if not bodies:
        return _finish(_pending_result(expected, "candidate_set_empty"))
    if not report_text.strip():
        return _finish(_unresolved_result(expected, "report_evidence_missing"))
    if llm is None:
        return _finish(_pending_result(expected, "structured_provider_unavailable"))

    try:
        from app.infrastructure.llm.call_budget import reserve_ground_llm_call, run_ground_llm_call
    except ImportError:
        from app.spatial.grounding.call_budget import reserve_ground_llm_call, run_ground_llm_call

    cluster_lines = "\n".join(_candidate_line(c) for c in bodies)
    entity_lines = "\n".join(
        f"- entity_ref={item['entity_ref']} mention={item['display_name']}"
        for item in expected
    )
    prompt = prompt_template.format(
        villages=entity_lines,
        clusters=cluster_lines,
        **(prompt_kwargs or {}),
    )
    prompt += (
        f"\n\ncandidate_set_digest={candidate_digest}"
        f" schema_digest={schema_digest}"
        f"\n报告原文（source_span 偏移相对于 segment_id=report）：\n{report_text}\n"
    )
    anchor_lines, allowed_candidate_ids = _spatial_anchor_prompt(
        expected,
        bodies,
        spatial_evidence,
    )
    if anchor_lines:
        prompt += f"\n\n跨源空间锚点（只能缩小候选闭集）：\n{anchor_lines}\n"
    structured_timeout = reserve_ground_llm_call(budget)
    response = None
    if structured_timeout is not None:
        async def _invoke_structured():
            return await _structured_mapping(
                llm,
                prompt,
                timeout=structured_timeout,
            )

        response = await run_ground_llm_call(budget, structured_timeout, _invoke_structured)
    if response is None:
        result = _pending_result(expected, "structured_output_unavailable")
    else:
        result = _validate_mapping_batch(
            response,
            expected,
            bodies,
            report_text,
            allowed_candidate_ids=allowed_candidate_ids or None,
        )
    return _finish(result)


async def assign_names(
    candidates: List[VillageCluster],
    names: List[str],
    *,
    prompt_template: str,
    cache_key_prefix: str,
    prompt_kwargs: Optional[Dict[str, Any]] = None,
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
    entity_kind: str = "entity",
) -> MappingResult:
    """Map names through a dynamic stable-ID candidate set."""
    return await _map_bodies(
        candidates,
        names,
        prompt_template=prompt_template,
        cache_key_prefix=cache_key_prefix,
        prompt_kwargs=prompt_kwargs,
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
        spatial_evidence=spatial_evidence,
        entity_kind=entity_kind,
    )


async def map_villages(
    clusters: List[VillageCluster],
    village_names: List[str],
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
) -> MappingResult:
    """Map village names to clusters through the typed Flash contract."""
    return await _map_bodies(
        clusters,
        village_names,
        prompt_template=_PROMPT_TEMPLATE,
        cache_key_prefix="village-stable-v1",
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
        spatial_evidence=spatial_evidence,
        entity_kind="village",
    )


async def map_water_bodies(
    bodies: List[VillageCluster],
    water_names: List[str],
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
) -> MappingResult:
    """Map report water-body names to landuse-derived water bodies."""
    return await _map_bodies(
        bodies,
        water_names,
        prompt_template=_WATER_PROMPT_TEMPLATE,
        cache_key_prefix="water-stable-v1",
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
        spatial_evidence=spatial_evidence,
        entity_kind="water",
    )


async def _structured_mapping(
    model: Any,
    prompt: str,
    *,
    timeout: Optional[float] = None,
) -> Optional[_GMappingSet]:
    """Call the provider only through the strict typed mapping envelope."""
    try:
        from app.infrastructure.llm.structured import run_structured_output
        response = await run_structured_output(
            _GMappingSet,
            [{"role": "user", "content": prompt}],
            max_retries=0,
            timeout=timeout,
            temperature=0.1,
            max_tokens=1200,
            llm=model,
        )
        if response is None:
            raise ValueError("structured_mapping_empty_response")
        return response if isinstance(response, _GMappingSet) else _GMappingSet.model_validate(response)
    except Exception as exc:
        logger.warning(
            "[village-cluster] structured mapping rejected: %s: %s",
            type(exc).__name__,
            str(exc)[:500],
        )
        return None


def _aggregate_clusters(member_clusters: List[VillageCluster]) -> Dict[str, Any]:
    """Aggregate member clusters into a village-level extent (many-to-one).

    BSMs are the deduplicated union; centroid is parcel-count-weighted.
    Returns stable ``cluster_ids`` / ``bsms`` / ``centroid``.
    """
    member_clusters = sorted(member_clusters, key=lambda c: c.cluster_id)
    cluster_ids = [c.cluster_id for c in member_clusters]
    bsms = list(dict.fromkeys(b for c in member_clusters for b in c.bsms))
    weights = [max(int(c.parcel_count or 0), 1) for c in member_clusters]
    total = sum(weights)
    centroid = (
        sum(c.centroid[0] * w for c, w in zip(member_clusters, weights)) / total,
        sum(c.centroid[1] * w for c, w in zip(member_clusters, weights)) / total,
    )
    return {
        "cluster_ids": cluster_ids,
        "bsms": bsms,
        "centroid": [round(x, 6) for x in centroid],
    }


def _spatial_anchor_prompt(
    entities: list[dict[str, str]],
    bodies: List[VillageCluster],
    spatial_evidence: Optional[Mapping[str, Any]],
) -> tuple[str, Dict[str, set[str]]]:
    """Describe source-backed spatial anchors and derive a hard candidate set.

    ``spatial_evidence`` contains only identity/provenance and related Bundle
    parcel BSMs supplied by EvidenceGraph.  The mapper joins those BSMs to
    deterministic residential bodies; it never receives or parses geometry
    from the model.  An anchor can therefore narrow the LLM's decision, but
    cannot manufacture a new parcel or coordinate.
    """
    if not spatial_evidence:
        return "", {}
    body_bsms = {body.cluster_id: {str(bsm) for bsm in body.bsms} for body in bodies}
    lines: List[str] = []
    allowed: Dict[str, set[str]] = {}
    for entity in entities:
        entity_ref = entity["entity_ref"]
        requested_name = entity["display_name"]
        raw_anchors = spatial_evidence.get(entity_ref)
        if raw_anchors is None:
            raw_anchors = spatial_evidence.get(
                requested_name.removesuffix("自然村").removesuffix("村")
            )
        if not isinstance(raw_anchors, (list, tuple)):
            continue
        hits: Dict[str, int] = {}
        anchor_labels: List[str] = []
        anchor_related_bsms: set[str] = set()
        for raw_anchor in raw_anchors:
            if not isinstance(raw_anchor, Mapping):
                continue
            label = str(raw_anchor.get("canonical_name") or "").strip()
            feature_bsm = str(raw_anchor.get("feature_bsm") or "").strip()
            related_bsms = {
                str(value).strip()
                for value in (raw_anchor.get("related_parcel_bsms") or [])
                if str(value).strip()
            }
            if label:
                anchor_labels.append(label)
            anchor_related_bsms.update(related_bsms)
            for candidate_id, bsms in body_bsms.items():
                overlap = len(related_bsms.intersection(bsms))
                if overlap:
                    hits[candidate_id] = hits.get(candidate_id, 0) + overlap
        if not hits:
            continue
        ordered_hits = sorted(hits.items(), key=lambda item: (-item[1], item[0]))
        allowed[entity_ref] = {candidate_id for candidate_id, _count in ordered_hits}
        labels = "、".join(list(dict.fromkeys(anchor_labels))[:6])
        candidates = "；".join(
            f"{candidate_id}(关联地块交集{count})" for candidate_id, count in ordered_hits
        )
        lines.append(
            f"- {entity_ref}/{requested_name}: Bundle锚点={labels or '未命名空间特征'}，"
            f"锚点关联地块数={len(anchor_related_bsms)}，支持的聚落候选={candidates}。"
            "只能从这些候选中选择；村名列表本身不能证明聚落归属。"
        )
    return "\n".join(lines), allowed


def collect_spatial_anchor_evidence(
    context: Any,
    names: List[str],
    *,
    max_candidates: int = 16,
) -> Dict[str, List[Dict[str, Any]]]:
    """Collect source-backed cross-layer anchors for village mapping.

    This is intentionally a retrieval adapter, not a second index.  It asks
    EvidenceGraph for all bounded candidates matching each name without a
    caller-provided layer.  The returned payload contains Bundle identities,
    related parcel BSMs, KG relation refs and L1 fact refs; authoritative
    geometry remains behind ``bundle://feature/...`` and is never copied into
    the prompt or into the mapper result.
    """
    graph = getattr(context, "evidence_graph", None)
    if graph is None:
        from app.evidence.retrieval.evidence_graph import EvidenceGraph

        graph = EvidenceGraph.build(context)
    result: Dict[str, List[Dict[str, Any]]] = {}
    for name in names:
        normalized = str(name or "").strip()
        if not normalized:
            continue
        candidates = graph.query_scope_candidates(
            normalized,
            entity_scope=[],
            max_candidates=max(1, int(max_candidates or 1)),
        )
        anchors = []
        for candidate in candidates:
            related = [
                str(value).strip()
                for value in (getattr(candidate, "related_parcel_bsms", None) or [])
                if str(value).strip()
            ]
            feature_bsm = str(getattr(candidate, "feature_bsm", "") or "").strip()
            if not related or not feature_bsm:
                continue
            anchors.append({
                "canonical_name": str(getattr(candidate, "canonical_name", "") or ""),
                "role": str(getattr(candidate, "role", "") or ""),
                "feature_bsm": feature_bsm,
                "related_parcel_bsms": list(dict.fromkeys(related)),
                "relation_refs": list(getattr(candidate, "relation_refs", None) or []),
                "l1_fact_refs": list(getattr(candidate, "l1_fact_refs", None) or []),
                "evidence_refs": list(getattr(candidate, "evidence_refs", None) or []),
            })
        if anchors:
            result[normalized] = anchors
    return result


def village_gazetteer_entries(
    mapping: Mapping[str, Mapping[str, Any]],
    clusters: List[VillageCluster],
    *,
    canonical_suffix: str = "村",
    uri_prefix: str = "pln:natural_village:",
    source: str = "village_cluster_map",
    kind_label: str = "自然村",
    member_label: str = "宅基地聚落",
) -> List["GazetteerEntry"]:
    """Turn a many-to-one name->bodies mapping into aggregated gazetteer
    entries (natural villages, water bodies, ...).

    Only ``status=mapped`` decisions are materialized.  Every input decision
    remains available in the caller's ``MappingResult``; unresolved/pending
    entries are never silently converted into a nearby cluster.
    """
    from app.infrastructure.kg.gazetteer import GazetteerEntry

    entries: List[GazetteerEntry] = []
    by_id = {candidate.cluster_id: candidate for candidate in clusters}
    for entity_ref in sorted(mapping):
        item = mapping[entity_ref]
        if item.get("status") != "mapped":
            continue
        candidate_ids = list(item.get("candidate_ids") or [])
        member_clusters = [by_id[candidate_id] for candidate_id in candidate_ids if candidate_id in by_id]
        if not member_clusters or len(member_clusters) != len(candidate_ids):
            continue
        aggregate = _aggregate_clusters(member_clusters)
        bsms = list(aggregate["bsms"])
        if not bsms:
            continue
        raw = str(item.get("display_name") or "").strip()
        if not raw:
            continue
        canonical = f"{raw}{canonical_suffix}" if canonical_suffix and not raw.endswith(canonical_suffix) else raw
        aliases = [raw]
        if raw.endswith(canonical_suffix) and len(raw) > len(canonical_suffix):
            aliases.append(raw[: -len(canonical_suffix)])
        entry = GazetteerEntry(
            name=canonical,
            aliases=aliases,
            entity_uri=f"{uri_prefix}{entity_ref}",
            bsms=bsms,
            centroid=aggregate["centroid"] or None,
            source=source,
            confidence=float(item.get("confidence", 0.0) or 0.0),
            description=(
                f"{kind_label}「{raw}」：依据报告证据「{item.get('evidence', '')}」"
                f"映射 {len(candidate_ids)} 个{member_label}（{candidate_ids}），BSM 并集 {len(bsms)} 个"
            ),
        )
        entry.entity_ref = entity_ref
        entry.village_ref = entity_ref
        entry.candidate_ids = candidate_ids
        entry.cluster_ids = candidate_ids
        entry.candidate_set_digest = getattr(mapping, "candidate_set_digest", "")
        entry.input_digest = getattr(mapping, "input_digest", "")
        entry.schema_digest = getattr(mapping, "schema_digest", "")
        entry.source_span = item.get("source_span")
        entries.append(entry)
    return entries


def water_gazetteer_entries(
    mapping: Dict[str, Dict[str, Any]],
    bodies: List[VillageCluster],
) -> List["GazetteerEntry"]:
    """Aggregated gazetteer entries for LLM-named water bodies."""
    return village_gazetteer_entries(
        mapping,
        bodies,
        canonical_suffix="",
        uri_prefix="pln:water_body:",
        source="water_cluster_map",
        kind_label="水体",
        member_label="水域地块",
    )


async def assign_villages_to_clusters(
    gazetteer: Any,
    parcels: List[Any],
    village_names: List[str],
    report_text: str,
    *,
    context: Any = None,
    llm: Any = None,
    cache: Optional[Path] = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
) -> List["GazetteerEntry"]:
    """LLM-decided many-to-one village assignment -> aggregated gazetteer entries.

    Only villages that are still absent from ``gazetteer`` are considered.
    Clusters are derived deterministically from the 宅基地 parcels.  A village
    is assigned only when the report carries verifiable evidence; the rest stay
    unresolved (fail-closed).  Callers upsert the returned entries.
    """
    clusters = build_village_clusters(parcels)
    if not clusters or not village_names:
        return []
    names: List[str] = []
    for v in village_names:
        base = str(v or "").strip()
        if base.endswith("自然村"):
            base = base[:-3]
        elif base.endswith("村"):
            base = base[:-1]
        base = base.strip()
        if not base:
            continue
        if gazetteer is not None:
            existing = gazetteer.resolve(f"{base}村", fuzzy=False)
            # A name-only entry is semantic evidence, not spatial grounding.
            # Keep it eligible for cluster mapping until it carries BSMs.
            if existing is not None and getattr(existing, "bsms", None):
                continue
        names.append(base)
    if not names:
        return []
    mapping = await map_villages(
        clusters,
        names,
        report_text=report_text,
        spatial_evidence=(
            collect_spatial_anchor_evidence(context, names)
            if context is not None
            else None
        ),
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
    )
    return village_gazetteer_entries(mapping, clusters)


_WATER_MARKERS = ("水域", "河流", "水库", "坑塘", "沟渠", "水利设施")


async def assign_water_bodies(
    gazetteer: Any,
    parcels: List[Any],
    water_names: List[str],
    report_text: str,
    *,
    llm: Any = None,
    cache: Optional[Path] = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
) -> List["GazetteerEntry"]:
    """LLM-decided many-to-one water-name -> landuse water-body assignment.

    Water bodies are derived deterministically from the landuse parcels whose
    DLBM/DLMC marks them as water (水域/河流/水库/坑塘/沟渠/水利设施).  The LLM
    only assigns names to bodies when the report carries verifiable evidence;
    geometry and BSMs always come from the parcels.
    """
    bodies = build_landuse_bodies(parcels, _WATER_MARKERS)
    if not bodies or not water_names:
        return []
    names: List[str] = []
    for n in water_names:
        base = str(n or "").strip()
        if not base:
            continue
        if gazetteer is not None and gazetteer.resolve(base, fuzzy=False) is not None:
            continue
        names.append(base)
    if not names:
        return []
    mapping = await map_water_bodies(
        bodies,
        names,
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
    )
    return water_gazetteer_entries(mapping, bodies)


__all__ = [
    "SourceSpan",
    "MappingResult",
    "VillageCluster",
    "build_landuse_bodies",
    "build_village_clusters",
    "collect_spatial_anchor_evidence",
    "map_villages",
    "map_water_bodies",
    "village_gazetteer_entries",
    "water_gazetteer_entries",
    "assign_villages_to_clusters",
    "assign_water_bodies",
    "assign_names",
    "stable_entity_ref",
]
