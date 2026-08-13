"""Deterministic non-terrain suitability features from authoritative Bundle data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape
from shapely.ops import transform, unary_union


@dataclass(frozen=True)
class ParcelSpatialFactors:
    bsm: str
    hard_feasible: bool
    road_distance_m: float | None = None
    road_access_score: float | None = None
    facility_distance_m: float | None = None
    facility_coverage_score: float | None = None
    hazard_distance_m: float | None = None
    hazard_safety_score: float | None = None
    exclusion_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    score_breakdown: dict[str, float] = field(default_factory=dict)


def _features(group: Any, key: str) -> list[Any]:
    return list(group.get(key) or []) if group is not None and hasattr(group, "get") else []


def _metric_transformer(crs: str):
    from pyproj import Transformer

    return Transformer.from_crs(crs, "EPSG:3857", always_xy=True).transform


def _metric_union(features: list[Any], project) -> Any:
    geometries = []
    for feature in features:
        try:
            geometry = shape(getattr(feature, "geometry", None) or {})
            if not geometry.is_empty and geometry.is_valid:
                geometries.append(transform(project, geometry))
        except Exception:
            continue
    return unary_union(geometries) if geometries else None


def _distance_score(distance_m: float, preferred_m: float) -> float:
    return 1.0 / (1.0 + max(distance_m, 0.0) / preferred_m)


class SpatialFactorIndex:
    """Precompute road, facility and hazard geometries once per SELECT run."""

    def __init__(self, context: Any, policy: Any) -> None:
        self.context = context
        self.policy = policy
        workspace = getattr(context, "workspace", None)
        metadata = getattr(workspace, "metadata", None)
        self.crs = str(getattr(metadata, "crs", "") or "")
        self.diagnostics: list[str] = []
        self.project = None
        self.roads = None
        self.facilities = None
        self.hazards = None
        if not self.crs:
            self.diagnostics.append("SPATIAL_FACTOR_CRS_MISSING")
            return
        try:
            self.project = _metric_transformer(self.crs)
        except Exception:
            self.diagnostics.append("SPATIAL_FACTOR_CRS_INVALID")
            return
        self.roads = _metric_union(
            _features(getattr(workspace, "lines", None), "roads_current"),
            self.project,
        )
        self.facilities = _metric_union(
            _features(getattr(workspace, "points", None), "facilities_current"),
            self.project,
        )
        self.hazards = _metric_union(
            _features(getattr(workspace, "points", None), "hazard_points"),
            self.project,
        )
        if self.roads is None:
            self.diagnostics.append("ROAD_ACCESS_SOURCE_MISSING")
        if self.facilities is None:
            self.diagnostics.append("FACILITY_COVERAGE_SOURCE_MISSING")
        if self.hazards is None:
            self.diagnostics.append("HAZARD_POINT_SOURCE_MISSING")

    def evaluate(self, parcel: Any) -> ParcelSpatialFactors:
        bsm = str(getattr(parcel, "bsm", "") or "")
        exclusions: list[str] = []
        evidence_refs = [f"bundle:landuse_current:{bsm}"]
        diagnostics = list(self.diagnostics)
        if self.project is None:
            return ParcelSpatialFactors(
                bsm=bsm,
                hard_feasible=False,
                exclusion_codes=("SPATIAL_FACTOR_CRS_UNAVAILABLE",),
                evidence_refs=tuple(evidence_refs),
                diagnostics=tuple(diagnostics),
            )
        try:
            parcel_geometry = shape(getattr(parcel, "geometry", None) or {})
            if parcel_geometry.is_empty or not parcel_geometry.is_valid:
                raise ValueError("invalid parcel geometry")
            metric = transform(self.project, parcel_geometry)
        except Exception:
            return ParcelSpatialFactors(
                bsm=bsm,
                hard_feasible=False,
                exclusion_codes=("PARCEL_GEOMETRY_INVALID",),
                evidence_refs=tuple(evidence_refs),
                diagnostics=tuple(diagnostics),
            )

        road_distance = metric.distance(self.roads) if self.roads is not None else None
        facility_distance = (
            metric.representative_point().distance(self.facilities)
            if self.facilities is not None
            else None
        )
        hazard_distance = (
            metric.distance(self.hazards) if self.hazards is not None else None
        )
        if hazard_distance is not None and hazard_distance < self.policy.hazard_min_distance_m:
            exclusions.append("HAZARD_POINT_BUFFER")
            evidence_refs.append("bundle:hazard_points")

        constraint_index = getattr(self.context, "constraint_index", None)
        if constraint_index is not None:
            from app.spatial.allocation.selection import _PROHIBITED_CONSTRAINTS

            for overlap in constraint_index.geometry_in_constraint(parcel.geometry) or []:
                code = str(getattr(overlap, "constraint_type", "") or "")
                if code in _PROHIBITED_CONSTRAINTS:
                    exclusions.append(code)
                    evidence_refs.append(f"constraint-index:{code}:{bsm}")

        breakdown: dict[str, float] = {}
        road_score = None
        if road_distance is not None:
            road_score = _distance_score(road_distance, self.policy.road_preferred_distance_m)
            breakdown["road_access"] = road_score
            breakdown["road_distance_m"] = float(road_distance)
            evidence_refs.append("bundle:roads_current")
        service_score = None
        if facility_distance is not None:
            service_score = _distance_score(
                facility_distance,
                self.policy.facility_preferred_distance_m,
            )
            breakdown["service_coverage"] = service_score
            breakdown["facility_distance_m"] = float(facility_distance)
            evidence_refs.append("bundle:facilities_current")
        hazard_score = None
        if hazard_distance is not None:
            hazard_score = min(1.0, hazard_distance / self.policy.hazard_min_distance_m)
            breakdown["hazard_safety"] = hazard_score
            breakdown["hazard_distance_m"] = float(hazard_distance)
            evidence_refs.append("bundle:hazard_points")
        return ParcelSpatialFactors(
            bsm=bsm,
            hard_feasible=not exclusions,
            road_distance_m=float(road_distance) if road_distance is not None else None,
            road_access_score=road_score,
            facility_distance_m=(
                float(facility_distance) if facility_distance is not None else None
            ),
            facility_coverage_score=service_score,
            hazard_distance_m=(
                float(hazard_distance) if hazard_distance is not None else None
            ),
            hazard_safety_score=hazard_score,
            exclusion_codes=tuple(dict.fromkeys(exclusions)),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            diagnostics=tuple(diagnostics),
            score_breakdown=breakdown,
        )


__all__ = ["ParcelSpatialFactors", "SpatialFactorIndex"]
