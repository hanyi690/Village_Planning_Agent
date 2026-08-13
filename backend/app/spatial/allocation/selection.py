from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

_DEG2_HA = 110.9 * 101.0 * 100.0
_SCALE_HA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(公顷|万平方米|亩|㎡|平方米)")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def compute_area_ha(geometry: Dict[str, Any]) -> float:
    if not geometry:
        return 0.0
    from shapely.geometry import shape

    try:
        geom = shape(geometry)
    except Exception:
        return 0.0
    if geom.is_empty:
        return 0.0
    return geom.area * _DEG2_HA


def parse_scale_ha(scale_text: str) -> Optional[float]:
    text = (scale_text or "").strip()
    if not text:
        return None
    m = _SCALE_HA_RE.search(text)
    if not m:
        cn = re.search(r"占地\s*([一二三四五六七八九十]+)\s*亩", text)
        if not cn:
            return None
        num = _CN_NUM.get(cn.group(1))
        return num / 15.0 if num is not None else None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "公顷":
        return value
    if unit == "万平方米":
        return value
    if unit == "亩":
        return value / 15.0
    return value / 10000.0


_LARGE_BLOCK_KEYWORDS = ("基地", "产业园", "种植园", "养殖场", "示范区", "加工坊", "整理")
_NON_CONSTRUCTION_DLMC = {"商品林", "生态林", "水域", "耕地"}
_NON_BUILDABLE_DLMC = {"水域", "生态林"}


@dataclass
class SelectionTarget:
    target_id: str
    name: str = ""
    category: str = "project"  # project / facility / zone
    scale_text: str = ""


@dataclass
class CandidateParcel:
    bsm: str
    geometry: Dict[str, Any]
    dlmc: str = ""
    dlbm: str = ""
    dlbm_system: str = ""
    area_ha: float = 0.0
    cluster: str = ""
    distance_m: Optional[float] = None
    target_ref: str = ""


def is_large_block_target(target: SelectionTarget) -> bool:
    if target.category == "zone":
        return True
    scale_ha = parse_scale_ha(target.scale_text)
    if scale_ha is not None and scale_ha >= 2.0:
        return True
    text = f"{target.name} {target.scale_text}"
    return any(kw in text for kw in _LARGE_BLOCK_KEYWORDS)


_PROHIBITED_CONSTRAINTS = {
    "farmland_protection", "ecological_redline", "historical_protection",
    "cultivated_land_target", "hazard_control_line", "flood_control_line",
}
_HAZARD_MIN_DIST = 0.001
_OCCUPIED_MIN_DIST = 0.00025


@dataclass
class Rejection:
    bsm: str
    reason: str
    detail: List[str] = field(default_factory=list)


def apply_hard_filters(
    candidates: List[CandidateParcel],
    *,
    constraint_index: Any = None,
    hazards: Optional[List[Any]] = None,
    occupied: Optional[List[Tuple[float, float]]] = None,
    min_area_ha: float = 0.0,
    filter_cache: Optional[Dict[str, Tuple[Any, List[str]]]] = None,
) -> Tuple[List[CandidateParcel], List[Rejection]]:
    from shapely.geometry import Point, shape

    survivors: List[CandidateParcel] = []
    rejected: List[Rejection] = []
    for cand in candidates:
        cache_key = str(cand.bsm)
        cached = filter_cache.get(cache_key) if filter_cache is not None else None
        if cached is None:
            try:
                geom = shape(cand.geometry)
            except Exception:
                if filter_cache is not None:
                    filter_cache[cache_key] = (None, ["invalid_geometry"])
                rejected.append(Rejection(cand.bsm, "invalid_geometry"))
                continue
            if geom.is_empty:
                if filter_cache is not None:
                    filter_cache[cache_key] = (None, ["empty_geometry"])
                rejected.append(Rejection(cand.bsm, "empty_geometry"))
                continue
            static_detail: List[str] = []
            if cand.dlmc in _NON_BUILDABLE_DLMC:
                static_detail.append(f"landuse_not_suitable:{cand.dlmc}")
            if constraint_index is not None:
                overlaps = constraint_index.geometry_in_constraint(cand.geometry) or []
                blocked = sorted({
                    ov.constraint_type for ov in overlaps
                    if ov.constraint_type in _PROHIBITED_CONSTRAINTS
                })
                if blocked:
                    static_detail.append(f"constraint:{','.join(blocked)}")
            if filter_cache is not None:
                filter_cache[cache_key] = (geom, list(static_detail))
        else:
            geom, static_detail = cached
            if geom is None:
                rejected.append(Rejection(cand.bsm, static_detail[0]))
                continue
        detail = list(static_detail)
        if not detail:
            point = geom.representative_point()
            for hazard in hazards or []:
                if point.distance(hazard) < _HAZARD_MIN_DIST:
                    detail.append("hazard_proximity")
                    break
            if not detail:
                for other in occupied or []:
                    if geom.distance(Point(other)) < _OCCUPIED_MIN_DIST:
                        detail.append("occupied_proximity")
                        break
        if min_area_ha > 0 and cand.area_ha < min_area_ha:
            detail.append(f"below_min_area:{min_area_ha}")
        if detail:
            rejected.append(Rejection(cand.bsm, "hard_filter", detail))
        else:
            survivors.append(cand)
    return survivors, rejected


