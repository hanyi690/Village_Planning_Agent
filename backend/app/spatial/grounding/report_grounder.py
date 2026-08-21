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
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger
from app.spatial.grounding.village_cluster_mapper import (
    VillageCluster,
    assign_names,
    build_landuse_bodies,
    village_gazetteer_entries,
)

logger = get_logger(__name__)

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

_PROMPT_TEMPLATE = """你是村庄规划 GIS 证据编译器。待核对的{kind_label}名称：{villages}。
系统中有 {m} 个候选{kind_label}（编号 0..{max_index}），每个候选的几何特征：
{clusters}

{intro}
只允许根据报告摘录中明确出现的名称、方位、走向或可核对空间关系建立映射。
禁止按名称顺序、规模顺序、常识或猜测分配。证据不足的名称必须省略。

对每个名称给出：candidate_indexes（候选编号列表，可多个）和 evidence（必须是报告摘录中可以逐字找到的短句）。
不要输出解释或思考过程，只输出结果。"""


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
        f"{c.index}: 质心({c.centroid[0]:.5f},{c.centroid[1]:.5f}) "
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
        out.append(c)
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
        }
        out.append(c)
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
    todo = list(dict.fromkeys(todo))
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
    Phase 2: ground every role against KG geometry - villages through a
    collective many-to-one partition that covers ALL report-named villages
    (respecting the total count), every other role through the same
    evidence-constrained LLM assignment.

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


