from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance


class ParcelChange(BaseModel):
    bsm: str
    action: str = "modify"  # "preserve"|"reclassify"|"modify"|"split"|"merge"|"create"
    derived_from_bsms: list[str] = Field(default_factory=list)
    before_classification: ClassificationRef | None = None
    after_classification: ClassificationRef | None = None
    before_geometry_wkt: str = ""
    after_geometry_wkt: str = ""
    new_area_ha: float = 0.0
    source_area_ha: float = 0.0
    coverage_ratio: float | None = None
    availability_status: Literal[
        "fully_available",
        "partially_available",
        "fully_unavailable",
        "unknown",
    ] = "unknown"
    eligible_area_ha: float | None = Field(default=None, ge=0)
    excluded_area_ha: float | None = Field(default=None, ge=0)
    # Adjacent parcels are execution context, not an implicit merge request.
    # A later typed relation/worker may explicitly consume them; EXECUTE must
    # preserve the references without silently mutating those parcels.
    adjacent_parcel_bsms: list[str] = Field(default_factory=list)
    adjacency_evidence_refs: list[str] = Field(default_factory=list)
    project_ref: str | None = None
    intervention_id: str | None = None
    # Frozen SELECT identity carried through EXECUTE into PlannedState.  These
    # fields keep final relation validation bound to the approved candidate;
    # source-parcel changes may leave candidate identity empty.
    candidate_id: str = ""
    feature_id: str = ""
    target_id: str = ""
    scenario_id: str = ""
    feature_bsms: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""

    @model_validator(mode="after")
    def validate_availability_semantics(self) -> "ParcelChange":
        """Prevent EXECUTE from reviving prohibited area or losing the split."""
        tolerance = 1e-9
        source = float(self.source_area_ha or 0.0)
        if source > tolerance:
            if self.eligible_area_ha is not None and float(self.eligible_area_ha) > source + tolerance:
                raise ValueError("eligible_area_ha cannot exceed source_area_ha")
            if self.excluded_area_ha is not None and float(self.excluded_area_ha) > source + tolerance:
                raise ValueError("excluded_area_ha cannot exceed source_area_ha")
        if self.availability_status == "fully_unavailable" and self.new_area_ha > tolerance:
            raise ValueError("fully_unavailable parcel change cannot create geometry")
        if (
            self.availability_status == "partially_available"
            and self.eligible_area_ha is not None
            and float(self.eligible_area_ha) <= tolerance
            and self.new_area_ha > tolerance
        ):
            raise ValueError("partially_available parcel change requires positive eligible area")
        if self.availability_status == "fully_available" and (
            self.excluded_area_ha is not None and float(self.excluded_area_ha) > tolerance
        ):
            raise ValueError("fully_available parcel change cannot carry excluded area")
        return self


class FacilityChange(BaseModel):
    name: str
    action: str = "create"
    facility_type: str = ""
    area_sqm: float = 0.0
    center: tuple[float, float] | None = None
    derived_from_name: str = ""
    feature_bsms: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""


class RoadChange(BaseModel):
    name: str
    action: str = "create"
    road_level: str = ""
    width_m: float = 0.0
    path: list[list[float]] = Field(default_factory=list)
    derived_from_name: str = ""
    feature_bsms: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    relation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    bundle_snapshot_digest: str = ""


class SettlementChange(BaseModel):
    settlement_name: str
    action: str = "modify"
    new_population: float = 0.0
    new_area_ha: float = 0.0
    target_location: tuple[float, float] | None = None
    merge_into: str = ""


class ParcelChangeSet(ContractMeta):
    changes: list[ParcelChange] = Field(default_factory=list)
    area_conservation_verified: bool = False
    geometry_validity_verified: bool = False
    provenance: "Provenance | None" = None
