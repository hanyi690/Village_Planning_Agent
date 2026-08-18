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


_VILLAGE_COUNT_RE = None  # compiled lazily
_DIRECTION_PAT = None


def _first_village_count(report_text: str) -> int:
    global _VILLAGE_COUNT_RE
    import re

    if _VILLAGE_COUNT_RE is None:
        _VILLAGE_COUNT_RE = re.compile(r"(\d+)\s*个自然村")
    m = _VILLAGE_COUNT_RE.search(report_text or "")
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return 0
    return 0


def _village_clue(report_text: str, base: str) -> str:
    global _DIRECTION_PAT
    import re

    if _DIRECTION_PAT is None:
        _DIRECTION_PAT = re.compile(
            r"(东南|西南|东北|西北|中部|东部|西部|南部|北部|东侧|西侧|南侧|北侧|东|南|西|北)"
        )
    for m in re.finditer(re.escape(base), report_text or ""):
        window = (report_text[max(0, m.start() - 45): m.end() + 45]).replace("\n", " ")
        if _DIRECTION_PAT.search(window):
            return window[:90]
    return ""


def _infer_village_meta_fallback(
    report_text: str,
    village_names: List[str],
) -> Dict[str, Any]:
    """Deterministic fallback for village meta: regex count + per-village
    direction-clue window.  Never the primary source; used only when the LLM
    is unavailable or fails."""
    return {
        "total_count": _first_village_count(report_text),
        "clues": {
            base: clue
            for base in village_names
            if (clue := _village_clue(report_text, base))
        },
    }


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
    from the KG/bundle.  Falls back to the deterministic regex baseline when
    the model is unavailable or returns nothing usable, so this never blocks
    grounding.
    """
    fallback = _infer_village_meta_fallback(report_text, village_names)
    if llm is None or not (report_text or "").strip() or not village_names:
        return fallback
    cache_key = hashlib.sha256(
        f"village-meta|{report_text[:4000]}|{','.join(village_names)}".encode("utf-8")
    ).hexdigest()
    if cache is not None and cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if raw.get("key") == cache_key:
                return raw.get("value") or fallback
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
            "请推导：1) 本村共有多少个自然村（total_count，依据报告表述如“全村共有12个自然村”，"
            "无明确数字时按报告实际出现的自然村名数量估算）；"
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
            return fallback
        try:
            async def _invoke_structured():
                return await run_structured_output(
                    _Meta,
                    [{"role": "user", "content": prompt}],
                    max_retries=1,
                    timeout=structured_timeout,
                    temperature=0.1,
                    max_tokens=600,
                    llm=llm,
                )

            response = await run_ground_llm_call(
                budget, structured_timeout, _invoke_structured
            )
            meta = response.model_dump()
        except Exception:
            text_timeout = reserve_ground_llm_call(budget)
            if text_timeout is None:
                return fallback
            async def _invoke_text():
                return await llm.ainvoke(prompt)

            raw = await run_ground_llm_call(budget, text_timeout, _invoke_text)
            content = getattr(raw, "content", "") or ""
            if isinstance(content, list):
                content = "".join(content)
            meta = _parse_village_meta_json(str(content or ""))
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
    except Exception as exc:  # noqa: BLE001 - fallback is always safe
        logger.warning("[report-grounder] village meta LLM inference failed: %s", exc)
    return fallback


def _parse_village_meta_json(raw: str) -> Dict[str, Any]:
    """Parse the text-protocol village-meta JSON (think-stripped)."""
    import re as _re

    text = _re.sub(r"<think>.*?</think>", "", raw or "", flags=_re.I | _re.S)
    text = _re.sub(r"<think>.*$", "", text, flags=_re.I | _re.S)
    match = _re.search("\\{.*\\}", text, _re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


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

    inv.total_village_count = _first_village_count(report_text)

    # facility/road/water/landmark -> village associations from the fact's
    # source span (e.g. ``现状设施 | 祠堂 | 社前村 | 三座祠堂``).
    for fact in facts or []:
        role = str(getattr(fact, "role", "") or "").strip().lower()
        if role == "village":
            continue
        name = str(getattr(fact, "normalized_name", "") or "").strip()
        if not name:
            continue
        span = " ".join(
            str(x)
            for x in (
                getattr(fact, "source_span", "") or "",
                getattr(fact, "spatial_hint", "") or "",
            )
            if x
        )
        for vb in village_bases:
            if vb in span:
                inv.facility_villages.append((name, vb))
    inv.facility_villages = list(dict.fromkeys(inv.facility_villages))

    for vb in village_bases:
        clue = _village_clue(report_text, vb)
        if clue:
            inv.clues[vb] = clue

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


_PARTITION_PROMPT = """你是村庄规划 GIS 证据编译器。本村共有 {n} 个自然村：{{villages}}。
系统中有 {{m}} 个宅基地聚落（编号 0..{{max_index}}），每个聚落有质心坐标与规模：
{{clusters}}

