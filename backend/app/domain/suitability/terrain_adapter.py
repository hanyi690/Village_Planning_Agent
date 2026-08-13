"""Adapt terrain evidence into target-bound suitability candidate features."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from rasterio.errors import RasterioError
from shapely import from_wkt
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.contracts.spatial.terrain_evidence import TerrainEvidenceConfig
from app.domain.suitability.candidate_features import (
    CandidateSuitabilityFeatures,
    EvidenceAvailabilityDiagnostic,
    SuitabilityEvidenceAvailability,
    TerrainCandidateFeatures,
)
from app.domain.suitability.policy import VersionedSuitabilityPolicy
from app.domain.suitability.terrain import assess_terrain_suitability
from app.spatial.terrain import TerrainEvidenceService, TerrainSourceError


_FACTORS = (
    "terrain",
    "hazard",
    "farmland_protection",
    "ecological_protection",
    "road_access",
    "facility_coverage",
)


def _features(group: Any, key: str) -> list[Any]:
    if group is None or not hasattr(group, "get"):
        return []
    return list(group.get(key) or [])


def _geometry_usable(feature: Any) -> bool:
    geometry = getattr(feature, "geometry", None)
    if not geometry:
        return False
    try:
        value = geometry if isinstance(geometry, BaseGeometry) else shape(geometry)
        return not value.is_empty and value.is_valid
    except (TypeError, ValueError):
        return False


def _usable_count(features: Sequence[Any]) -> int:
    return sum(1 for item in features if _geometry_usable(item))


def _demand_row_usable(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    geometry = row.get("geometry")
    if geometry:
        try:
            value = geometry if isinstance(geometry, BaseGeometry) else shape(geometry)
            if value.geom_type in {"Point", "MultiPoint"} and not value.is_empty:
                return True
        except (TypeError, ValueError):
            pass
    for longitude, latitude in (
        ("lon", "lat"),
        ("longitude", "latitude"),
        ("经度", "纬度"),
    ):
        try:
            if row.get(longitude) is not None and row.get(latitude) is not None:
                float(row[longitude])
                float(row[latitude])
                return True
        except (TypeError, ValueError):
            continue
    return False


def _blocks(
    policy: VersionedSuitabilityPolicy,
    factor: str,
    status: str,
) -> bool:
    requirement = getattr(policy.factors, factor)
    return (
        status != "available"
        and requirement.required
        and requirement.on_unavailable == "block_candidate"
    )


def _diagnostic(
    policy: VersionedSuitabilityPolicy,
    *,
    factor: str,
    status: str,
    code: str,
    source_fields: Sequence[str] = (),
    observed_count: int = 0,
    usable_count: int = 0,
    missing_fields: Sequence[str] = (),
    evidence_refs: Sequence[str] = (),
    details: dict[str, int | float | str | bool | None] | None = None,
) -> EvidenceAvailabilityDiagnostic:
    return EvidenceAvailabilityDiagnostic(
        factor=factor,
        status=status,
        code=code,
        source_fields=tuple(source_fields),
        observed_count=observed_count,
        usable_count=usable_count,
        missing_fields=tuple(missing_fields),
        evidence_refs=tuple(evidence_refs),
        details=details or {},
        blocks_candidate=_blocks(policy, factor, status),
    )


def audit_suitability_evidence_availability(
    planning_context: Any,
    policy: VersionedSuitabilityPolicy,
    *,
    terrain_service: TerrainEvidenceService | None = None,
    terrain_error: str = "",
    terrain_failure_status: str = "missing",
) -> SuitabilityEvidenceAvailability:
    """Inventory real Bundle fields without fabricating candidate-level scores."""

    workspace = getattr(planning_context, "workspace", None)
    points = getattr(workspace, "points", None)
    lines = getattr(workspace, "lines", None)
    polygons = getattr(workspace, "polygons", None)
    tables = getattr(workspace, "tables", None)
    diagnostics: list[EvidenceAvailabilityDiagnostic] = []

    if terrain_service is None:
        invalid_source = terrain_failure_status == "invalid"
        diagnostics.append(
            _diagnostic(
                policy,
                factor="terrain",
                status="invalid" if invalid_source else "missing",
                code="TERRAIN_DEM_INVALID" if invalid_source else "TERRAIN_DEM_MISSING",
                source_fields=("workspace.rasters.dem", "catalog.layer_type:dem"),
                missing_fields=("dem",),
                details={"error": terrain_error or "DEM source was not resolved"},
            )
        )
    elif not terrain_service.metadata.valid:
        diagnostics.append(
            _diagnostic(
                policy,
                factor="terrain",
                status="invalid",
                code="TERRAIN_DEM_INVALID",
                source_fields=("workspace.rasters.dem", "catalog.layer_type:dem"),
                observed_count=1,
                evidence_refs=(terrain_service.metadata.source_sha256,),
                details={"diagnostics": "|".join(terrain_service.metadata.diagnostics)},
            )
        )
    else:
        diagnostics.append(
            _diagnostic(
                policy,
                factor="terrain",
                status="available",
                code="TERRAIN_DEM_AVAILABLE",
                source_fields=("workspace.rasters.dem", "catalog.layer_type:dem"),
                observed_count=1,
                usable_count=1,
                evidence_refs=(terrain_service.metadata.source_sha256,),
                details={
                    "crs": terrain_service.metadata.crs,
                    "nodata_declared": terrain_service.metadata.nodata is not None,
                    "source_origin": terrain_service.metadata.source_origin,
                },
            )
        )

    hazard_points = _features(points, "hazard_points")
    hazard_lines = _features(polygons, "hazard_control_lines")
    if not hazard_lines:
        hazard_lines = _features(polygons, "hazard_control_line")
    hazard_observed = len(hazard_points) + len(hazard_lines)
    hazard_usable = _usable_count(hazard_points) + _usable_count(hazard_lines)
    diagnostics.append(
        _diagnostic(
            policy,
            factor="hazard",
            status="source_only" if hazard_usable else "missing",
            code=(
                "HAZARD_SOURCE_AVAILABLE_FEATURE_NOT_COMPUTED"
                if hazard_usable
                else "HAZARD_SOURCE_MISSING"
            ),
            source_fields=(
                "workspace.points.hazard_points",
                "workspace.polygons.hazard_control_lines",
            ),
            observed_count=hazard_observed,
            usable_count=hazard_usable,
            missing_fields=(() if hazard_usable else ("hazard geometry",)),
            details={
                "hazard_point_count": len(hazard_points),
                "hazard_control_geometry_count": len(hazard_lines),
                "invalid_geometry_count": hazard_observed - hazard_usable,
            },
        )
    )

    for factor, field, code_prefix in (
        ("farmland_protection", "farmland_protection", "FARMLAND"),
        ("ecological_protection", "ecological_redline", "ECOLOGICAL"),
    ):
        items = _features(polygons, field)
        usable = _usable_count(items)
        diagnostics.append(
            _diagnostic(
                policy,
                factor=factor,
                status="source_only" if usable else "missing",
                code=(
                    f"{code_prefix}_SOURCE_AVAILABLE_OVERLAP_NOT_COMPUTED"
                    if usable
                    else f"{code_prefix}_SOURCE_MISSING"
                ),
                source_fields=(f"workspace.polygons.{field}",),
                observed_count=len(items),
                usable_count=usable,
                missing_fields=(() if usable else (f"{field} geometry",)),
                details={"invalid_geometry_count": len(items) - usable},
            )
        )

    roads = _features(lines, "roads_current")
    usable_roads = _usable_count(roads)
    diagnostics.append(
        _diagnostic(
            policy,
            factor="road_access",
            status="source_only" if usable_roads else "missing",
            code=(
                "ROAD_SOURCE_AVAILABLE_ACCESS_NOT_COMPUTED"
                if usable_roads
                else "ROAD_SOURCE_MISSING"
            ),
            source_fields=("workspace.lines.roads_current",),
            observed_count=len(roads),
            usable_count=usable_roads,
            missing_fields=(() if usable_roads else ("current road geometry",)),
            details={"invalid_geometry_count": len(roads) - usable_roads},
        )
    )

    facilities = _features(points, "facilities_current")
    annotations = _features(points, "annotations_current")
    usable_facilities = _usable_count(facilities)
    radius_count = sum(
        1 for item in facilities if float(getattr(item, "service_radius", 0.0) or 0.0) > 0.0
    )
    population = getattr(tables, "population", None)
    population_values = list(getattr(population, "rows", None) or [])
    population_rows = len(population_values)
    geolocated_demand_count = sum(
        1 for row in population_values if _demand_row_usable(row)
    )
    facility_observed = len(facilities) + len(annotations)
    missing_facility_fields: list[str] = []
    if usable_facilities == 0:
        missing_facility_fields.append("typed facility geometry")
    if radius_count == 0:
        missing_facility_fields.append("service_radius")
    if geolocated_demand_count == 0:
        missing_facility_fields.append("geolocated demand points")
    facility_source_present = facility_observed > 0 or population_rows > 0
    diagnostics.append(
        _diagnostic(
            policy,
            factor="facility_coverage",
            status="source_only" if facility_source_present else "missing",
            code=(
                "FACILITY_COVERAGE_INPUTS_INCOMPLETE"
                if facility_source_present and missing_facility_fields
                else (
                    "FACILITY_COVERAGE_SOURCE_AVAILABLE_FEATURE_NOT_COMPUTED"
                    if facility_source_present
                    else "FACILITY_COVERAGE_SOURCE_MISSING"
                )
            ),
            source_fields=(
                "workspace.points.facilities_current",
                "workspace.points.annotations_current",
                "workspace.tables.population",
            ),
            observed_count=facility_observed + population_rows,
            usable_count=usable_facilities,
            missing_fields=tuple(missing_facility_fields),
            details={
                "typed_facility_count": len(facilities),
                "annotation_anchor_count": len(annotations),
                "positive_service_radius_count": radius_count,
                "population_row_count": population_rows,
                "geolocated_demand_count": geolocated_demand_count,
            },
        )
    )

    ordered = tuple(
        next(item for item in diagnostics if item.factor == factor)
        for factor in _FACTORS
    )
    return SuitabilityEvidenceAvailability(
        policy_ref=policy.ref,
        policy_digest=policy.digest,
        diagnostics=ordered,
    )


class TerrainCandidateFeatureAdapter:
    """Build terrain features for exact, target-bound Grounding candidates."""

    def __init__(
        self,
        planning_context: Any,
        policy: VersionedSuitabilityPolicy,
        *,
        terrain_service: TerrainEvidenceService | None,
        terrain_error: str = "",
        terrain_failure_status: str = "missing",
        geometry_crs: str = "",
    ) -> None:
        self.planning_context = planning_context
        self.policy = policy
        self.terrain_service = terrain_service
        self.terrain_error = terrain_error
        self.terrain_failure_status = terrain_failure_status
        workspace = getattr(planning_context, "workspace", None)
        metadata = getattr(workspace, "metadata", None)
        self.geometry_crs = str(
            geometry_crs or getattr(metadata, "crs", "") or ""
        )
        self.availability = audit_suitability_evidence_availability(
            planning_context,
            policy,
            terrain_service=terrain_service,
            terrain_error=terrain_error,
            terrain_failure_status=terrain_failure_status,
        )

    @classmethod
    def from_context(
        cls,
        planning_context: Any,
        policy: VersionedSuitabilityPolicy,
        *,
        catalog: Any | None = None,
        cache_dir: str | Path | None = None,
        terrain_config: TerrainEvidenceConfig | None = None,
        geometry_crs: str = "",
    ) -> "TerrainCandidateFeatureAdapter":
        service = None
        error = ""
        failure_status = "missing"
        try:
            service = TerrainEvidenceService.open(
                planning_context=planning_context,
                catalog=catalog,
                config=terrain_config,
                cache_dir=cache_dir,
            )
        except TerrainSourceError as exc:
            error = str(exc)
        except (OSError, ValueError, RasterioError) as exc:
            error = str(exc)
            failure_status = "invalid"
        return cls(
            planning_context,
            policy,
            terrain_service=service,
            terrain_error=error,
            terrain_failure_status=failure_status,
            geometry_crs=geometry_crs,
        )

    def _candidate_geometry(
        self,
        candidate: Any,
    ) -> tuple[Any | None, str, tuple[str, ...]]:
        candidate_wkt = str(getattr(candidate, "available_geometry_wkt", "") or "")
        if candidate_wkt:
            try:
                geometry = from_wkt(candidate_wkt)
                if geometry.is_empty or not geometry.is_valid:
                    raise ValueError("candidate WKT is empty or invalid")
                return geometry, "candidate_wkt", ()
            except (TypeError, ValueError) as exc:
                return None, "unavailable", (f"CANDIDATE_GEOMETRY_INVALID:{exc}",)

        source_parcels = tuple(str(item) for item in getattr(candidate, "source_parcels", ()) or ())
        if not source_parcels:
            return None, "unavailable", ("CANDIDATE_SOURCE_PARCELS_MISSING",)
        current = list(self.planning_context.current_parcels())
        by_bsm = {str(getattr(parcel, "bsm", "") or ""): parcel for parcel in current}
        missing = tuple(bsm for bsm in source_parcels if bsm not in by_bsm)
        if missing:
            return None, "unavailable", tuple(
                f"CANDIDATE_SOURCE_PARCEL_NOT_FOUND:{bsm}" for bsm in missing
            )
        geometries = []
        for bsm in source_parcels:
            parcel = by_bsm[bsm]
            try:
                raw_geometry = getattr(parcel, "geometry", None)
                geometry = (
                    raw_geometry
                    if isinstance(raw_geometry, BaseGeometry)
                    else shape(raw_geometry)
                )
            except (TypeError, ValueError):
                return None, "unavailable", (f"CANDIDATE_SOURCE_GEOMETRY_INVALID:{bsm}",)
            if geometry.is_empty or not geometry.is_valid:
                return None, "unavailable", (f"CANDIDATE_SOURCE_GEOMETRY_INVALID:{bsm}",)
            geometries.append(geometry)
        return unary_union(geometries), "bundle_source_parcels", ()

    def build_candidate(self, candidate: Any) -> CandidateSuitabilityFeatures:
        candidate_id = str(getattr(candidate, "site_id", "") or "")
        target_id = str(
            getattr(candidate, "target_ref", None)
            or getattr(candidate, "project_ref", None)
            or ""
        )
        source_parcels = tuple(
            str(item) for item in getattr(candidate, "source_parcels", ()) or ()
        )
        blocking_codes: list[str] = []
        if not target_id:
            blocking_codes.append("CANDIDATE_TARGET_REF_MISSING")
        if not source_parcels:
            blocking_codes.append("CANDIDATE_SOURCE_PARCELS_MISSING")
        hard_result = getattr(candidate, "hard_constraint_result", None)
        grounding_hard_feasible = bool(
            hard_result is not None and getattr(hard_result, "passed", False)
        )
        if hard_result is None:
            blocking_codes.append("GROUND_HARD_CONSTRAINTS_UNPROVEN")
        elif not grounding_hard_feasible:
            blocking_codes.append("GROUND_HARD_CONSTRAINTS_FAILED")

        terrain_feature = TerrainCandidateFeatures(
            status="missing",
            classification="unknown",
            hard_feasible=False,
            reason_codes=("TERRAIN_DEM_MISSING",),
        )
        geometry_source = "unavailable"
        candidate_availability = list(self.availability.diagnostics)
        terrain_diagnostic = self.availability.for_factor("terrain")

        if not self.geometry_crs:
            blocking_codes.append("CANDIDATE_GEOMETRY_CRS_MISSING")
            terrain_diagnostic = _diagnostic(
                self.policy,
                factor="terrain",
                status="invalid",
                code="TERRAIN_CANDIDATE_CRS_MISSING",
                missing_fields=("candidate geometry CRS",),
            )
            terrain_feature = terrain_feature.model_copy(
                update={
                    "status": "invalid",
                    "reason_codes": ("CANDIDATE_GEOMETRY_CRS_MISSING",),
                }
            )
        elif self.terrain_service is not None and self.terrain_service.metadata.valid:
            geometry, geometry_source, geometry_errors = self._candidate_geometry(candidate)
            if geometry is None:
                blocking_codes.extend(geometry_errors)
                terrain_diagnostic = _diagnostic(
                    self.policy,
                    factor="terrain",
                    status="invalid",
                    code="TERRAIN_CANDIDATE_GEOMETRY_UNAVAILABLE",
                    missing_fields=("candidate geometry",),
                    details={"reason": "|".join(geometry_errors)},
                )
                terrain_feature = terrain_feature.model_copy(
                    update={
                        "status": "invalid",
                        "reason_codes": geometry_errors,
                    }
                )
            else:
                evidence = self.terrain_service.analyze_geometry(
                    candidate_id,
                    geometry,
                    geometry_crs=self.geometry_crs,
                )
                assessment = assess_terrain_suitability(evidence, self.policy.terrain)
                evidence_available = (
                    evidence.status == "ready"
                    and assessment.classification != "unknown"
                )
                terrain_status = "available" if evidence_available else "invalid"
                reasons = (
                    tuple(assessment.reasons)
                    if evidence_available
                    else tuple(assessment.reasons) or tuple(evidence.diagnostics)
                )
                terrain_feature = TerrainCandidateFeatures(
                    status=terrain_status,
                    elevation_min_m=evidence.elevation.minimum,
                    elevation_max_m=evidence.elevation.maximum,
                    elevation_mean_m=evidence.elevation.mean,
                    elevation_p90_m=evidence.elevation.p90,
                    slope_mean_degrees=evidence.slope.mean,
                    slope_p90_degrees=evidence.slope.p90,
                    slope_max_degrees=evidence.slope.maximum,
                    relief_m=evidence.relief_m,
                    valid_fraction=evidence.elevation.valid_fraction,
                    classification=assessment.classification,
                    score=assessment.score if evidence_available else None,
                    hard_feasible=assessment.hard_feasible,
                    evidence_ref=evidence.evidence_id,
                    reason_codes=reasons,
                    provenance=evidence.provenance,
                )
                terrain_diagnostic = _diagnostic(
                    self.policy,
                    factor="terrain",
                    status="available" if evidence_available else "invalid",
                    code=(
                        "TERRAIN_CANDIDATE_FEATURE_AVAILABLE"
                        if evidence_available
                        else "TERRAIN_CANDIDATE_FEATURE_INVALID"
                    ),
                    observed_count=evidence.elevation.total_cell_count,
                    usable_count=evidence.elevation.valid_cell_count,
                    evidence_refs=(evidence.evidence_id,),
                    details={
                        "evidence_status": evidence.status,
                        "classification": assessment.classification,
                    },
                )
                if not assessment.hard_feasible:
                    blocking_codes.extend(assessment.reasons or ("TERRAIN_NOT_HARD_FEASIBLE",))
        else:
            blocking_codes.append(terrain_diagnostic.code)
            if terrain_diagnostic.status == "invalid":
                terrain_feature = terrain_feature.model_copy(
                    update={
                        "status": "invalid",
                        "reason_codes": (terrain_diagnostic.code,),
                    }
                )

        candidate_availability = [
            terrain_diagnostic if item.factor == "terrain" else item
            for item in candidate_availability
        ]
        blocking_codes.extend(
            item.code for item in candidate_availability if item.blocks_candidate
        )
        blocking_codes = list(dict.fromkeys(blocking_codes))
        evidence_refs = list(getattr(candidate, "evidence_refs", ()) or ())
        if terrain_feature.evidence_ref:
            evidence_refs.append(terrain_feature.evidence_ref)
        feature_payload = {
            "candidate_id": candidate_id,
            "target_id": target_id,
            "source_parcels": sorted(source_parcels),
            "policy_digest": self.policy.digest,
            "terrain_evidence_ref": terrain_feature.evidence_ref,
            "blocking_codes": blocking_codes,
        }
        feature_id = "suitability-feature-" + hashlib.sha256(
            json.dumps(feature_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        hard_feasible = (
            grounding_hard_feasible
            and terrain_feature.hard_feasible
            and not blocking_codes
        )
        return CandidateSuitabilityFeatures(
            feature_id=feature_id,
            candidate_id=candidate_id,
            target_id=target_id,
            source_parcels=source_parcels,
            geometry_source=geometry_source,
            geometry_crs=self.geometry_crs,
            policy_ref=self.policy.ref,
            policy_digest=self.policy.digest,
            terrain=terrain_feature,
            availability=tuple(candidate_availability),
            grounding_hard_feasible=grounding_hard_feasible,
            hard_feasible=hard_feasible,
            blocking_codes=tuple(blocking_codes),
            evidence_refs=tuple(dict.fromkeys(str(item) for item in evidence_refs)),
        )

    def build_candidates(
        self,
        candidates: Sequence[Any],
    ) -> tuple[CandidateSuitabilityFeatures, ...]:
        return tuple(self.build_candidate(candidate) for candidate in candidates)


__all__ = [
    "TerrainCandidateFeatureAdapter",
    "audit_suitability_evidence_availability",
]