def apply_scale_filter(
    candidates: List[CandidateParcel],
    *,
    allow_large_block: bool = False,
    max_area_ha: float = 2.0,
) -> List[CandidateParcel]:
    if allow_large_block:
        return list(candidates)
    return [
        c for c in candidates
        if not (c.area_ha > max_area_ha and c.dlmc in _NON_CONSTRUCTION_DLMC)
    ]


@dataclass
class ScoredCandidate:
    bsm: str
    score: float
    distance_m: Optional[float]
    reasons: List[str] = field(default_factory=list)


def _is_construction_dlmc(dlmc: str) -> bool:
    return any(kw in (dlmc or "") for kw in ("建设", "居住", "宅基", "空闲"))


_PROJECT_WEIGHT_KEYS = (
    "proximity",
    "construction",
    "area_fit",
    "road_access",
    "service_coverage",
    "adjacency",
    "conversion_cost",
    "slope_hazard",
    "l2_structure_fit",
)

# Per-project-type weight sets for the extended scoring formula. Each set sums
# to 1.0. industrial favors road access + conversion cost; residential favors
# adjacency + service coverage; facility favors service coverage + road access.
PROJECT_WEIGHTS: Dict[str, Dict[str, float]] = {
    "industrial": {
        "proximity": 0.15,
        "construction": 0.10,
        "area_fit": 0.15,
        "road_access": 0.25,
        "service_coverage": 0.05,
        "adjacency": 0.05,
        "conversion_cost": 0.15,
        "slope_hazard": 0.05,
        "l2_structure_fit": 0.05,
    },
    "residential": {
        "proximity": 0.15,
        "construction": 0.10,
        "area_fit": 0.15,
        "road_access": 0.10,
        "service_coverage": 0.15,
        "adjacency": 0.15,
        "conversion_cost": 0.05,
        "slope_hazard": 0.10,
        "l2_structure_fit": 0.05,
    },
    "facility": {
        "proximity": 0.15,
        "construction": 0.05,
        "area_fit": 0.15,
        "road_access": 0.20,
        "service_coverage": 0.25,
        "adjacency": 0.05,
        "conversion_cost": 0.05,
        "slope_hazard": 0.05,
        "l2_structure_fit": 0.05,
    },
    "default": {
        "proximity": 0.20,
        "construction": 0.10,
        "area_fit": 0.15,
        "road_access": 0.15,
        "service_coverage": 0.10,
        "adjacency": 0.10,
        "conversion_cost": 0.10,
        "slope_hazard": 0.05,
        "l2_structure_fit": 0.05,
    },
}

_NEW_CRITERION_DICTS = (
    "road_distance_m",
    "service_coverage",
    "adjacency",
    "conversion_cost",
    "slope_hazard",
    "l2_structure_fit",
)


