"""Unified report -> KG grounding mechanism.

The ONLY inputs are the current-state report and the KG geometry (landuse
parcels with DLBM/DLMC codes, line features, point features).  The KG's
textual information may be minimal or even absent: names always come from the
report, geometry/BSMs always come from the KG.  Every entity role runs the SAME
evidence-first pipeline:

  1. derive candidate spatial objects deterministically from KG geometry
     (blocking): landuse bodies for village/water/area, road lines with
     orientation, facility/landmark points with near-parcel BSMs;
  2. one role-parameterized flash-LLM prompt assigns report names to candidate
     ids, constrained to verbatim report evidence (never order/size guessing);
  3. global consistency (one candidate <= one name) and aggregation into
     gazetteer entries with union BSMs / geometry.

Anything without report evidence stays fail-closed.
"""
from __future__ import annotations

import hashlib
from collections import Counter
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from app.infrastructure.logging import get_logger
from app.spatial.grounding.village_cluster_mapper import (
    SourceSpan,
    VillageCluster,
    assign_names,
    build_landuse_bodies,
    _finalize_cluster_ids,
    _stable_digest,
    stable_entity_ref,
    village_gazetteer_entries,
)

logger = get_logger(__name__)


def _source_feature_identity(feature: Any, geometry: Any) -> str:
    for attr in ("entity_uri", "feature_id", "id", "bsm", "source_id"):
        value = str(getattr(feature, attr, "") or "").strip()
        if value:
            return value
    return _stable_digest({"geometry": geometry, "text": getattr(feature, "text", "")})

_VILLAGE_MARKERS = ("1340", "0702", "宅基地", "村庄建设用地", "农村居民点")
_WATER_MARKERS = ("水域", "河流", "水库", "坑塘", "沟渠", "水利设施")
_AREA_MARKERS = ("建设区", "生态", "农田", "园地", "林地", "草地")


def create_grounding_llm():
    """Flash LLM sized for grounding output (partition JSON + evidence spans).

    The default flash cap (300-500 tokens) is far too small for a collective
    village partition that must list every cluster and a verbatim evidence
    snippet per name; MiniMax reasoning also consumes budget on <think> blocks.
    """
    import os

    if str(os.getenv("GROUND_LLM_ENABLED", "false")).strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        return None
    if any(
        str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}
        for name in ("DISABLE_GROUND_LLM", "DISABLE_GROUND_REPORT_LLM")
    ):
        return None
    try:
        from app.infrastructure.llm.factory import (
            LLMProvider,
            create_llm,
            get_provider,
        )

        model = None
        # MiniMax-M2.7-highspeed supports function_calling structured output.
        # Use the provider's configured model (M2.7-highspeed for MiniMax);
        # other providers keep their default model.
        return create_llm(
            model=model,
            max_tokens=4000,
            temperature=0.1,
        )
    except Exception as exc:  # noqa: BLE001 - grounding degrades to deterministic only
        logger.warning("[report-grounder] grounding LLM unavailable: %s", exc)
        return None


@dataclass(frozen=True)
class RoleSpec:
    role: str
    markers: tuple = ()
    geometry_kind: str = "body"  # body | line | point
    canonical_suffix: str = ""
    uri_prefix: str = "pln:place:"
    source: str = "report_grounded"
    kind_label: str = "地点"
    candidate_label: str = "候选实体"
    intro: str = ""
    point_source: str = ""