任务：把全部 {{m}} 个聚落分配到 {n} 个自然村（多对一）。每个聚落只能属于一个自然村，每个自然村至少分配一个聚落。
允许依据（按优先级）：
1. 报告推导的每村方位/分布线索：{clues}；
2. 报告摘录中明确出现的方位/相对位置（如「园寨位于村中部」）；
3. 已知设施/项目所在村（文本证据）：{assocs}；
4. 邻村注记 POI（外源）相对方位：{pois}；
5. 报告原文逐字证据。
禁止按名称顺序、规模顺序或常识猜测。

输出每个自然村对应的 candidate_indexes（候选编号列表）和 evidence。
evidence 尽量填报告摘录中可逐字找到的短句；无明确原文证据时填最接近的推断依据。
不要输出解释或思考过程，只输出结果。必须覆盖全部 {n} 个自然村和全部 {{m}} 个聚落，每个自然村至少一个聚落，每个聚落只能属于一个自然村。"""


_CLUE_POS_WORDS = [
    ("中部", "中部"), ("东部", "东"), ("西部", "西"), ("南部", "南"), ("北部", "北"),
    ("东南", "东南"), ("西南", "西南"), ("东北", "东北"), ("西北", "西北"),
    ("东侧", "东"), ("西侧", "西"), ("南侧", "南"), ("北侧", "北"),
    ("东", "东"), ("南", "南"), ("西", "西"), ("北", "北"),
]


def _clue_position(clue: str) -> Optional[str]:
    for word, pos in _CLUE_POS_WORDS:
        if word in (clue or ""):
            return pos
    return None


def _centroid_dist(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def deterministic_village_partition(
    inventory: SpatialInventory,
    workspace: Any,
    clusters: List[VillageCluster],
) -> Dict[str, Dict[str, Any]]:
    """Deterministic village -> clusters partition (no LLM).

    Uses ONLY report facts + KG geometry:
      1. facility -> village associations: each matching facility point's
         nearest residential cluster belongs to that village (L1 text anchor);
      2. per-village direction clues: clusters at the matching relative
         position (方位) belong to that village;
      3. fill: every remaining cluster goes to the nearest anchored village;
         villages with no anchor get the nearest remaining clusters so the
         report's total village count is covered where geometry allows.
    Global consistency holds by construction (one cluster <= one village).
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

    # 0) external-source authoritative coordinates (Tianditu / Tencent / AMap
    #    村名 annotations): a report village whose name matches an external POI
    #    is anchored to the residential cluster nearest that authoritative
    #    point - the strongest spatial evidence available.
    for ext_name, lon, lat in inventory.external_pois:
        ext_base = str(ext_name or "").removesuffix("村").removesuffix("自然村").strip()
        if not ext_base or lon is None or lat is None:
            continue
        for base in report_bases:
            if base == ext_base or base in ext_base or ext_base in base:
                best = min(clusters, key=lambda cl: _centroid_dist(cl.centroid, (lon, lat)))
                _add(base, best.index, f"外源POI:{ext_name}")
                break

    # 1) facility -> village anchors: a facility reported at village V anchors
    #    V to the SINGLE nearest cluster among all its matching points (the
    #    facility's primary location).  Assigning every point would over-load
    #    one village (e.g. 13 祠 points -> 13 clusters to one village).
    for facility, village in inventory.facility_villages:
        evidence = f"设施{facility}位于{village}"
        best_cluster = None
        best_dist = float("inf")
        for c in derive_candidates(workspace, "facility"):
            label = str(c.features.get("名称", "") or "")
            if not label or not (label in facility or facility in label):
                continue
            if not c.centroid:
                continue
            cl = min(clusters, key=lambda x: _centroid_dist(x.centroid, c.centroid))
            d = _centroid_dist(cl.centroid, c.centroid)
            if d < best_dist:
                best_dist = d
                best_cluster = cl
        if best_cluster is not None:
            _add(village, best_cluster.index, evidence)

    # 2) direction clues
    for village, clue in inventory.clues.items():
        pos = _clue_position(clue)
        if pos:
            for cl in clusters:
                if cl.features.get("方位") == pos:
                    _add(village, cl.index, clue[:80])

    if not clusters:
        return mapping

    # 3) coverage fill: every report-named village gets at least one cluster
    #    and every cluster lands somewhere, via spatial nearest - NEVER by
    #    name order or by dumping everything on the first anchor.  Evidence
    #    anchors (steps 1-2) always win; this only covers the rest.
    report_bases = [
        (v.removesuffix("村").removesuffix("自然村").strip() or v)
        for v in inventory.names_by_role.get("village", [])
    ]
    report_bases = list(dict.fromkeys(report_bases))

    def _used() -> set:
        return {idx for item in mapping.values() for idx in item["cluster_indexes"]}

    def _village_centroid(village: str) -> tuple:
        idxs = mapping.get(village, {}).get("cluster_indexes", []) or []
        pts = [c.centroid for c in clusters if c.index in idxs]
        if not pts:
            return (0.0, 0.0)
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    # 3a) every village with no cluster yet takes its nearest free cluster
    #     (spatial proximity, iterated so later villages stay spread out).
    unassigned = [c for c in clusters if c.index not in _used()]
    for village in report_bases:
        if not unassigned:
            break
        if mapping.get(village, {}).get("cluster_indexes"):
            continue
        best = min(unassigned, key=lambda c: _centroid_dist(
            c.centroid,
            _village_centroid(village) if mapping.get(village, {}).get("cluster_indexes") else (
                # no anchor yet: prefer the largest remaining settlement so the
                # village gets a real 宅基地 core (coverage, not name mapping)
                (0.0, 0.0)
            ),
        ))
        _add(village, best.index, "空间就近覆盖")
        unassigned = [c for c in clusters if c.index not in _used()]

    # 3b) any remaining clusters -> nearest already-covered village.
    for cl in clusters:
        if cl.index in _used():
            continue
        covered = [v for v in report_bases if mapping.get(v, {}).get("cluster_indexes")]
        if not covered:
            break
        nearest = min(covered, key=lambda v: _centroid_dist(
            cl.centroid,
            _village_centroid(v),
        ))
        _add(nearest, cl.index, "空间就近")

    # 4) aggregate each village's BSM union + weighted centroid from its member
    #    clusters (same shape the LLM partition produces), so downstream
    #    gazetteer entries carry the spatial extent.
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
) -> List["GazetteerEntry"]:
    """Collective natural-village grounding: assign ALL residential clusters
    across ALL report-named villages (many-to-one partition).

    LLM-driven: the model first derives the natural-village count and per
    village position clues from the report (regex only as fallback), then
    assigns ALL residential clusters to ALL report-named villages under a
    many-to-one constraint (one cluster <= one village enforced by conflict
    resolution).  The deterministic pass (facility->village anchors +
    direction clues + nearest fill) remains as the LLM-free baseline and fills
    villages the LLM leaves uncovered.  Geometry/BSMs always come from the
    bundle clusters; the LLM never emits coordinates.
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
    # clues derived from the report (regex only as fallback).
    meta = await _infer_village_meta(report_text, bases, llm, cache, budget)
    n = int(meta.get("total_count") or 0) or inventory.total_village_count or len(todo)
    clues = dict(inventory.clues)
    clues.update(meta.get("clues") or {})

    # Deterministic baseline: facility->village text anchors + direction clues
    # + nearest fill.  It is the LLM-free path and fills villages the LLM
    # leaves uncovered, so every report-named village is covered where the
    # geometry allows.
    mapping = deterministic_village_partition(inventory, workspace, clusters)

    # LLM-driven full partition: the model assigns ALL residential clusters to
    # ALL report-named villages (many-to-one, one cluster <= one village via
    # conflict resolution).  The deterministic result is only a fallback.
    if llm is not None:
        try:
            cluster_lines = "\n".join(_candidate_line(c) for c in clusters)
            assocs = "；".join(f"{f}@{v}" for f, v in inventory.facility_villages[:24]) or "无"
            pois = "；".join(
                f"{nm}({lon:.4f},{lat:.4f})"
                for nm, lon, lat in inventory.external_pois[:10]
            ) or "无"
            clue_lines = "；".join(f"{v}：{c}" for v, c in clues.items()) or "无"
            prompt = _PARTITION_PROMPT.format(
                n=n, clues=clue_lines, assocs=assocs, pois=pois,
            )
            llm_mapping = await assign_names(
                clusters,
                todo,
                prompt_template=prompt,
                cache_key_prefix="village-partition-v4",
                require_evidence=False,
                report_text=report_text,
                cache=cache,
                llm=llm,
                budget=budget,
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

    Always carries an LLM-recommended placement (bsms/geometry) so the human
    can confirm or override; never an empty 'cannot locate' dead end.
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
    confirmation.  The LLM recommendation is always present; the human only
    arbitrates when confidence is insufficient."""

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
    always_land: bool = True,
) -> GroundReportResult:
    """The complete GROUND flow over a ``PlanningContext`` + typed L1 facts.

    Phase 1: spatial inventory from the report.  Phase 2: collective village
    partition + per-role LLM evidence assignment, upserted into the context
    gazetteer.  Then the evidence index is rebuilt and every fact is audited
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
    )
    try:
        context.location_facts = list(facts or [])
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        context.evidence_index = PlaceEvidenceIndex.build(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[report-grounder] evidence index rebuild failed: %s", exc)

    index = getattr(context, "evidence_index", None)
    queue = HumanReviewQueue()
    entities: List[GroundedEntity] = []
    seen = set()
    # Fallback extent computed once and reused (cluster build is expensive).
    _fallback_cache = {}


    def _fallback(name: str, role: str) -> tuple:
        key = "default"
        if key not in _fallback_cache:
            _fallback_cache[key] = _nearest_extent_fallback(context, name, role)
        return _fallback_cache[key]
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
        if index is not None:
            try:
                res = index.resolve_mention(name, role=role)
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
                source="evidence_index",
            ))
        else:
            # ALWAYS LAND: when the deterministic/LLM pass left a name without
            # an extent, attach the nearest residential-cluster extent as an
            # LLM-recommended placement and raise a human review item.  A name
            # never ends as a dead "cannot locate"; it lands with a confidence
            # and a human decision point.
            fb_bsms, fb_geom, fb_conf = _fallback(name, role)
            if always_land and fb_bsms:
                entities.append(GroundedEntity(
                    name=name,
                    role=role,
                    status="grounded",
                    bsms=fb_bsms,
                    geometry_ref=fb_geom,
                    source="llm_recommended_fallback",
                ))
                queue.add(
                    session_id,
                    LocationReviewItem(
                        name=name,
                        role=role,
                        recommended_bsms=fb_bsms,
                        recommended_geometry_ref=fb_geom,
                        confidence=fb_conf,
                        reason="置信度不足：确定性/LLM 未给出强证据，LLM 推荐落位至最近村落范围，需人工确认",
                    ),
                )
            else:
                entities.append(GroundedEntity(name=name, role=role, status="unresolved"))
    result = GroundReportResult(
        entities=entities,
        counts=counts,
        unresolved=[e.name for e in entities if e.status == "unresolved"],
        reviews=queue.pending(session_id),
        queue=queue,
    )
    logger.info("[report-grounder] %s reviews=%d", result.summary(), len(result.reviews))
    return result


def _nearest_extent_fallback(
    context: Any,
    name: str,
    role: str,
) -> tuple:
    """LLM-recommended fallback extent for a name the evidence pass could not
    place: the nearest residential cluster's BSM union (geometry from the KG,
    never invented).  Confidence is intentionally low so it routes to human
    review."""
    from app.spatial.grounding.village_cluster_mapper import build_village_clusters

    parcels = []
    try:
        workspace = getattr(context, "workspace", None)
        parcels = list((getattr(workspace, "polygons", {}) or {}).get("landuse_current") or [])
    except Exception:
        parcels = []
    clusters = build_village_clusters(parcels)
    if not clusters:
        return [], "", 0.0
    # fallback to the village-centre cluster (largest settlement)
    cluster = clusters[0]
    return (
        list(dict.fromkeys(cluster.bsms or [])),
        f"residential-cluster:{cluster.index}",
        round(0.25 + 0.05 * min(len(cluster.bsms or []), 10), 2),
    )


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
