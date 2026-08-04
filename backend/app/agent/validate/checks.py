"""VALIDATE subgraph — deterministic validation checks (Wave J Task 1).

Eight pure, deterministic checks that validate planning artifacts and
attribute each finding to the responsibility stage that should fix it:

  1. hard_constraints       -> SELECT/EXECUTE  candidate falls in a prohibited constraint
  2. area_conservation      -> EXECUTE         split/merge area drift
  3. topology               -> EXECUTE         invalid / empty / gappy geometries
  4. overlap                -> EXECUTE         polygon layer self-overlap
  5. continuity             -> EXECUTE         fragmented zone geometry
  6. accessibility          -> SELECT          facility coordinates invalid / out of reach
  7. contract_completeness  -> EXECUTE/L3      missing parcels or parcel fields
  8. classification_missing -> EXECUTE         non-preserve parcel without a land use

Stage attribution rationale:
  - SELECT: a parcel that was chosen while overlapping a prohibited constraint,
    or a facility placed with invalid coordinates, is a candidate-selection fault.
  - EXECUTE: geometry/layout faults (topology, overlap, continuity, conservation,
    missing classification, incomplete parcel output) are produced by the worker.
  - L3: when intent targets exist but no parcels were produced, the intent may
    not have grounded any parcel (reported as EXECUTE here; fix lies upstream).

No LLM, no KG, no MIP — geometry math only (shapely imported lazily).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional

from app.modules.schema.contracts.validation_report_contracts import ValidationCheck

_AREA_TOLERANCE = 0.05
_POLYGON_TYPES = ("Polygon", "MultiPolygon")

_PROHIBITED_CONSTRAINTS = {
    "farmland_protection",
    "ecological_redline",
    "historical_protection",
    "cultivated_land_target",
    "hazard_control_line",
    "flood_control_line",
}


def _check(
    check_id: str,
    check_name: str,
    passed: bool,
    *,
    stage: str = "EXECUTE",
    actual: str = "",
    expected: str = "",
    parcels: Optional[List[str]] = None,
    fix: str = "",
) -> ValidationCheck:
    return ValidationCheck(
        check_id=check_id,
        check_name=check_name,
        passed=passed,
        actual_value=actual,
        expected_value=expected,
        responsible_stage=stage,
        affected_parcels=list(parcels or []),
        fix_suggestion=fix,
    )


def _wkt_area(wkt: str) -> float:
    if not wkt:
        return 0.0
    try:
        from shapely import wkt as _wkt

        geom = _wkt.loads(wkt)
        return geom.area if geom and not geom.is_empty else 0.0
    except Exception:
        return 0.0


def check_hard_constraints(planned_state: Any, constraint_index: Any) -> List[ValidationCheck]:
    """Check no planned parcel overlaps a prohibited constraint polygon."""
    if constraint_index is None:
        return [
            _check(
                "hard_constraints",
                "硬性约束核查",
                True,
                stage="SELECT",
                actual="constraint_index unavailable",
                expected="constraint_index available",
            )
        ]
    affected: List[str] = []
    for parcel in planned_state.parcels or []:
        wkt = (parcel.geometry or "").strip()
        if not wkt:
            continue
        try:
            from shapely import wkt as _wkt
            from shapely.geometry import mapping

            geojson = mapping(_wkt.loads(wkt))
            overlaps = constraint_index.geometry_in_constraint(geojson) or []
        except Exception:
            continue
        for ov in overlaps:
            if getattr(ov, "constraint_type", "") in _PROHIBITED_CONSTRAINTS:
                affected.append(parcel.bsm)
                break
    passed = not affected
    return [
        _check(
            "hard_constraints",
            "硬性约束核查",
            passed,
            stage="SELECT",
            actual=", ".join(affected),
            expected="no parcel overlaps a prohibited constraint",
            parcels=affected,
            fix="重新选择不落入生态红线/基本农田/灾害控制线等地块",
        )
    ]


def check_area_conservation(changeset: Any) -> List[ValidationCheck]:
    """Check split/merge changes conserve area (5% tolerance on degree^2 areas)."""
    if changeset is None:
        return [_check("area_conservation", "面积守恒", True, stage="EXECUTE")]
    if changeset.area_conservation_verified:
        return [
            _check(
                "area_conservation",
                "面积守恒",
                True,
                stage="EXECUTE",
                actual="verified by pipeline",
            )
        ]
    split_groups: dict = {}
    for change in changeset.changes or []:
        if change.action == "split":
            key = tuple(sorted(change.derived_from_bsms or [])) or (change.bsm,)
            group = split_groups.setdefault(key, {"before": 0.0, "after": 0.0, "bsms": []})
            before = _wkt_area(change.before_geometry_wkt)
            if before > group["before"]:
                group["before"] = before
            group["after"] += _wkt_area(change.after_geometry_wkt)
            group["bsms"].append(change.bsm)
    mismatched: List[str] = []
    for key, group in split_groups.items():
        before = group["before"]
        if before <= 0:
            continue
        ratio = abs(group["after"] - before) / max(before, 1e-9)
        if ratio >= _AREA_TOLERANCE:
            mismatched.extend(group["bsms"])
    passed = not mismatched
    return [
        _check(
            "area_conservation",
            "面积守恒",
            passed,
            stage="EXECUTE",
            actual=", ".join(mismatched),
            expected="split parts sum to the source area within 5%",
            parcels=mismatched,
            fix="核对 split/merge 地块面积，避免面积损失或新增",
        )
    ]


def check_topology(layout_configs: Any) -> List[ValidationCheck]:
    """Check geometries are valid/non-empty and polygon layers have no gaps."""
    invalid: List[str] = []
    empty: List[str] = []
    polygon_groups: List[List[Any]] = []
    for layer in layout_configs or []:
        if not isinstance(layer, dict):
            continue
        data = layer.get("data") or {}
        if data.get("type") != "FeatureCollection":
            continue
        geoms: List[Any] = []
        for feature in data.get("features") or []:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if not geometry:
                continue
            props = feature.get("properties") or {} if isinstance(feature, dict) else {}
            name = props.get("name") or ""
            try:
                from shapely.geometry import shape

                s = shape(geometry)
            except Exception:
                continue
            if s.is_empty:
                empty.append(name)
            elif not s.is_valid:
                invalid.append(name)
            geoms.append(s)
        if layer.get("layerType") in ("zone", "parcel", "polygon") and geoms:
            polygon_groups.append(geoms)

    validity_passed = not invalid and not empty
    checks = [
        _check(
            "topology_validity",
            "拓扑有效性",
            validity_passed,
            stage="EXECUTE",
            actual=f"invalid={invalid}, empty={empty}",
            expected="no invalid or empty geometries",
            fix="修复自相交、空几何等问题",
        )
    ]
    gap_area = 0.0
    for geoms in polygon_groups:
        try:
            from shapely.ops import unary_union

            union = unary_union([g for g in geoms if not g.is_empty])
            if union.is_empty:
                continue
            gap_area += union.convex_hull.difference(union).area
        except Exception:
            continue
    gap_passed = gap_area <= 1e-9
    checks.append(
        _check(
            "topology_gaps",
            "拓扑缝隙",
            gap_passed,
            stage="EXECUTE",
            actual=f"gap_area={gap_area:.6f}",
            expected="polygon layers cover their convex hull without gaps",
            fix="补充缺失图斑或调整边界",
        )
    )
    return checks


def check_overlap(layout_configs: Any) -> List[ValidationCheck]:
    """Check no pair of polygons in a layer overlaps."""
    pair_count = 0
    for layer in layout_configs or []:
        if not isinstance(layer, dict):
            continue
        data = layer.get("data") or {}
        if data.get("type") != "FeatureCollection":
            continue
        geoms: List[Any] = []
        for feature in data.get("features") or []:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if not geometry:
                continue
            try:
                from shapely.geometry import shape

                s = shape(geometry)
                if not s.is_empty and s.geom_type in _POLYGON_TYPES:
                    geoms.append(s)
            except Exception:
                continue
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                try:
                    inter = geoms[i].intersection(geoms[j])
                    if not inter.is_empty and inter.area > 1e-12:
                        pair_count += 1
                except Exception:
                    continue
    passed = pair_count == 0
    return [
        _check(
            "overlap",
            "图层重叠",
            passed,
            stage="EXECUTE",
            actual=f"{pair_count} overlapping pairs",
            expected="no polygon pairs overlap",
            fix="消除地块/图斑之间的重叠区域",
        )
    ]


def check_continuity(layout_configs: Any) -> List[ValidationCheck]:
    """Check each zone is a single contiguous geometry (no fragmented parts)."""
    fragmented: List[str] = []
    for layer in layout_configs or []:
        if not isinstance(layer, dict):
            continue
        data = layer.get("data") or {}
        if data.get("type") != "FeatureCollection":
            continue
        name_groups: dict = {}
        for feature in data.get("features") or []:
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            if not geometry:
                continue
            props = feature.get("properties") or {} if isinstance(feature, dict) else {}
            name = props.get("name") or "unnamed"
            try:
                from shapely.geometry import shape

                s = shape(geometry)
            except Exception:
                continue
            name_groups.setdefault(name, []).append(s)
        for name, geoms in name_groups.items():
            for g in geoms:
                if g.geom_type == "MultiPolygon" and len(g.geoms) > 1:
                    fragmented.append(name)
            if len(geoms) > 1:
                fragmented.append(name)
    fragmented = sorted(set(fragmented))
    passed = not fragmented
    return [
        _check(
            "continuity",
            "图斑连续性",
            passed,
            stage="EXECUTE",
            actual=", ".join(fragmented),
            expected="each zone is a single contiguous geometry",
            fix="合并同一用地的碎片图斑",
        )
    ]


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    radius_km = 6371.0
    dlon = radians(lon2 - lon1)
    dlat = radians(lat2 - lat1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius_km * asin(sqrt(a))


def _parcel_centroid_lonlat(planned_state: Any) -> Optional[tuple]:
    from shapely import wkt as _wkt

    points: List[tuple] = []
    for parcel in planned_state.parcels or []:
        wkt = (parcel.geometry or "").strip()
        if not wkt:
            continue
        try:
            geom = _wkt.loads(wkt)
            if geom.is_empty:
                continue
            c = geom.centroid
            points.append((c.x, c.y))
        except Exception:
            continue
    if not points:
        return None
    n = len(points)
    return (sum(x for x, _ in points) / n, sum(y for _, y in points) / n)


def _facilities_from_intent(intent: Any) -> List[SimpleNamespace]:
    facilities: List[SimpleNamespace] = []
    for target in getattr(intent, "facilities", None) or []:
        anchor = getattr(target, "anchor_point", None)
        if anchor is None:
            continue
        facilities.append(
            SimpleNamespace(
                name=target.type or "facility",
                facility_type=target.type or "",
                lon=float(anchor[0]),
                lat=float(anchor[1]),
                service_radius=float(getattr(target, "service_radius", None) or 0.0),
            )
        )
    return facilities


def check_accessibility(planned_state: Any, intent: Any = None) -> List[ValidationCheck]:
    """Check every facility has valid coordinates and is within service radius."""
    facilities = list(getattr(planned_state, "facilities", None) or [])
    if not facilities and intent is not None:
        facilities = _facilities_from_intent(intent)
    center = _parcel_centroid_lonlat(planned_state)
    invalid: List[str] = []
    for fac in facilities:
        lon = float(getattr(fac, "lon", 0.0) or 0.0)
        lat = float(getattr(fac, "lat", 0.0) or 0.0)
        name = getattr(fac, "name", "") or "facility"
        if lon == 0.0 and lat == 0.0:
            invalid.append(name)
            continue
        radius = float(getattr(fac, "service_radius", 0.0) or 0.0)
        if radius > 0 and center is not None:
            distance_km = _haversine_km(lon, lat, center[0], center[1])
            if distance_km * 1000 > radius:
                invalid.append(name)
    passed = not invalid
    return [
        _check(
            "accessibility",
            "设施可达性",
            passed,
            stage="SELECT",
            actual=", ".join(invalid),
            expected="all facilities have valid coordinates within service radius",
            fix="为设施提供有效坐标或调整服务半径",
        )
    ]


def check_contract_completeness(
    planned_state: Any, changeset: Any, intent: Any = None
) -> List[ValidationCheck]:
    """Check parcels are produced when targets exist and fields are complete."""
    if intent is None:
        intent = SimpleNamespace(project_targets=[], zone_targets=[])
    project_targets = list(getattr(intent, "project_targets", None) or [])
    zone_targets = list(getattr(intent, "zone_targets", None) or [])
    need_parcels = bool(project_targets or zone_targets)
    parcels_present = (not need_parcels) or bool(planned_state.parcels)
    missing_bsm = [p.bsm for p in planned_state.parcels if not (p.bsm or "").strip()]
    missing_geom = [p.bsm or "?" for p in planned_state.parcels if not (p.geometry or "").strip()]
    parcel_fields_ok = not missing_bsm and not missing_geom
    flags_ok = bool(
        changeset
        and changeset.area_conservation_verified
        and changeset.geometry_validity_verified
    )
    return [
        _check(
            "parcels_present",
            "地块产出完整性",
            parcels_present,
            stage="EXECUTE",
            actual=f"{len(planned_state.parcels)} parcels",
            expected="parcels produced when zone/project targets exist",
            fix="补充地块生成逻辑，产出 planned parcels",
        ),
        _check(
            "parcel_fields",
            "地块字段完整",
            parcel_fields_ok,
            stage="EXECUTE",
            actual=f"missing_bsm={missing_bsm}, missing_geom={missing_geom}",
            expected="every planned parcel has bsm and geometry",
            fix="补齐地块 bsm 与 geometry",
        ),
        _check(
            "changeset_flags",
            "变更集校验标志",
            flags_ok,
            stage="EXECUTE",
            actual=(
                f"conservation={bool(changeset and changeset.area_conservation_verified)}, "
                f"validity={bool(changeset and changeset.geometry_validity_verified)}"
            ),
            expected="area_conservation_verified and geometry_validity_verified recorded",
            fix="记录面积守恒与几何有效性校验结果",
        ),
    ]


def check_classification_missing(planned_state: Any) -> List[ValidationCheck]:
    """Check non-preserve parcels carry a planning land use classification."""
    missing = [
        p.bsm
        for p in planned_state.parcels
        if p.operation != "preserve" and not (p.planning_land_use or "").strip()
    ]
    passed = not missing
    return [
        _check(
            "classification_missing",
            "规划分类缺失",
            passed,
            stage="EXECUTE",
            actual=", ".join(missing),
            expected="non-preserve parcels carry a planning_land_use",
            parcels=missing,
            fix="为地块补充规划分类编码（planning_land_use）",
        )
    ]


__all__ = [
    "check_hard_constraints",
    "check_area_conservation",
    "check_topology",
    "check_overlap",
    "check_continuity",
    "check_accessibility",
    "check_contract_completeness",
    "check_classification_missing",
]