_ROLE_SPECS: Dict[str, RoleSpec] = {
    "village": RoleSpec(
        role="village",
        markers=_VILLAGE_MARKERS,
        canonical_suffix="村",
        uri_prefix="pln:natural_village:",
        kind_label="自然村",
        candidate_label="宅基地聚落",
        intro="一个自然村可能由多个聚落组成（多对一），同一聚落只能属于一个自然村。",
    ),
    "water": RoleSpec(
        role="water",
        markers=_WATER_MARKERS,
        uri_prefix="pln:water_body:",
        kind_label="水体",
        candidate_label="水域地块聚合体",
        intro="一个水体可能由多个水域地块组成（多对一），同一组地块只能属于一个水体。",
    ),
    "area": RoleSpec(
        role="area",
        markers=_AREA_MARKERS,
        uri_prefix="pln:area:",
        kind_label="分区",
        candidate_label="用地聚合体",
        intro="一个分区可能由多个地块组成（多对一）。",
    ),
    "road": RoleSpec(
        role="road",
        geometry_kind="line",
        uri_prefix="pln:road:",
        kind_label="道路",
        candidate_label="道路线",
        intro="同一走向/连通的线段可组成一条道路（多对一），同一段线只能属于一条道路。",
    ),
    "facility": RoleSpec(
        role="facility",
        geometry_kind="point",
        uri_prefix="pln:facility:",
        kind_label="设施",
        candidate_label="设施点",
        point_source="annotations_current",
    ),
    "landmark": RoleSpec(
        role="landmark",
        geometry_kind="point",
        uri_prefix="pln:landmark:",
        kind_label="地物",
        candidate_label="地物点",
        point_source="annotations_current",
    ),
}

_PROMPT_TEMPLATE = """你是村庄规划 GIS 证据编译器。只做动态闭集候选选择，不创造地点。
待核对实体闭集：
{villages}

候选闭集（只能引用 candidate_id）：
{clusters}

{intro}
只允许根据报告原文中明确出现的名称、方位、走向或可核对空间关系建立映射。
候选为空或多解时返回 pending 或 unresolved，不能默认选项；禁止按名称顺序、候选顺序、规模或常识猜测。

严格返回 decisions；每个 entity_ref 恰好一次。mapped 必须带 candidate_ids 和报告 source_span，unresolved/pending 不带候选并填写 reason_code。
不要输出解释或思考过程，只输出 JSON。"""


def _flatten(coords: Any) -> List[tuple]:
    flat: List[tuple] = []
    def walk(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (list, tuple)):
            for item in c:
                walk(item)
        elif isinstance(c, (list, tuple)) and len(c) >= 2 and isinstance(c[0], (int, float)):
            flat.append((float(c[0]), float(c[1])))
    walk(coords)
    return flat


def _mean(pts: List[tuple]) -> tuple:
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _approx_length_m(pts: List[tuple]) -> float:
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += math.hypot((b[0] - a[0]) * 102000.0, (b[1] - a[1]) * 111000.0)
    return total


def _candidate_line(c: VillageCluster) -> str:
    feats = dict(getattr(c, "features", {}) or {})
    extra = " ".join(f"{k}={v}" for k, v in feats.items())
    return (
        f"candidate_id={c.cluster_id}: 质心({c.centroid[0]:.5f},{c.centroid[1]:.5f}) "
        f"地块数{c.parcel_count} 面积{c.area_ha:.2f} {extra}".rstrip()
    )


def _line_candidates(lines: List[Any]) -> List[VillageCluster]:
    out: List[VillageCluster] = []
    for i, line in enumerate(lines or []):
        geom = getattr(line, "geometry", None) or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if not coords:
            continue
        flat = _flatten(coords)
        if len(flat) < 2:
            continue
        centroid = _mean(flat)
        dx = flat[-1][0] - flat[0][0]
        dy = flat[-1][1] - flat[0][1]
        ang = math.degrees(math.atan2(abs(dy), abs(dx)))
        if ang < 30:
            direction = "东西"
        elif ang > 60:
            direction = "南北"
        elif dx * dy >= 0:
            direction = "东北-西南"
        else:
            direction = "西北-东南"
        length_m = _approx_length_m(flat)
        c = VillageCluster(
            index=len(out),
            centroid=centroid,
            bsms=[],
            parcel_count=1,
            area_ha=round(length_m / 1000.0, 3),
        )
        c.features = {"走向": direction, "长度m": round(length_m, 0)}
        c.features["source_identity"] = _source_feature_identity(line, coords)
        out.append(c)
    _finalize_cluster_ids(out, "road")
    return out


