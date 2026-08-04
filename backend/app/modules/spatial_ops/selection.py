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
    area_ha: float = 0.0
    cluster: str = ""
    distance_m: Optional[float] = None


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
) -> Tuple[List[CandidateParcel], List[Rejection]]:
    from shapely.geometry import Point, shape

    survivors: List[CandidateParcel] = []
    rejected: List[Rejection] = []
    for cand in candidates:
        try:
            geom = shape(cand.geometry)
        except Exception:
            rejected.append(Rejection(cand.bsm, "invalid_geometry"))
            continue
        if geom.is_empty:
            rejected.append(Rejection(cand.bsm, "empty_geometry"))
            continue
        detail: List[str] = []
        if constraint_index is not None:
            overlaps = constraint_index.geometry_in_constraint(cand.geometry) or []
            blocked = sorted({
                ov.constraint_type for ov in overlaps
                if ov.constraint_type in _PROHIBITED_CONSTRAINTS
            })
            if blocked:
                detail.append(f"constraint:{','.join(blocked)}")
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


def score_candidates(
    candidates: List[CandidateParcel],
    *,
    cluster_centroid: Optional[Tuple[float, float]] = None,
    target_ha: Optional[float] = None,
) -> List[ScoredCandidate]:
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
        score = 0.5 * proximity + 0.3 * construction + 0.2 * area_fit
        scored.append(ScoredCandidate(bsm=c.bsm, score=score, distance_m=c.distance_m))
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