async def _infer_village_meta(
    report_text: str,
    village_names: List[str],
    llm: Any = None,
    cache: Optional[Path] = None,
    budget: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """LLM 从现状报告推导村庄元信息：自然村总数 + 每村方位/分布线索。

    Returns ``{"total_count": int, "clues": {村名: 方位描述}}``.  The LLM only
    produces text semantics (count + position wording); geometry still comes
    from the KG/bundle.  If the typed call is unavailable or invalid, the
    result is empty and the caller keeps the unresolved diagnostic.
    """
    empty = {"total_count": 0, "clues": {}}
    if llm is None or not (report_text or "").strip() or not village_names:
        logger.warning("[report-grounder] typed village meta evidence unavailable")
        return empty
    cache_key = hashlib.sha256(
        f"village-meta|{report_text[:4000]}|{','.join(village_names)}".encode("utf-8")
    ).hexdigest()
    if cache is not None and cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if raw.get("key") == cache_key:
                return raw.get("value") or empty
        except Exception:
            pass
    try:
        from pydantic import BaseModel as _BM, Field as _Field

        class _Pos(_BM):
            name: str = ""
            position: str = ""

        class _Meta(_BM):
            total_count: int = _Field(default=0, ge=0, le=200)
            positions: list[_Pos] = _Field(default_factory=list)

        prompt = (
            "你是村庄规划 GIS 证据编译器。下面是某行政村的现状报告摘录与报告提到的自然村名。"
            "请提取：1) 本村共有多少个自然村（total_count，仅接受报告明确给出的数字，"
            "没有明确数字时填 0，不要估算）；"
            "2) 每个自然村的方位/分布线索（positions，如「园寨位于村中部」「田坑在村东南部」），"
            "只写报告中可找到依据的方位描述，没有就留空字符串。\n"
            f"自然村名：{('、'.join(village_names))[:500]}\n"
            f"报告摘录：\n{(report_text or '')[:6000]}"
        )
        import asyncio

        from app.infrastructure.llm.structured import run_structured_output
        from app.spatial.grounding.call_budget import (
            reserve_ground_llm_call,
            run_ground_llm_call,
        )

        structured_timeout = reserve_ground_llm_call(budget)
        if structured_timeout is None:
            logger.warning("[report-grounder] village meta call budget unavailable")
            return empty
        async def _invoke_structured():
            return await run_structured_output(
                _Meta,
                [{"role": "user", "content": prompt}],
                max_retries=1,
                timeout=structured_timeout,
                temperature=0.1,
                max_tokens=600,
                llm=llm,
                allow_content_json_fallback=False,
            )

        response = await run_ground_llm_call(
            budget, structured_timeout, _invoke_structured
        )
        meta = response.model_dump()
        total = int(meta.get("total_count") or 0)
        clues: Dict[str, str] = {}
        for pos in meta.get("positions") or []:
            name = str(pos.get("name") or "").strip()
            position = str(pos.get("position") or "").strip()
            if name and position:
                clues[name] = position
        if total > 0 or clues:
            value = {"total_count": total, "clues": clues}
            if cache is not None:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cache.with_suffix(".tmp")
                    tmp.write_text(
                        json.dumps({"key": cache_key, "value": value}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    tmp.replace(cache)
                except Exception:
                    pass
            return value
    except Exception as exc:  # noqa: BLE001 - typed failure is explicit
        logger.warning("[report-grounder] village meta LLM inference failed: %s", exc)
    return empty


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


_PARTITION_PROMPT = """你是村庄规划 GIS 证据编译器。待核对的自然村名称：{{villages}}。
系统中有 {{m}} 个宅基地聚落（编号 0..{{max_index}}），每个聚落有质心坐标与规模：
{{clusters}}

任务：只为有明确证据和跨源空间锚点支持的自然村选择 {{m}} 个候选聚落中的一个或多个。每个聚落最多属于一个自然村。
允许依据（按优先级）：
1. 报告推导的每村方位/分布线索：{clues}；
2. 报告摘录中明确出现的方位/相对位置（如「园寨位于村中部」）；
3. 已知设施/项目所在村（文本证据）：{assocs}；
4. 邻村注记 POI（外源）相对方位：{pois}；
5. 报告原文逐字证据。
禁止按名称顺序、规模顺序或常识猜测。

输出有明确报告证据和跨源空间锚点支持的自然村 candidate_indexes（候选编号列表）和 evidence。
evidence 必须是报告摘录中可逐字找到的短句；没有明确证据的名称必须省略。
不要输出解释或思考过程；不要求覆盖全部名称或聚落，禁止用空间就近、名称顺序、数量或常识补齐。"""


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

    def _add(village: str, idx: int, evidence: str) -> None:
        item = mapping.setdefault(village, {"cluster_indexes": [], "evidence": evidence})
        if idx not in item["cluster_indexes"]:
            item["cluster_indexes"].append(idx)

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
                best = min(clusters, key=lambda cl: _centroid_dist(cl.centroid, (lon, lat)))
                _add(base, best.index, f"外源POI:{ext_name}")
                break

    # Aggregate each explicitly anchored village's BSM union + weighted
    # centroid. Unanchored clusters remain outside the mapping.
    from app.spatial.grounding.village_cluster_mapper import _aggregate_clusters

    for village, item in mapping.items():
        member = [c for c in clusters if c.index in (item.get("cluster_indexes") or [])]
        if not member:
            continue
        item.update(_aggregate_clusters(member))
    return mapping


def mapping_village_centroid(
    mapping: Dict[str, Dict[str, Any]],
    village: str,
    clusters: List[VillageCluster],
) -> tuple:
    idxs = mapping.get(village, {}).get("cluster_indexes", []) or []
    pts = [c.centroid for c in clusters if c.index in idxs]
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

    The typed LLM assigns only candidates supported by verbatim report
    evidence and cross-source spatial anchors. A partial response is valid;
    omitted names and clusters remain unresolved. Geometry/BSMs always come
    from Bundle clusters; the LLM never emits coordinates.
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

    # LLM-driven village meta: natural-village count + per-village position
    # clues derived from the report.
    meta = await _infer_village_meta(report_text, bases, llm, cache, budget)
    n = int(meta.get("total_count") or 0) or inventory.total_village_count or len(todo)
    clues = dict(inventory.clues)
    clues.update(meta.get("clues") or {})

    # Deterministic baseline is limited to explicit external village-name
    # point anchors.  It must never allocate an unanchored cluster by nearest
    # distance or by report order.
    mapping = deterministic_village_partition(inventory, workspace, clusters)

    spatial_evidence = None
    if context is not None:
        from app.spatial.grounding.village_cluster_mapper import (
            collect_spatial_anchor_evidence,
        )

        spatial_evidence = collect_spatial_anchor_evidence(context, todo)

    # LLM-driven closed-set partition.  A partial typed result is accepted
    # only for names backed by verbatim report evidence and spatial anchors;
    # every omitted name remains unresolved.
    if llm is not None:
        try:
            cluster_lines = "\n".join(_candidate_line(c) for c in clusters)
            assocs = "；".join(f"{f}@{v}" for f, v in inventory.facility_villages[:24]) or "无"
            pois = "；".join(
                f"{nm}({lon:.4f},{lat:.4f})"
                for nm, lon, lat in inventory.external_pois[:10]
            ) or "无"
            clue_lines = "；".join(f"{v}：{c}" for v, c in clues.items()) or "无"
            llm_mapping = await assign_names(
                clusters,
                todo,
                # Keep this template unrendered until the shared mapper adds
                # the candidate list.  Rendering it here would turn escaped
                # JSON braces into active format braces, and the second
                # rendering in _map_bodies would fail with ``Single '}'``.
                prompt_template=_PARTITION_PROMPT,
                cache_key_prefix="village-partition-v4",
                prompt_kwargs={
                    "n": n,
                    "clues": clue_lines,
                    "assocs": assocs,
                    "pois": pois,
                },
                require_evidence=True,
                report_text=report_text,
                cache=cache,
                llm=llm,
                budget=budget,
                spatial_evidence=spatial_evidence,
            )
            if llm_mapping:
                merged = dict(llm_mapping)
                for v, item in mapping.items():
                    if v not in merged:
                        merged[v] = item
                mapping = merged
        except Exception as exc:  # noqa: BLE001 - deterministic path always safe
            logger.warning("[report-grounder] LLM village partition failed: %s", exc)

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
               override_bsms: Optional[List[str]] = None) -> Optional[LocationReviewItem]:
        """Human decision on one pending item: accept the LLM recommendation
        or override it with explicit BSMs (the only place a human can pin
        coordinates)."""
        items = self._items.get(str(session_id or "default"), [])
        for item in items:
            if item.name == name and item.role == role and item.status == "pending":
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
    status: str  # grounded | unresolved
    bsms: List[str] = field(default_factory=list)
    geometry_ref: str = ""
    entity_uri: str = ""
    evidence: str = ""
    source: str = ""


@dataclass
class GroundReportResult:
    entities: List[GroundedEntity] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    unresolved: List[str] = field(default_factory=list)
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
            f"by_role={self.counts} unresolved={self.unresolved[:8]}"
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
    seen = set()
    for fact in facts or []:
        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        role = str(getattr(fact, "role", "") or "").strip().lower()
        if not name or (name, role) in seen:
            continue
        seen.add((name, role))
        candidate = None
        if graph is not None:
            try:
                res = graph.resolve_mention(name, role=role)
                if res.status == "resolved" and res.candidates:
                    candidate = res.candidates[0]
            except Exception:
                candidate = None
        if candidate is not None and (
            getattr(candidate, "source_bsms", None)
            or getattr(candidate, "geometry_ref", None)
        ):
            entities.append(GroundedEntity(
                name=name,
                role=role,
                status="grounded",
                bsms=list(getattr(candidate, "source_bsms", None) or []),
                geometry_ref=str(getattr(candidate, "geometry_ref", "") or ""),
                entity_uri=str(getattr(candidate, "entity_ref", "") or ""),
                source="evidence_graph",
            ))
        else:
            entities.append(GroundedEntity(name=name, role=role, status="unresolved"))
            queue.add(
                session_id,
                LocationReviewItem(
                    name=name,
                    role=role,
                    reason="EvidenceGraph 未解析出可验证空间范围；未生成候选几何，需要补充 L1/KG/bundle evidence",
                ),
            )
    result = GroundReportResult(
        entities=entities,
        counts=counts,
        unresolved=[e.name for e in entities if e.status == "unresolved"],
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