def _point_candidates(points: List[Any], parcels: List[Any]) -> List[VillageCluster]:
    from app.spatial.grounding.grounding import (
        build_parcel_centroid_cache,
        query_parcels_near_entity,
    )

    cache = build_parcel_centroid_cache(parcels)
    out: List[VillageCluster] = []
    for i, p in enumerate(points or []):
        geom = getattr(p, "geometry", None) or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if not coords or len(coords) < 2:
            continue
        centroid = (float(coords[0]), float(coords[1]))
        bsms = query_parcels_near_entity(
            parcels, centroid, max_distance_m=500, centroid_cache=cache
        )
        text = str(getattr(p, "text", "") or "").strip()
        c = VillageCluster(
            index=len(out),
            centroid=centroid,
            bsms=list(dict.fromkeys(bsms)),
            parcel_count=1,
            area_ha=0.0,
        )
        c.features = {
            "名称": text or "无",
            "类型": str(getattr(p, "category", "") or "").strip() or "点",
            "source_identity": _source_feature_identity(p, coords),
        }
        out.append(c)
    _finalize_cluster_ids(out, "point")
    return out


def derive_candidates(workspace: Any, role: str) -> List[VillageCluster]:
    """Deterministic candidate derivation from KG geometry for one role."""
    spec = _ROLE_SPECS.get(role)
    if spec is None:
        return []
    polygons = (getattr(workspace, "polygons", {}) or {}) if workspace is not None else {}
    parcels = list(polygons.get("landuse_current") or [])
    if spec.geometry_kind == "body":
        return build_landuse_bodies(parcels, spec.markers)
    if spec.geometry_kind == "line":
        lines = (getattr(workspace, "lines", {}) or {}).get("roads_current") or []
        return _line_candidates(list(lines))
    points = (getattr(workspace, "points", {}) or {}).get(
        spec.point_source or "annotations_current"
    ) or []
    return _point_candidates(list(points), parcels)


async def assign_role_names(
    gazetteer: Any,
    workspace: Any,
    names: List[str],
    role: str,
    report_text: str,
    *,
    llm: Any = None,
    cache: Optional[Path] = None,
    budget: Optional[Dict[str, Any]] = None,
    context: Any = None,
) -> List["GazetteerEntry"]:
    """One role-parameterized grounding pass: derive candidates, let the LLM
    assign report names with evidence, aggregate into gazetteer entries."""
    spec = _ROLE_SPECS.get(role)
    if spec is None:
        return []
    candidates = derive_candidates(workspace, role)
    if not candidates or not names:
        return []
    todo: List[str] = []
    for n in names:
        base = str(n or "").strip()
        if not base:
            continue
        key = f"{base}{spec.canonical_suffix}" if spec.canonical_suffix else base
        if gazetteer is not None and gazetteer.resolve(key, fuzzy=False) is not None:
            continue
        todo.append(base)
    if not todo:
        return []
    spatial_evidence = None
    if context is not None:
        from app.spatial.grounding.village_cluster_mapper import (
            collect_spatial_anchor_evidence,
        )

        spatial_evidence = collect_spatial_anchor_evidence(context, todo)
    mapping = await assign_names(
        candidates,
        todo,
        prompt_template=_PROMPT_TEMPLATE,
        cache_key_prefix=f"ground-{role}-v1",
        prompt_kwargs={
            "kind_label": spec.kind_label,
            "intro": spec.intro,
        },
        report_text=report_text,
        cache=cache,
        llm=llm,
        budget=budget,
        spatial_evidence=spatial_evidence,
        entity_kind=role,
    )
    return village_gazetteer_entries(
        mapping,
        candidates,
        canonical_suffix=spec.canonical_suffix,
        uri_prefix=spec.uri_prefix,
        source=spec.source,
        kind_label=spec.kind_label,
        member_label=spec.candidate_label,
    )