def score_candidates(
    candidates: List[CandidateParcel],
    *,
    cluster_centroid: Optional[Tuple[float, float]] = None,
    target_ha: Optional[float] = None,
    road_distance_m: Optional[Dict[str, float]] = None,
    service_coverage: Optional[Dict[str, float]] = None,
    adjacency: Optional[Dict[str, float]] = None,
    conversion_cost: Optional[Dict[str, float]] = None,
    slope_hazard: Optional[Dict[str, float]] = None,
    l2_structure_fit: Optional[Dict[str, float]] = None,
    project_type: Optional[str] = None,
) -> List[ScoredCandidate]:
    """Score candidates, optionally with the extended weighted formula.

    When none of the new per-criterion dicts is provided the exact legacy
    formula (``0.5*proximity + 0.3*construction + 0.2*area_fit``) is kept, so
    existing callers and ordering tests are byte-for-byte unchanged. When any
    new dict is present a ``PROJECT_WEIGHTS`` weighted blend of all nine
    dimensions is used. Missing optional evidence is omitted and the remaining
    weights are renormalized; it is never replaced by a neutral 0.5. Dict
    values are pre-normalized to [0,1] (higher = better;
    ``slope_hazard`` higher = safer).
    """
    new_criteria = {
        "road_distance_m": road_distance_m,
        "service_coverage": service_coverage,
        "adjacency": adjacency,
        "conversion_cost": conversion_cost,
        "slope_hazard": slope_hazard,
        "l2_structure_fit": l2_structure_fit,
    }
    extended = any(v is not None for v in new_criteria.values())
    weights = None
    if extended:
        weights = PROJECT_WEIGHTS.get(project_type or "default", PROJECT_WEIGHTS["default"])
    scored: List[ScoredCandidate] = []
    for c in candidates:
        proximity = 0.5
        if cluster_centroid is not None and c.distance_m is not None:
            proximity = 1.0 / (1.0 + c.distance_m / 500.0)
        construction = 1.0 if _is_construction_dlmc(c.dlmc) else 0.3
        area_fit = 0.5
        if target_ha is not None and c.area_ha > 0:
            ratio = c.area_ha / target_ha
            area_fit = max(0.0, 1.0 - abs(math.log2(ratio)))
        reasons = [f"construction:{construction:.2f}"]
        if cluster_centroid is not None and c.distance_m is not None:
            reasons.append(f"proximity:{proximity:.2f}")
        if target_ha is not None and c.area_ha > 0:
            reasons.append(f"area_fit:{area_fit:.2f}")
        if not extended:
            score = 0.5 * proximity + 0.3 * construction + 0.2 * area_fit
            scored.append(
                ScoredCandidate(
                    bsm=c.bsm, score=score, distance_m=c.distance_m, reasons=reasons
                )
            )
            continue
        dims: Dict[str, float] = {
            "proximity": proximity,
            "construction": construction,
            "area_fit": area_fit,
        }
        available_dimensions = {"proximity", "construction", "area_fit"}
        if road_distance_m is not None:
            d = road_distance_m.get(c.bsm)
            if d is not None:
                dims["road_access"] = 1.0 / (1.0 + d / 300.0)
                reasons.append(f"road_access:{dims['road_access']:.2f}")
                available_dimensions.add("road_access")
        for key in (
            "service_coverage",
            "adjacency",
            "conversion_cost",
            "slope_hazard",
            "l2_structure_fit",
        ):
            data = new_criteria[key]
            if data is not None and c.bsm in data and data[c.bsm] is not None:
                val = float(data[c.bsm])
                dims[key] = val
                available_dimensions.add(key)
                reasons.append(f"{key}:{val:.2f}")
        weight_total = sum(weights[key] for key in available_dimensions)
        score = sum(weights[key] * dims[key] for key in available_dimensions) / weight_total
        scored.append(
            ScoredCandidate(
                bsm=c.bsm, score=score, distance_m=c.distance_m, reasons=reasons
            )
        )
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored


def place_anchor_point(
    geometry: Dict[str, Any],
    cluster_centroid: Optional[Tuple[float, float]] = None,
    small_area_ha: float = 2.0,
) -> Optional[Tuple[float, float]]:
    from shapely.geometry import Point, shape

    try:
        geom = shape(geometry)
    except Exception:
        return None
    if geom.is_empty:
        return None
    rep = geom.representative_point()
    if cluster_centroid is None:
        return (rep.x, rep.y)
    if compute_area_ha(geometry) > small_area_ha and geom.geom_type in ("Polygon", "MultiPolygon"):
        exterior = geom.exterior if geom.geom_type == "Polygon" else geom.convex_hull.exterior
        target = Point(cluster_centroid)
        nearest = exterior.interpolate(exterior.project(target))
        return (nearest.x, nearest.y)
    return (rep.x, rep.y)

Ranker = Callable[[List[CandidateParcel], Dict[str, Any]], List[str]]


