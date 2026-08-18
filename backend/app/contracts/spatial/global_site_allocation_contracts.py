"""Typed contracts for one-shot non-zone site allocation in SELECT.

Only target-bound suitability evidence may enter this contract.  Geometry is
owned by the VillageBundle; assignments carry stable BSM and evidence refs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SiteTargetType = Literal["site_area", "facility"]
SiteOutputKind = Literal["parcel", "polygon", "point"]
SiteAllocationStatus = Literal[
    "OPTIMAL",
    "PARTIAL",
    "INFEASIBLE",
    "MODEL_INVALID",
    "SOLVER_UNAVAILABLE",
    "SOLVER_ERROR",
]


class SiteTargetDemand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str = Field(min_length=1)
    target_type: SiteTargetType
    expected_output_kind: SiteOutputKind
    required_area_m2: float = Field(ge=0.0)
    priority: int = Field(default=50, ge=1, le=100)
    priority_source: str = "equal_default"
    exclusive_bsm: bool = False
    target_binding: dict[str, Any] = Field(default_factory=dict)
    provenance_refs: list[str] = Field(default_factory=list)


class SiteParcelCapacity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bsm: str = Field(min_length=1)
    capacity_area_m2: float = Field(gt=0.0)
    geometry_ref: str = Field(min_length=1)
    provenance_refs: list[str] = Field(min_length=1)


class SiteCandidateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str = Field(min_length=1)
    bsm: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    anchor_point: tuple[float, float]
    suitability_score: float = Field(ge=0.0, le=1.0)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    hard_feasible: bool = False
    exclusion_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    availability_diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class GlobalSiteAllocationProblem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    targets: list[SiteTargetDemand] = Field(default_factory=list)
    candidates: list[SiteCandidateEvidence] = Field(default_factory=list)
    parcels: list[SiteParcelCapacity] = Field(default_factory=list)
    required_score_factors: tuple[str, ...] = (
        "slope_hazard",
        "hazard_safety",
        "road_access",
        "service_coverage",
    )
    provenance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_stable_identity(self) -> "GlobalSiteAllocationProblem":
        target_ids = [item.target_id for item in self.targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("duplicate non-zone target_id")
        parcel_ids = [item.bsm for item in self.parcels]
        if len(parcel_ids) != len(set(parcel_ids)):
            raise ValueError("duplicate parcel capacity BSM")
        candidate_keys = [(item.target_id, item.bsm) for item in self.candidates]
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("duplicate target/BSM site candidate")
        return self


class SiteAllocationLineage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lineage_id: str
    allocator_version: Literal["global-site-v1"] = "global-site-v1"
    target_id: str
    candidate_id: str
    bsm: str
    target_provenance_refs: list[str] = Field(default_factory=list)
    candidate_evidence_refs: list[str] = Field(default_factory=list)
    parcel_provenance_refs: list[str] = Field(default_factory=list)
    geometry_ref: str


class GlobalSiteAssignment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_id: str
    target_type: SiteTargetType
    expected_output_kind: SiteOutputKind
    status: Literal["assigned", "unplaced"]
    bsm: str = ""
    anchor_point: tuple[float, float] | None = None
    consumed_area_m2: float = Field(default=0.0, ge=0.0)
    parcel_capacity_area_m2: float = Field(default=0.0, ge=0.0)
    priority: int = Field(default=50, ge=1, le=100)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    reason: str = ""
    target_binding: dict[str, Any] = Field(default_factory=dict)
    lineage: SiteAllocationLineage | None = None


class SiteAllocationDiagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    target_id: str = ""
    bsm: str = ""
    related_target_ids: list[str] = Field(default_factory=list)
    missing_factors: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class GlobalSiteAllocationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    status: SiteAllocationStatus
    feasible: bool = False
    complete: bool = False
    assignments: list[GlobalSiteAssignment] = Field(default_factory=list)
    objective_value: float = 0.0
    diagnostics: list[SiteAllocationDiagnostic] = Field(default_factory=list)
    input_provenance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capacity_and_exclusivity(self) -> "GlobalSiteAllocationResult":
        assigned = [item for item in self.assignments if item.status == "assigned"]
        by_bsm: dict[str, list[GlobalSiteAssignment]] = {}
        for item in assigned:
            by_bsm.setdefault(item.bsm, []).append(item)
        for bsm, rows in by_bsm.items():
            capacities = {round(item.parcel_capacity_area_m2, 6) for item in rows}
            if len(capacities) != 1:
                raise ValueError(f"inconsistent parcel capacity for {bsm}")
            if sum(item.consumed_area_m2 for item in rows) > next(iter(capacities)) + 1e-6:
                raise ValueError(f"site assignments exceed parcel capacity for {bsm}")
            exclusive = [
                item
                for item in rows
                if bool(item.target_binding.get("allocation_exclusive_bsm"))
            ]
            if exclusive and len(rows) > 1:
                raise ValueError(f"exclusive target shares parcel {bsm}")
        return self


__all__ = [
    "GlobalSiteAllocationProblem",
    "GlobalSiteAllocationResult",
    "GlobalSiteAssignment",
    "SiteAllocationDiagnostic",
    "SiteAllocationLineage",
    "SiteCandidateEvidence",
    "SiteParcelCapacity",
    "SiteTargetDemand",
]
