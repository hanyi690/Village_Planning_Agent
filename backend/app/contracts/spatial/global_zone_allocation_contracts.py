"""Canonical contracts for exclusive global zone-to-parcel allocation.

The contracts deliberately separate authoritative land-use assignments from
non-exclusive protection/restoration overlays.  They carry only bundle parcel
references; geometry remains owned by the VillageBundle.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.workflow.parse_contracts import ZoneTarget


AllocationStatus = Literal[
    "OPTIMAL",
    "PARTIAL",
    "INFEASIBLE",
    "MODEL_INVALID",
    "SOLVER_UNAVAILABLE",
    "SOLVER_ERROR",
]
DiagnosticSeverity = Literal["info", "warning", "error"]
OverlayRole = Literal[
    "functional_overlay",
    "protection_overlay",
    "restoration_overlay",
]


class ParcelConstraint(BaseModel):
    """One audited constraint attached to an existing parcel.

    ``blocked_target_ids`` narrows a constraint to specific targets.  An empty
    list means the constraint applies to every land-use assignment target.
    The allocator never infers behavior from ``code`` text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1)
    blocks_land_use_assignment: bool = True
    blocked_target_ids: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(min_length=1)


class ZoneParcelFact(BaseModel):
    """Current-state parcel facts required by the allocator."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bsm: str = Field(min_length=1)
    area_ha: float = Field(gt=0)
    geometry_ref: str = Field(min_length=1)
    provenance_refs: list[str] = Field(min_length=1)
    constraints: list[ParcelConstraint] = Field(default_factory=list)


class ZoneParcelCandidate(BaseModel):
    """Target-bound suitability evidence for one bundle parcel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bsm: str = Field(min_length=1)
    suitability_score: float = Field(ge=0.0, le=1.0)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    hard_feasible: bool = True
    exclusion_codes: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(min_length=1)


class ZoneCandidateSet(BaseModel):
    """All suitability candidates for one stable ZoneTarget."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str = Field(min_length=1)
    candidates: list[ZoneParcelCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_bsms(self) -> "ZoneCandidateSet":
        bsms = [candidate.bsm for candidate in self.candidates]
        if len(bsms) != len(set(bsms)):
            raise ValueError(f"duplicate candidate BSMs for target {self.target_id}")
        return self


class ZoneOverlayTargetRef(BaseModel):
    """Pass-through non-exclusive overlay; never enters parcel ownership MIP."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str = Field(min_length=1)
    materialization_role: OverlayRole
    candidate_bsms: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(min_length=1)


class GlobalZoneAllocationProblem(BaseModel):
    """Typed global allocation input assembled after GROUND/Suitability."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    targets: list[ZoneTarget] = Field(default_factory=list)
    candidate_sets: list[ZoneCandidateSet] = Field(default_factory=list)
    parcels: list[ZoneParcelFact] = Field(default_factory=list)
    overlay_targets: list[ZoneOverlayTargetRef] = Field(default_factory=list)
    area_tolerance_ratio: float = Field(default=0.05, ge=0.0, le=0.5)
    provenance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stable_identity(self) -> "GlobalZoneAllocationProblem":
        target_ids = [target.target_id for target in self.targets]
        if any(not target_id for target_id in target_ids):
            raise ValueError("every zone target requires a stable target_id")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("duplicate zone target_id")

        candidate_ids = [item.target_id for item in self.candidate_sets]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("duplicate candidate set target_id")

        parcel_ids = [parcel.bsm for parcel in self.parcels]
        if len(parcel_ids) != len(set(parcel_ids)):
            raise ValueError("duplicate parcel facts for one BSM")

        overlay_ids = [overlay.target_id for overlay in self.overlay_targets]
        if len(overlay_ids) != len(set(overlay_ids)):
            raise ValueError("duplicate overlay target_id")
        if set(target_ids) & set(overlay_ids):
            raise ValueError("exclusive zone and overlay target IDs must be disjoint")
        return self


class ZoneAssignmentLineage(BaseModel):
    """Deterministic target/candidate/parcel lineage for one assignment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lineage_id: str
    target_id: str
    zone_id: str
    source_instruction_id: str = ""
    source_report_key: str = ""
    claim_refs: list[str] = Field(default_factory=list)
    classification_evidence_refs: list[str] = Field(default_factory=list)
    candidate_provenance_refs: list[str] = Field(default_factory=list)
    parcel_provenance_refs: list[str] = Field(default_factory=list)
    geometry_ref: str
    constraint_codes_considered: list[str] = Field(default_factory=list)
    allocator_version: Literal["global-zone-v1"] = "global-zone-v1"


class AuthoritativeZoneParcelAssignment(BaseModel):
    """The sole authoritative land-use assignment for one parcel BSM."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str
    zone_id: str
    bsm: str
    materialization_role: Literal["land_use_assignment"] = "land_use_assignment"
    land_use: str
    classification_system: str
    classification_code: str
    area_ha: float
    suitability_score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    lineage: ZoneAssignmentLineage


class ZoneAreaBalance(BaseModel):
    """Audited area demand and residual for one target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str
    zone_id: str
    requested_area_ha: float
    assigned_area_ha: float
    shortfall_area_ha: float
    excess_area_ha: float
    tolerance_area_ha: float
    fulfillment_ratio: float
    within_tolerance: bool


class ZoneAllocationDiagnostic(BaseModel):
    """Machine-routable allocation diagnostic, never an untyped message string."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: DiagnosticSeverity
    message: str
    target_id: str = ""
    bsm: str = ""
    related_target_ids: list[str] = Field(default_factory=list)
    constraint_codes: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class GlobalZoneAllocationResult(BaseModel):
    """Deterministic, auditable result of one global parcel allocation solve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: AllocationStatus
    feasible: bool = False
    complete: bool = False
    assignments: list[AuthoritativeZoneParcelAssignment] = Field(default_factory=list)
    area_balances: list[ZoneAreaBalance] = Field(default_factory=list)
    unassigned_bsms: list[str] = Field(default_factory=list)
    overlay_targets: list[ZoneOverlayTargetRef] = Field(default_factory=list)
    objective_value: float = 0.0
    diagnostics: list[ZoneAllocationDiagnostic] = Field(default_factory=list)
    input_provenance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_exclusive_assignments(self) -> "GlobalZoneAllocationResult":
        bsms = [assignment.bsm for assignment in self.assignments]
        if len(bsms) != len(set(bsms)):
            raise ValueError("a parcel BSM may have at most one authoritative land-use assignment")
        if any(
            assignment.materialization_role != "land_use_assignment"
            for assignment in self.assignments
        ):
            raise ValueError("overlay targets cannot enter authoritative assignments")
        return self


__all__ = [
    "AllocationStatus",
    "AuthoritativeZoneParcelAssignment",
    "GlobalZoneAllocationProblem",
    "GlobalZoneAllocationResult",
    "ParcelConstraint",
    "ZoneAllocationDiagnostic",
    "ZoneAreaBalance",
    "ZoneAssignmentLineage",
    "ZoneCandidateSet",
    "ZoneOverlayTargetRef",
    "ZoneParcelCandidate",
    "ZoneParcelFact",
]