def rank_candidates(
    candidates: List[CandidateParcel],
    *,
    cluster_centroid: Optional[Tuple[float, float]] = None,
    target_ha: Optional[float] = None,
    ranker: Optional[Ranker] = None,
    context: Optional[Dict[str, Any]] = None,
    road_distance_m: Optional[Dict[str, float]] = None,
    service_coverage: Optional[Dict[str, float]] = None,
    adjacency: Optional[Dict[str, float]] = None,
    conversion_cost: Optional[Dict[str, float]] = None,
    slope_hazard: Optional[Dict[str, float]] = None,
    l2_structure_fit: Optional[Dict[str, float]] = None,
    project_type: Optional[str] = None,
) -> List[ScoredCandidate]:
    pool = {c.bsm for c in candidates}
    if ranker is None:
        return score_candidates(
            candidates,
            cluster_centroid=cluster_centroid,
            target_ha=target_ha,
            road_distance_m=road_distance_m,
            service_coverage=service_coverage,
            adjacency=adjacency,
            conversion_cost=conversion_cost,
            slope_hazard=slope_hazard,
            l2_structure_fit=l2_structure_fit,
            project_type=project_type,
        )
    ctx = dict(context or {})
    ctx.setdefault("cluster_centroid", cluster_centroid)
    ctx.setdefault("target_ha", target_ha)
    ordered = [b for b in (ranker(candidates, ctx) or []) if b in pool]
    for c in candidates:
        if c.bsm not in ordered:
            ordered.append(c.bsm)
    return [ScoredCandidate(bsm=b, score=0.0, distance_m=None) for b in ordered]


@dataclass
class PlacementDecision:
    target_id: str
    selected_bsm: str = ""
    anchor_point: Optional[Tuple[float, float]] = None
    reason: str = ""
    status: str = "unplaced"  # placed / unplaced / deferred
    rejected: List[Rejection] = field(default_factory=list)
    ranking: List[ScoredCandidate] = field(default_factory=list)
    selected_score: float = 0.0


def select_parcel(
    target: SelectionTarget,
    *,
    candidates: List[CandidateParcel],
    constraint_index: Any = None,
    hazards: Optional[List[Any]] = None,
    occupied: Optional[List[Tuple[float, float]]] = None,
    cluster_centroid: Optional[Tuple[float, float]] = None,
    ranker: Optional[Ranker] = None,
    filter_cache: Optional[Dict[str, Tuple[Any, List[str]]]] = None,
    road_distance_m: Optional[Dict[str, float]] = None,
    service_coverage: Optional[Dict[str, float]] = None,
    adjacency: Optional[Dict[str, float]] = None,
    conversion_cost: Optional[Dict[str, float]] = None,
    slope_hazard: Optional[Dict[str, float]] = None,
    l2_structure_fit: Optional[Dict[str, float]] = None,
    project_type: Optional[str] = None,
) -> PlacementDecision:
    target_ha = parse_scale_ha(target.scale_text)
    target_min_area = target_ha if target.category == "project" else 0.0
    survivors, rejected = apply_hard_filters(
        candidates,
        constraint_index=constraint_index,
        hazards=hazards,
        occupied=occupied,
        min_area_ha=target_min_area or 0.0,
        filter_cache=filter_cache,
    )
    survivors = apply_scale_filter(survivors, allow_large_block=is_large_block_target(target))
    ranked = rank_candidates(
        survivors,
        cluster_centroid=cluster_centroid,
        target_ha=target_ha,
        ranker=ranker,
        road_distance_m=road_distance_m,
        service_coverage=service_coverage,
        adjacency=adjacency,
        conversion_cost=conversion_cost,
        slope_hazard=slope_hazard,
        l2_structure_fit=l2_structure_fit,
        project_type=project_type,
    )
    by_bsm = {c.bsm: c for c in survivors}
    for scored in ranked:
        bsm = scored.bsm
        cand = by_bsm[bsm]
        point = place_anchor_point(cand.geometry, cluster_centroid)
        if point is None:
            rejected.append(Rejection(bsm, "no_anchor_point"))
            continue
        return PlacementDecision(
            target_id=target.target_id,
            selected_bsm=bsm,
            anchor_point=point,
            reason=f"rank_top:{bsm}",
            status="placed",
            rejected=rejected,
            ranking=ranked,
            selected_score=scored.score,
        )
    return PlacementDecision(
        target_id=target.target_id,
        status="unplaced",
        rejected=rejected,
        ranking=ranked,
        selected_score=0.0,
    )
