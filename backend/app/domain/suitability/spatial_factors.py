"""Deterministic non-terrain suitability features from authoritative Bundle data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import mapping, shape
from shapely import wkt
from shapely.ops import transform, unary_union

from app.contracts.domain.planning_semantics import (
    RolePolicyFactorKey,
    RolePolicyDisposition,
    RolePolicyKey,
    SuitabilityMaterializationRole,
)

SPATIAL_ROLE_POLICY_VERSION = "materialization_role_policy_v1"
MATERIALIZATION_ROLE_POLICY_UNAVAILABLE = "MATERIALIZATION_ROLE_POLICY_UNAVAILABLE"
_OVERLAY_ROLES = frozenset(
    {
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
    }
)
_SITE_HARD_ROLES = frozenset(
    {
        "land_use_assignment",
        "site_footprint",
    }
)
_KNOWN_MATERIALIZATION_ROLES = frozenset(
    {
        "land_use_assignment",
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
        "site_footprint",
    }
)


@dataclass(frozen=True)
class MaterializationRolePolicy:
    role: SuitabilityMaterializationRole
    policy_key: RolePolicyKey
    factor_policies: dict[RolePolicyFactorKey, RolePolicyDisposition]

    def classify(self, factor_code: str) -> RolePolicyDisposition:
        factor_key = _factor_policy_key(factor_code)
        return self.factor_policies.get(factor_key, "site_hard_exclusion")


def _factor_policy_key(factor_code: str) -> str:
    if factor_code == "FARMLAND_PROTECTION_OVERLAP":
        return "farmland_overlap"
    if factor_code == "ECOLOGICAL_REDLINE_OVERLAP":
        return "ecological_overlap"
    if factor_code == "HAZARD_POINT_BUFFER":
        return "hazard_buffer"
    if factor_code == "ROAD_ACCESS_DISTANCE":
        return "road_access"
    if factor_code == "EXISTING_FACILITY_PROXIMITY":
        return "existing_facility_proximity"
    return "prohibited_constraint_overlap"


def normalize_materialization_role(value: Any) -> SuitabilityMaterializationRole:
    role = str(value or "").strip()
    if role in _KNOWN_MATERIALIZATION_ROLES:
        return role
    return "unknown"


def resolve_materialization_role_policy(value: Any) -> MaterializationRolePolicy | None:
    role = normalize_materialization_role(value)
    if role == "unknown":
        return None
    hard_policy: RolePolicyDisposition = (
        "site_hard_exclusion" if role in _SITE_HARD_ROLES else "overlay_constraint"
    )
    return MaterializationRolePolicy(
        role=role,
        policy_key=f"{SPATIAL_ROLE_POLICY_VERSION}:{role}",
        factor_policies={
            "farmland_overlap": hard_policy,
            "ecological_overlap": hard_policy,
            "hazard_buffer": hard_policy,
            "prohibited_constraint_overlap": hard_policy,
            "road_access": "advisory",
            "existing_facility_proximity": "advisory",
        },
    )


@dataclass(frozen=True)
class ParcelSpatialFactors:
    bsm: str
    hard_feasible: bool
    materialization_role: SuitabilityMaterializationRole = "unknown"
    policy_key: RolePolicyKey = ""
    materialization_role_policy: dict[RolePolicyFactorKey, RolePolicyDisposition] = field(
        default_factory=dict
    )
    road_distance_m: float | None = None
    road_access_score: float | None = None
    facility_distance_m: float | None = None
    facility_coverage_score: float | None = None
    existing_redundancy_score: float | None = None
    hazard_distance_m: float | None = None
    hazard_safety_score: float | None = None
    exclusion_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    score_breakdown: dict[str, float] = field(default_factory=dict)
    hard_constraint_factors: tuple[dict[str, object], ...] = ()
    evaluation_trace: tuple[dict[str, object], ...] = ()


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
        self.farmland = _metric_union(
            _features(getattr(workspace, "polygons", None), "farmland_protection"),
            self.project,
        )
        self.ecological = _metric_union(
            _features(getattr(workspace, "polygons", None), "ecological_redline"),
            self.project,
        )
        if self.roads is None:
            self.diagnostics.append("ROAD_ACCESS_SOURCE_MISSING")
        if self.facilities is None:
            self.diagnostics.append("FACILITY_COVERAGE_SOURCE_MISSING")
        if self.hazards is None:
            self.diagnostics.append("HAZARD_POINT_SOURCE_MISSING")
        if self.farmland is None:
            self.diagnostics.append("FARMLAND_SOURCE_MISSING")
        if self.ecological is None:
            self.diagnostics.append("ECOLOGICAL_SOURCE_MISSING")

    def evaluate(
        self,
        parcel: Any,
        geometry: Any = None,
        *,
        materialization_role: Any = None,
    ) -> ParcelSpatialFactors:
        """Evaluate the selected geometry, falling back to the source parcel.

        SELECT may operate on a clipped planning footprint inside a source
        BSM.  Passing that footprint here prevents a full-parcel overlap or
        distance from incorrectly deciding the subgeometry.
        """
        bsm = str(getattr(parcel, "bsm", "") or "")
        exclusions: list[str] = []
        evidence_refs = [f"bundle:landuse_current:{bsm}"]
        diagnostics = list(self.diagnostics)
        factor_records: list[dict[str, object]] = []
        evaluation_trace: list[dict[str, object]] = []
        role_policy = resolve_materialization_role_policy(materialization_role)
        normalized_role = normalize_materialization_role(materialization_role)
        evaluation_trace.append(
            {
                "step": "materialization_role_policy",
                "materialization_role": normalized_role,
                "policy_key": role_policy.policy_key if role_policy is not None else "",
                "policy": (
                    dict(role_policy.factor_policies) if role_policy is not None else {}
                ),
                "result": "resolved" if role_policy is not None else "fail_closed",
            }
        )
        if role_policy is None:
            factor_records.append(
                {
                    "factor_code": MATERIALIZATION_ROLE_POLICY_UNAVAILABLE,
                    "policy": "site_hard_exclusion",
                    "triggered": True,
                    "hard_exclusion": True,
                    "evidence_ref": "",
                    "detail": "materialization_role is missing or unknown",
                }
            )
            return ParcelSpatialFactors(
                bsm=bsm,
                hard_feasible=False,
                materialization_role=normalized_role,
                policy_key="",
                materialization_role_policy={},
                exclusion_codes=(MATERIALIZATION_ROLE_POLICY_UNAVAILABLE,),
                evidence_refs=tuple(evidence_refs),
                diagnostics=tuple(diagnostics),
                hard_constraint_factors=tuple(factor_records),
                evaluation_trace=tuple(evaluation_trace),
            )
        if self.project is None:
            return ParcelSpatialFactors(
                bsm=bsm,
                hard_feasible=False,
                materialization_role=normalized_role,
                policy_key=role_policy.policy_key,
                materialization_role_policy=dict(role_policy.factor_policies),
                exclusion_codes=("SPATIAL_FACTOR_CRS_UNAVAILABLE",),
                evidence_refs=tuple(evidence_refs),
                diagnostics=tuple(diagnostics),
                evaluation_trace=tuple(evaluation_trace),
            )
        try:
            raw_geometry = geometry
            if raw_geometry is None:
                raw_geometry = getattr(parcel, "geometry", None) or {}
            if isinstance(raw_geometry, str):
                parcel_geometry = wkt.loads(raw_geometry)
            elif isinstance(raw_geometry, dict):
                parcel_geometry = shape(raw_geometry)
            else:
                parcel_geometry = raw_geometry
            if parcel_geometry.is_empty or not parcel_geometry.is_valid:
                raise ValueError("invalid parcel geometry")
            metric = transform(self.project, parcel_geometry)
            evaluation_trace.append(
                {
                    "step": "geometry_prepared",
                    "materialization_role": normalized_role,
                    "geometry_source": "candidate_geometry" if geometry is not None else "parcel_geometry",
                    "result": "ok",
                }
            )
        except Exception:
            return ParcelSpatialFactors(
                bsm=bsm,
                hard_feasible=False,
                materialization_role=normalized_role,
                policy_key=role_policy.policy_key,
                materialization_role_policy=dict(role_policy.factor_policies),
                exclusion_codes=("PARCEL_GEOMETRY_INVALID",),
                evidence_refs=tuple(evidence_refs),
                diagnostics=tuple(diagnostics),
                evaluation_trace=tuple(
                    [
                        *evaluation_trace,
                        {
                            "step": "geometry_prepared",
                            "materialization_role": normalized_role,
                            "geometry_source": "candidate_geometry" if geometry is not None else "parcel_geometry",
                            "result": "invalid",
                        },
                    ]
                ),
            )

        def _record_factor(
            factor_code: str,
            *,
            triggered: bool,
            evidence_ref: str = "",
            detail: str = "",
        ) -> None:
            disposition = role_policy.classify(factor_code)
            hard_exclusion = triggered and disposition == "site_hard_exclusion"
            factor_records.append(
                {
                    "factor_code": factor_code,
                    "policy": disposition,
                    "triggered": triggered,
                    "hard_exclusion": hard_exclusion,
                    "evidence_ref": evidence_ref,
                    "detail": detail,
                }
            )
            evaluation_trace.append(
                {
                    "step": "spatial_factor",
                    "materialization_role": normalized_role,
                    "policy_key": role_policy.policy_key,
                    "factor_code": factor_code,
                    "policy": disposition,
                    "triggered": triggered,
                    "hard_exclusion": hard_exclusion,
                    "evidence_ref": evidence_ref,
                    "detail": detail,
                }
            )
            if hard_exclusion:
                exclusions.append(factor_code)
                if evidence_ref:
                    evidence_refs.append(evidence_ref)

        road_distance = metric.distance(self.roads) if self.roads is not None else None
        facility_distance = (
            metric.representative_point().distance(self.facilities)
            if self.facilities is not None
            else None
        )
        hazard_distance = (
            metric.distance(self.hazards) if self.hazards is not None else None
        )
        if hazard_distance is not None:
            _record_factor(
                "HAZARD_POINT_BUFFER",
                triggered=hazard_distance < self.policy.hazard_min_distance_m,
                evidence_ref="bundle:hazard_points",
                detail=(
                    "distance_m="
                    f"{float(hazard_distance):.6f};threshold_m={float(self.policy.hazard_min_distance_m):.6f}"
                ),
            )

        overlap_fraction_threshold = float(
            getattr(self.policy, "overlap_fraction_threshold", 1e-6) or 1e-6
        )
        for code, polygon, source_ref in (
            ("FARMLAND_PROTECTION_OVERLAP", self.farmland, "bundle:farmland_protection"),
            ("ECOLOGICAL_REDLINE_OVERLAP", self.ecological, "bundle:ecological_redline"),
        ):
            if polygon is None:
                continue
            intersection = metric.intersection(polygon)
            if intersection.is_empty or intersection.area <= 0:
                _record_factor(
                    code,
                    triggered=False,
                    evidence_ref=source_ref,
                    detail="overlap_fraction=0.000000",
                )
                continue
            fraction = intersection.area / max(metric.area, 1e-9)
            _record_factor(
                code,
                triggered=fraction > overlap_fraction_threshold,
                evidence_ref=source_ref,
                detail=(
                    "overlap_fraction="
                    f"{float(fraction):.6f};threshold={overlap_fraction_threshold:.6f}"
                ),
            )

        constraint_index = getattr(self.context, "constraint_index", None)
        if constraint_index is not None:
            from app.spatial.allocation.selection import _PROHIBITED_CONSTRAINTS

            for overlap in constraint_index.geometry_in_constraint(
                mapping(parcel_geometry)
            ) or []:
                code = str(getattr(overlap, "constraint_type", "") or "")
                if code in _PROHIBITED_CONSTRAINTS:
                    _record_factor(
                        code,
                        triggered=True,
                        evidence_ref=f"constraint-index:{code}:{bsm}",
                        detail=(
                            "overlap_area_sqm="
                            f"{float(getattr(overlap, 'overlap_area_sqm', 0.0) or 0.0):.6f};"
                            "overlap_pct="
                            f"{float(getattr(overlap, 'overlap_pct', 0.0) or 0.0):.6f}"
                        ),
                    )

        breakdown: dict[str, float] = {}
        road_score = None
        if road_distance is not None:
            road_score = _distance_score(road_distance, self.policy.road_preferred_distance_m)
            breakdown["road_access"] = road_score
            breakdown["road_distance_m"] = float(road_distance)
            evidence_refs.append("bundle:roads_current")
            _record_factor(
                "ROAD_ACCESS_DISTANCE",
                triggered=True,
                evidence_ref="bundle:roads_current",
                detail=(
                    "distance_m="
                    f"{float(road_distance):.6f};preferred_m={float(self.policy.road_preferred_distance_m):.6f}"
                ),
            )
        # Proximity to an existing facility is not service coverage.  Coverage
        # requires typed demand, facility capacity/type, and a routable network
        # and is evaluated by ``evaluate_facility_service``.  Keep this value
        # only as a diagnostic that penalises redundant co-location.
        service_score = None
        existing_redundancy_score = None
        if facility_distance is not None:
            proximity_score = _distance_score(
                facility_distance,
                self.policy.facility_preferred_distance_m,
            )
            existing_redundancy_score = 1.0 - proximity_score
            breakdown["existing_redundancy"] = existing_redundancy_score
            breakdown["existing_facility_distance_m"] = float(facility_distance)
            evidence_refs.append("bundle:facilities_current")
            _record_factor(
                "EXISTING_FACILITY_PROXIMITY",
                triggered=True,
                evidence_ref="bundle:facilities_current",
                detail=(
                    "distance_m="
                    f"{float(facility_distance):.6f};preferred_m={float(self.policy.facility_preferred_distance_m):.6f}"
                ),
            )
        hazard_score = None
        if hazard_distance is not None:
            hazard_score = min(1.0, hazard_distance / self.policy.hazard_min_distance_m)
            breakdown["hazard_safety"] = hazard_score
            breakdown["hazard_distance_m"] = float(hazard_distance)
            evidence_refs.append("bundle:hazard_points")
        return ParcelSpatialFactors(
            bsm=bsm,
            hard_feasible=not exclusions,
            materialization_role=normalized_role,
            policy_key=role_policy.policy_key,
            materialization_role_policy=dict(role_policy.factor_policies),
            road_distance_m=float(road_distance) if road_distance is not None else None,
            road_access_score=road_score,
            facility_distance_m=(
                float(facility_distance) if facility_distance is not None else None
            ),
            facility_coverage_score=service_score,
            existing_redundancy_score=existing_redundancy_score,
            hazard_distance_m=(
                float(hazard_distance) if hazard_distance is not None else None
            ),
            hazard_safety_score=hazard_score,
            exclusion_codes=tuple(dict.fromkeys(exclusions)),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            diagnostics=tuple(diagnostics),
            score_breakdown=breakdown,
            hard_constraint_factors=tuple(factor_records),
            evaluation_trace=tuple(evaluation_trace),
        )


__all__ = [
    "MATERIALIZATION_ROLE_POLICY_UNAVAILABLE",
    "RolePolicyDisposition",
    "SPATIAL_ROLE_POLICY_VERSION",
    "MaterializationRolePolicy",
    "ParcelSpatialFactors",
    "SpatialFactorIndex",
    "SuitabilityMaterializationRole",
    "normalize_materialization_role",
    "resolve_materialization_role_policy",
]
