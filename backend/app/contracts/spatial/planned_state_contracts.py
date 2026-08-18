from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance


class PlannedParcel(BaseModel):
    bsm: str = ""
    # Relation-aware candidates are immutable geometries, not cadastral BSMs.
    # Keep the two identities separate so legacy parcel consumers cannot
    # accidentally resolve a candidate through the current-land-use index.
    candidate_id: str = ""
    project_ref: str = ""
    planning_land_use: str = ""
    zone_type: str = ""
    area_ha: float = 0.0
    geometry: str = ""  # WKT
    derived_from_bsms: list[str] = Field(default_factory=list)
    derived_from_zone_target: str = ""
    source_spec: str = ""
    decided_by: str = ""
    operation: str = ""
    area_change_ha: float = 0.0
    target_ref: str = ""
    lineage_id: str = ""
    claim_refs: list[str] = Field(default_factory=list)
    source_instruction_id: str = ""
    source_report_key: str = ""
    geometry_ref: str = ""
    classification_system: str = ""
    classification_code: str = ""
    scenario_id: str = ""
    feature_id: str = ""
    materialization_role: str = ""
    source_refs: list[str] = Field(default_factory=list)


class PlannedZone(BaseModel):
    zone_id: str = ""
    zone_type: str = ""
    planning_land_use: str = ""
    classification_system: str = ""
    classification_code: str = ""
    area_ha: float = 0.0
    name: str = ""
    geometry: str = ""
    derived_from_zone_target: str = ""
    target_ref: str = ""
    project_ref: str = ""
    parcel_bsms: list[str] = Field(default_factory=list)
    lineage_ids: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    materialization_role: Literal["land_use_assignment"] = "land_use_assignment"


class PlannedZoneOverlay(BaseModel):
    """Non-exclusive functional/protection/restoration spatial overlay."""

    overlay_id: str = ""
    materialization_role: Literal[
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
    ]
    name: str = ""
    geometry: str = ""
    target_ref: str = ""
    project_ref: str = ""
    derived_from_bsms: list[str] = Field(default_factory=list)
    lineage_refs: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    candidate_id: str = ""
    scenario_id: str = ""
    feature_id: str = ""
    lineage_id: str = ""


class CoverageDomain(BaseModel):
    """Explicit boundary whose declared zones must form a partition/coverage."""

    domain_id: str
    domain_type: Literal["partition", "coverage"] = "partition"
    boundary_geometry: str
    zone_refs: list[str] = Field(default_factory=list)


class PlannedFacility(BaseModel):
    name: str = ""
    facility_type: str = ""
    lon: float = 0.0
    lat: float = 0.0
    service_radius: float = 0.0
    geometry: str = ""
    derived_from_target: str = ""
    scenario_id: str = ""
    candidate_id: str = ""
    feature_id: str = ""
    lineage_id: str = ""
    relation_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_bsms: list[str] = Field(default_factory=list)
    geometry_ref: str = ""


class PlannedRoad(BaseModel):
    name: str = ""
    road_level: str = ""
    width_m: float = 0.0
    geometry: str = ""
    derived_from_target: str = ""
    scenario_id: str = ""
    candidate_id: str = ""
    feature_id: str = ""
    lineage_id: str = ""
    relation_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class PlannedAxis(BaseModel):
    name: str = ""
    reference_feature: str = ""
    direction: str = ""
    geometry: str = ""
    derived_from_target: str = ""
    scenario_id: str = ""
    candidate_id: str = ""
    feature_id: str = ""
    lineage_id: str = ""
    relation_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class PlannedProjectPoint(BaseModel):
    """Legacy delivery marker retained for old artifacts.

    New canonical planning never produces this object: point semantics belong
    to ``PlannedFacility``. Keeping the reader field allows older delivery
    snapshots to be rendered while preventing new project targets from using
    it.
    """

    project_ref: str = ""
    name: str = ""
    geometry: str = ""


class PlannedState(ContractMeta):
    version: str = "v1"
    parcels: list[PlannedParcel] = Field(default_factory=list)
    zones: list[PlannedZone] = Field(default_factory=list)
    overlays: list[PlannedZoneOverlay] = Field(default_factory=list)
    coverage_domains: list[CoverageDomain] = Field(default_factory=list)
    facilities: list[PlannedFacility] = Field(default_factory=list)
    # Backward-compatible reader field; new EXECUTE writes facility points.
    project_points: list[PlannedProjectPoint] = Field(default_factory=list)
    roads: list[PlannedRoad] = Field(default_factory=list)
    axes: list[PlannedAxis] = Field(default_factory=list)
    source: str = ""
    provenance: "Provenance | None" = None
    scenario_id: str = ""
    scenario_ref: str = ""
    execution_trace_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_authoritative_zone_ownership(self) -> "PlannedState":
        parcel_bsms = [parcel.bsm for parcel in self.parcels if parcel.bsm]
        if len(parcel_bsms) != len(set(parcel_bsms)):
            raise ValueError("duplicate PlannedParcel BSM in authoritative PlannedState")

        owner_by_bsm: dict[str, str] = {}
        for zone in self.zones:
            owner = zone.zone_id or zone.target_ref or zone.derived_from_zone_target
            for bsm in zone.parcel_bsms:
                previous = owner_by_bsm.get(bsm)
                if previous is not None:
                    raise ValueError(
                        "parcel belongs to multiple authoritative PlannedZone entries"
                    )
                owner_by_bsm[bsm] = owner
        return self