async def ground_report_facts(
    gazetteer: Any,
    workspace: Any,
    facts: List[Any],
    report_text: str,
    *,
    llm: Any = None,
    session_id: str = "",
    budget: Optional[Dict[str, Any]] = None,
    context: Any = None,
) -> Dict[str, int]:
    """The complete GROUND flow over typed L1 facts.

    Phase 1: build the spatial inventory from the report (all place names,
    the total natural-village count, per-village direction clues, facility ->
    village text associations, external neighbor POIs).
    Phase 2: ground every role against the dynamic candidate set.  The mapper
    returns an exact batch of stable-ID decisions; only mapped decisions are
    materialized and all other dispositions remain explicit to the caller.

    Returns {role: entries_written} and upserts the entries into
    ``gazetteer`` (callers that keep a ports adapter should refresh it).
    """
    from app.infrastructure.paths import session_run_dir
    if budget is None:
        from app.spatial.grounding.call_budget import new_ground_llm_budget

        budget = new_ground_llm_budget()

    inventory = extract_spatial_inventory(report_text, facts, workspace)
    if llm is None:
        llm = create_grounding_llm()
    counts: Dict[str, int] = {}

    def _cache(role: str) -> Optional[Path]:
        if not session_id:
            return None
        try:
            return session_run_dir(session_id) / f"ground-{role}.json"
        except Exception:
            return None

    # Villages: collective partition covering all report-named villages.
    if inventory.names_by_role.get("village"):
        try:
            entries = await ground_village_partition(
                gazetteer,
                workspace,
                inventory,
                report_text,
                llm=llm,
                cache=_cache("village"),
                budget=budget,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[report-grounder] village partition failed: %s", exc)
            entries = []
        for e in entries:
            gazetteer.upsert(e)
        counts["village"] = len(entries)
        if entries:
            logger.info("[report-grounder] village partition grounded %d villages", len(entries))

    # Every other role through the same per-role assignment.
    for role, names in inventory.names_by_role.items():
        if role == "village" or role not in _ROLE_SPECS:
            continue
        try:
            entries = await assign_role_names(
                gazetteer,
                workspace,
                names,
                role,
                report_text,
                llm=llm,
                cache=_cache(role),
                budget=budget,
                context=context,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[report-grounder] role=%s failed: %s", role, exc)
            entries = []
        for e in entries:
            gazetteer.upsert(e)
        counts[role] = len(entries)
        if entries:
            logger.info("[report-grounder] role=%s grounded %d entities", role, len(entries))
    return counts


@dataclass
class SpatialInventory:
    names_by_role: Dict[str, List[str]] = field(default_factory=dict)
    total_village_count: int = 0
    clues: Dict[str, str] = field(default_factory=dict)
    facility_villages: List[tuple] = field(default_factory=list)
    external_pois: List[tuple] = field(default_factory=list)


def extract_spatial_inventory(
    report_text: str,
    facts: List[Any],
    workspace: Any = None,
) -> SpatialInventory:
    """Phase 1: exhaustively list every place name + spatial cue the report
    mentions: typed names, the total natural-village count, per-village
    direction clues, facility/road/water -> village associations, and external
    neighbor POIs.  Names come only from the report; geometry comes later."""
    inv = SpatialInventory()
    village_bases: List[str] = []
    for fact in facts or []:
        role = str(getattr(fact, "role", "") or "").strip().lower()
        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        if not name:
            continue
        inv.names_by_role.setdefault(role, []).append(name)
        if role == "village":
            base = name.removesuffix("村").removesuffix("自然村").strip()
            if base:
                village_bases.append(base)
    for role in inv.names_by_role:
        inv.names_by_role[role] = list(dict.fromkeys(inv.names_by_role[role]))
    village_bases = list(dict.fromkeys(village_bases))

    # Report prose is not parsed for spatial identity or counts.  If a
    # natural-village count is needed, the typed LLM meta contract supplies it;
    # otherwise the explicitly extracted typed names define the query set.
    inv.total_village_count = 0

    # facility/road/water/landmark -> village associations from the fact's
    # source span (e.g. ``现状设施 | 祠堂 | 社前村 | 三座祠堂``).
    for fact in facts or []:
        role = str(getattr(fact, "role", "") or "").strip().lower()
        if role == "village":
            continue
        name = str(getattr(fact, "normalized_name", "") or "").strip()
        if not name:
            continue
        references = [
            str(getattr(fact, "spatial_hint", "") or "").strip(),
            *[
                str(value or "").strip()
                for value in (getattr(fact, "related_mentions", None) or [])
            ],
        ]
        for reference in references:
            base = reference.removesuffix("村").removesuffix("自然村").strip()
            if base in village_bases:
                inv.facility_villages.append((name, base))
    inv.facility_villages = list(dict.fromkeys(inv.facility_villages))

    # A spatial hint carried by a typed village fact is safe context for the
    # LLM prompt; it is not interpreted here into a geometry assignment.
    for fact in facts or []:
        if str(getattr(fact, "role", "") or "").strip().lower() != "village":
            continue
        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        hint = str(getattr(fact, "spatial_hint", "") or "").strip()
        if name and hint and hint != name:
            inv.clues[name.removesuffix("村").removesuffix("自然村").strip()] = hint

    if workspace is not None:
        for p in list((getattr(workspace, "points", {}) or {}).get("annotations_current") or []):
            cat = str(getattr(p, "category", "") or "")
            if cat != "村名":
                continue
            geom = getattr(p, "geometry", None) or {}
            coords = geom.get("coordinates") if isinstance(geom, dict) else None
            if coords and len(coords) >= 2:
                inv.external_pois.append(
                    (str(getattr(p, "text", "") or ""), float(coords[0]), float(coords[1]))
                )
    return inv


_PARTITION_PROMPT = """这是自然村闭集映射任务。
只引用输入 entity_ref 和候选 candidate_id；自然村可以明确引用多个候选聚落，但不能把不确定的候选当作确定结果。
每个 entity_ref 必须返回一次；没有足够报告 source_span 或存在候选归属冲突时返回 pending。"""


def _centroid_dist(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def deterministic_village_partition(
    inventory: SpatialInventory,
    workspace: Any,
    clusters: List[VillageCluster],
) -> Dict[str, Dict[str, Any]]:
    """Return only explicitly anchored village clusters.

    A village-name point from the source bundle is a typed external spatial
    anchor. It may bind the nearest residential body, but an unanchored body
    is never assigned by distance, order, count coverage, or a guessed name.
    All other village mappings must come from the typed LLM/EvidenceGraph
    path; missing evidence stays unresolved.
    """
    mapping: Dict[str, Dict[str, Any]] = {}

    def _add(village: str, cluster_id: str, evidence: str) -> None:
        entity_ref = stable_entity_ref("village", village)
        item = mapping.setdefault(
            entity_ref,
            {
                "entity_ref": entity_ref,
                "display_name": village,
                "status": "pending",
                "candidate_ids": [],
                "reason_code": "external_anchor_requires_report_span",
                "evidence": evidence,
                "recommended_candidate_ids": [],
            },
        )
        if cluster_id not in item["recommended_candidate_ids"]:
            item["recommended_candidate_ids"].append(cluster_id)

    report_bases = [
        (v.removesuffix("村").removesuffix("自然村").strip() or v)
        for v in inventory.names_by_role.get("village", [])
    ]
    report_bases = list(dict.fromkeys(report_bases))
    if not clusters:
        return mapping

    # 0) external-source authoritative coordinates (Tianditu / Tencent / AMap
    #    村名 annotations): a report village whose name matches an external POI
    #    is anchored to the residential cluster nearest that authoritative
    #    point - the strongest spatial evidence available.
    for ext_name, lon, lat in inventory.external_pois:
        ext_base = str(ext_name or "").removesuffix("村").removesuffix("自然村").strip()
        if not ext_base or lon is None or lat is None:
            continue
        for base in report_bases:
            if base == ext_base:
                ranked = sorted(
                    (
                        _centroid_dist(cluster.centroid, (lon, lat)),
                        cluster.cluster_id,
                        cluster,
                    )
                    for cluster in clusters
                )
                if len(ranked) > 1 and math.isclose(ranked[0][0], ranked[1][0], rel_tol=0.0, abs_tol=1e-12):
                    _add(base, "", f"外源POI:{ext_name}:ambiguous")
                else:
                    _add(base, ranked[0][2].cluster_id, f"外源POI:{ext_name}")
                break
    return mapping


def mapping_village_centroid(
    mapping: Dict[str, Dict[str, Any]],
    village: str,
    clusters: List[VillageCluster],
) -> tuple:
    entity_ref = stable_entity_ref("village", village)
    ids = mapping.get(entity_ref, {}).get("recommended_candidate_ids", []) or []
    pts = [c.centroid for c in clusters if c.cluster_id in ids]
    if not pts:
        return (0.0, 0.0)
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


async def ground_village_partition(
    gazetteer: Any,
    workspace: Any,
    inventory: SpatialInventory,
    report_text: str,
    *,
    llm: Any = None,
    cache: Optional[Path] = None,
    budget: Optional[Dict[str, Any]] = None,
    context: Any = None,
) -> List["GazetteerEntry"]:
    """Collective natural-village grounding over evidence-backed clusters.

    The typed LLM assigns only stable candidate IDs supported by report spans
    and optional cross-source spatial anchors. Omitted, duplicate, and unknown
    decisions remain unresolved/pending and are never materialized.
    """
    from app.spatial.grounding.village_cluster_mapper import (
        assign_names,
        build_village_clusters,
        village_gazetteer_entries,
    )

    parcels = list((getattr(workspace, "polygons", {}) or {}).get("landuse_current") or [])
    clusters = build_village_clusters(parcels)
    villages = list(dict.fromkeys(inventory.names_by_role.get("village", [])))
    bases = [
        (v.removesuffix("村").removesuffix("自然村").strip() or v)
        for v in villages
    ]
    bases = list(dict.fromkeys(bases))
    todo = [
        b
        for b in bases
        if gazetteer is None or gazetteer.resolve(f"{b}村", fuzzy=False) is None
    ]
    if not clusters or not todo:
        return []

    spatial_evidence = None
    if context is not None:
        from app.spatial.grounding.village_cluster_mapper import (
            collect_spatial_anchor_evidence,
        )

        spatial_evidence = collect_spatial_anchor_evidence(context, todo)

    mapping = await assign_names(
        clusters,
        todo,
        prompt_template=_PARTITION_PROMPT,
        cache_key_prefix="village-partition-stable-v1",
        report_text=report_text,
        cache=cache,
        llm=llm,
        budget=budget,
        spatial_evidence=spatial_evidence,
        entity_kind="village",
    )

    return village_gazetteer_entries(
        mapping,
        clusters,
        canonical_suffix="村",
        uri_prefix="pln:natural_village:",
        source="village_partition",
        kind_label="自然村",
        member_label="宅基地聚落",
    )


@dataclass
class LocationReviewItem:
    """A low-confidence location that needs a human decision.

    It may carry no geometry at all.  A human can only override the location
    with explicit BSMs; unresolved evidence is never converted into a nearby
    parcel suggestion.
    """
    name: str
    role: str
    entity_ref: str = ""
    source_span: Optional[Dict[str, Any]] = None
    recommended_bsms: List[str] = field(default_factory=list)
    recommended_geometry_ref: str = ""
    confidence: float = 0.0
    reason: str = ""
    status: str = "pending"  # pending | confirmed | rejected | overridden


class HumanReviewQueue:
    """In-memory per-session queue of low-confidence locations for human
    confirmation.  An item without recommended BSMs records an evidence gap;
    it is not a geometric recommendation."""

    def __init__(self) -> None:
        self._items: Dict[str, List[LocationReviewItem]] = {}

    def add(self, session_id: str, item: LocationReviewItem) -> None:
        self._items.setdefault(str(session_id or "default"), []).append(item)

    def pending(self, session_id: str) -> List[LocationReviewItem]:
        return list(self._items.get(str(session_id or "default"), []))

    def decide(self, session_id: str, name: str, role: str, *, accept: bool = True,
               override_bsms: Optional[List[str]] = None,
               entity_ref: str = "") -> Optional[LocationReviewItem]:
        """Human decision on one pending item: accept the LLM recommendation
        or override it with explicit BSMs (the only place a human can pin
        coordinates)."""
        items = self._items.get(str(session_id or "default"), [])
        for item in items:
            if (
                item.name == name
                and item.role == role
                and (not entity_ref or item.entity_ref == entity_ref)
                and item.status == "pending"
            ):
                item.status = "confirmed" if accept else "overridden"
                if override_bsms:
                    item.recommended_bsms = list(override_bsms)
                    item.status = "overridden"
                return item
        return None


@dataclass
class GroundedEntity:
    """One report-named entity and where GROUND located it."""
    name: str
    role: str
    status: str  # grounded | unresolved | pending
    entity_ref: str = ""
    candidate_ids: List[str] = field(default_factory=list)
    source_span: Optional[Dict[str, Any]] = None
    reason: str = ""
    bsms: List[str] = field(default_factory=list)
    geometry_ref: str = ""
    entity_uri: str = ""
    evidence: str = ""
    source: str = ""


def _fact_entity_ref(fact: Any, role: str, name: str) -> str:
    for attr in ("entity_ref", "village_ref", "entity_id", "fact_id"):
        value = str(getattr(fact, attr, "") or "").strip()
        if value:
            return value
    return stable_entity_ref(role or "entity", name)


def _fact_source_span(fact: Any, report_text: str, name: str) -> Optional[Dict[str, Any]]:
    candidates = [
        str(getattr(fact, "mention", "") or "").strip(),
        str(getattr(fact, "normalized_name", "") or "").strip(),
        name.removesuffix("自然村").removesuffix("村").strip(),
    ]
    raw_source_span = getattr(fact, "source_span", None)
    if isinstance(raw_source_span, Mapping):
        try:
            span = SourceSpan.model_validate(raw_source_span)
            if _span_matches_report(span, report_text, name):
                return span.model_dump(mode="json")
        except Exception:
            pass
    source_text = str(raw_source_span or "").strip()
    if source_text and name in source_text:
        candidates.insert(0, source_text)
    for needle in candidates:
        if not needle:
            continue
        start = report_text.find(needle)
        if start < 0:
            continue
        end = start + len(needle)
        quote = report_text[start:end]
        return SourceSpan(
            segment_id="report",
            start=start,
            end=end,
            quote_hash=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        ).model_dump(mode="json")
    return None


def _span_matches_report(span: SourceSpan, report_text: str, name: str) -> bool:
    if span.segment_id != "report" or span.start < 0 or span.end > len(report_text):
        return False
    quote = report_text[span.start:span.end]
    return (
        span.end > span.start
        and hashlib.sha256(quote.encode("utf-8")).hexdigest() == span.quote_hash
        and (name in quote or name.removesuffix("村") in quote)
    )


def _candidate_entity_ref(candidate: Any) -> str:
    for attr in ("entity_ref", "entity_uri", "candidate_id", "feature_id"):
        value = str(getattr(candidate, attr, "") or "").strip()
        if value:
            return value
    return ""


@dataclass
class GroundReportResult:
    entities: List[GroundedEntity] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    unresolved: List[str] = field(default_factory=list)
    pending: List[str] = field(default_factory=list)
    unresolved_refs: List[str] = field(default_factory=list)
    pending_refs: List[str] = field(default_factory=list)
    reviews: List[LocationReviewItem] = field(default_factory=list)
    queue: Any = None

    @property
    def grounded(self) -> int:
        return sum(1 for e in self.entities if e.status == "grounded")

    @property
    def total(self) -> int:
        return len(self.entities)

    @property
    def rate(self) -> float:
        return self.grounded / self.total if self.total else 0.0

    def summary(self) -> str:
        return (
            f"grounded={self.grounded}/{self.total} ({self.rate:.1%}) "
            f"by_role={self.counts} unresolved={self.unresolved[:8]} "
            f"pending={self.pending[:8]}"
        )


async def ground_report(
    context: Any,
    facts: List[Any],
    report_text: str,
    *,
    llm: Any = None,
    session_id: str = "",
    budget: Optional[Dict[str, Any]] = None,
) -> GroundReportResult:
    """The complete GROUND flow over a ``PlanningContext`` + typed L1 facts.

    Phase 1: spatial inventory from the report.  Phase 2: collective village
    partition + per-role LLM evidence assignment, upserted into the context
    gazetteer.  Then the EvidenceGraph is rebuilt and every fact is audited
    through it - status is ``grounded`` only when the entity actually resolves
    to a spatial extent/geometry; everything else is explicitly unresolved.
    """
    gazetteer = getattr(context, "gazetteer", None)
    workspace = getattr(context, "workspace", None)
    counts = await ground_report_facts(
        gazetteer,
        workspace,
        facts,
        report_text,
        llm=llm,
        session_id=session_id,
        budget=budget,
        context=context,
    )
    try:
        context.location_facts = list(facts or [])
        from app.evidence.retrieval.evidence_graph import EvidenceGraph

        context.evidence_graph = EvidenceGraph.build(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[report-grounder] evidence graph rebuild failed: %s", exc)

    graph = getattr(context, "evidence_graph", None)
    queue = HumanReviewQueue()
    entities: List[GroundedEntity] = []
    refs = [
        _fact_entity_ref(
            fact,
            str(getattr(fact, "role", "") or "").strip().lower(),
            str(
                getattr(fact, "normalized_name", "")
                or getattr(fact, "mention", "")
                or ""
            ).strip(),
        )
        for fact in facts or []
    ]
    ref_counts = Counter(refs)
    for fact in facts or []:
        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        role = str(getattr(fact, "role", "") or "").strip().lower()
        entity_ref = _fact_entity_ref(fact, role, name)
        source_span = _fact_source_span(fact, report_text, name) if name else None
        status = "grounded"
        reason = ""
        candidate = None
        candidate_ids: List[str] = []
        if not name:
            status, reason = "pending", "input_entity_name_missing"
        elif ref_counts[entity_ref] > 1:
            status, reason = "pending", "duplicate_input_entity_ref"
        elif source_span is None:
            status, reason = "pending", "source_span_missing_or_invalid"
        elif graph is None:
            status, reason = "pending", "evidence_graph_unavailable"
        else:
            try:
                resolution = graph.resolve_mention(name, role=role)
                candidates = list(getattr(resolution, "candidates", None) or [])
                if getattr(resolution, "status", "") != "resolved" or not candidates:
                    status, reason = "unresolved", "evidence_graph_no_candidate"
                elif len(candidates) != 1:
                    status, reason = "pending", "ambiguous_candidate_set"
                else:
                    candidate = candidates[0]
                    candidate_ref = _candidate_entity_ref(candidate)
                    if not candidate_ref:
                        status, reason = "pending", "candidate_identity_missing"
                    elif not (
                        getattr(candidate, "source_bsms", None)
                        or getattr(candidate, "geometry_ref", None)
                    ):
                        status, reason = "unresolved", "candidate_has_no_spatial_extent"
                    else:
                        candidate_ids = [candidate_ref]
            except Exception:
                status, reason = "pending", "evidence_graph_resolution_failed"
        if status == "grounded" and candidate is not None:
            entities.append(GroundedEntity(
                name=name,
                role=role,
                status=status,
                entity_ref=entity_ref,
                candidate_ids=candidate_ids,
                source_span=source_span,
                bsms=list(getattr(candidate, "source_bsms", None) or []),
                geometry_ref=str(getattr(candidate, "geometry_ref", "") or ""),
                entity_uri=_candidate_entity_ref(candidate),
                source="evidence_graph",
            ))
        else:
            entities.append(GroundedEntity(
                name=name,
                role=role,
                status=status,
                entity_ref=entity_ref,
                candidate_ids=[],
                source_span=source_span,
                reason=reason,
            ))
            queue.add(
                session_id,
                LocationReviewItem(
                    name=name,
                    role=role,
                    entity_ref=entity_ref,
                    source_span=source_span,
                    reason=reason,
                ),
            )
    result = GroundReportResult(
        entities=entities,
        counts=counts,
        unresolved=[e.name for e in entities if e.status == "unresolved"],
        pending=[e.name for e in entities if e.status == "pending"],
        unresolved_refs=[e.entity_ref for e in entities if e.status == "unresolved"],
        pending_refs=[e.entity_ref for e in entities if e.status == "pending"],
        reviews=queue.pending(session_id),
        queue=queue,
    )
    logger.info("[report-grounder] %s reviews=%d", result.summary(), len(result.reviews))
    return result


__all__ = [
    "RoleSpec",
    "SpatialInventory",
    "GroundedEntity",
    "GroundReportResult",
    "LocationReviewItem",
    "HumanReviewQueue",
    "derive_candidates",
    "assign_role_names",
    "ground_village_partition",
    "extract_spatial_inventory",
    "ground_report_facts",
    "ground_report",
    "create_grounding_llm",
    "_ROLE_SPECS",
]
