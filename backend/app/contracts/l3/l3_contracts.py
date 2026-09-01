"""L3 stage contracts — interventions, dependencies, and the planning program."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.classification_ref import ClassificationDecision
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.l1.l1_contracts import EvidenceGap
from app.contracts.target_projection.parse_result_contracts import ParseDiagnostic
from app.contracts.target_projection.parsing_contracts import CompilerTrace
from app.contracts.artifacts.provenance import Provenance
from app.contracts.l3.program import PlanningClaim, PlanningRole
from app.contracts.l2.planning_semantics import (
    AssetKind,
    AxisPlanningParameters,
    FacilityPlanningParameters,
    LinearAssetPlanningParameters,
    PolygonPlanningParameters,
    SiteAreaPlanningParameters,
    RoadPlanningParameters,
    LINEAR_ASSET_KINDS,
)


RepresentationPurpose = Literal[
    "point_location",
    "service_area",
    "centerline",
    "corridor",
    "site_footprint",
    "land_use_assignment",
    "functional_overlay",
    "protection_overlay",
    "restoration_overlay",
]
RepresentationType = Literal[
    "point",
    "line",
    "polygon",
    "parcel_set",
    "network_path",
    "service_area",
]


class L3TargetRow(BaseModel):
    """Flat semantic target produced by L3; never a world/entity binding."""

    model_config = ConfigDict(extra="forbid")

    target_ref: str = Field(min_length=1)
    claim_family: str = Field(min_length=1)
    subject_ref: str = ""
    subject_text: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    representation_purpose: RepresentationPurpose
    required_capabilities: list[str] = Field(default_factory=list, max_length=12)
    constraint_refs: list[str] = Field(default_factory=list, max_length=16)
    l2_refs: list[str] = Field(default_factory=list, min_length=1, max_length=24)
    evidence_refs: list[str] = Field(default_factory=list, max_length=24)
    source_fact_refs: list[str] = Field(default_factory=list, max_length=24)
    candidate_request_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lineage(self) -> "L3TargetRow":
        if not (self.evidence_refs or self.source_fact_refs):
            raise ValueError("L3 target requires evidence or source-fact lineage")
        for field_name in (
            "required_capabilities",
            "constraint_refs",
            "l2_refs",
            "evidence_refs",
            "source_fact_refs",
        ):
            values = getattr(self, field_name)
            setattr(self, field_name, list(dict.fromkeys(v for v in values if v)))
        return self


class L3SpatialRequirementRow(BaseModel):
    """Flat representation request; it deliberately cannot carry geometry."""

    model_config = ConfigDict(extra="forbid")

    requirement_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    representation_type: RepresentationType
    representation_purpose: RepresentationPurpose
    operation: str = Field(min_length=1)
    location_hints: list[str] = Field(default_factory=list, max_length=8)
    grounding_requirements: list[str] = Field(default_factory=list, max_length=12)
    required_capabilities: list[str] = Field(default_factory=list, max_length=12)
    l2_refs: list[str] = Field(default_factory=list, min_length=1, max_length=24)
    evidence_refs: list[str] = Field(default_factory=list, max_length=24)


class L3CandidateRequestRow(BaseModel):
    """Flat request for GROUND to build a candidate domain, not a candidate."""

    model_config = ConfigDict(extra="forbid")

    request_ref: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    entity_type_requirements: list[str] = Field(default_factory=list, max_length=8)
    representation_type_requirements: list[RepresentationType] = Field(
        default_factory=list,
        min_length=1,
        max_length=4,
    )
    representation_purpose: RepresentationPurpose
    operation: str = Field(min_length=1)
    query_terms: list[str] = Field(default_factory=list, max_length=8)
    location_hints: list[str] = Field(default_factory=list, max_length=8)
    constraint_refs: list[str] = Field(default_factory=list, max_length=16)
    l2_refs: list[str] = Field(default_factory=list, min_length=1, max_length=24)
    evidence_refs: list[str] = Field(default_factory=list, max_length=24)
    route_to: Literal["ground"] = "ground"
    status: Literal["ready", "pending_location_evidence"] = "ready"


class PlanningIntervention(BaseModel):
    intervention_id: str
    name: str
    target_id: str = ""
    planning_role: PlanningRole = "evidence_statement"
    project_package_ref: str = ""
    variant_key: str = ""
    admission_reason: str = ""
    execution_mode: Literal["spatial", "non_spatial"]
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"]
    category: Literal[
        "site_area",
        "facility",
        "road",
        "axis",
        "restoration",
        "protection",
        "zone",
    ]
    asset_kind: AssetKind = "none"
    problem_addressed: str = ""
    scale: str = ""
    area_range_ha: tuple[float, float] | None = None
    functions: list[str] = Field(default_factory=list)
    service_population: str | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    spatial_requirements: dict = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    objective_refs: list[str] = Field(default_factory=list)
    # A formal target classification must be selected in its own namespace.
    # Human-readable ``name``/``functions`` remain semantic context only.
    classification_decision: ClassificationDecision | None = None
    derives_from_strategy: str | None = None
    intervention_action: Literal[
        "preserve",
        "new",
        "expand",
        "relocate",
        "upgrade",
        "widen",
        "harden",
        "repair",
        "demolish",
    ] = "new"
    materialization_role: Literal[
        "land_use_assignment",
        "functional_overlay",
        "protection_overlay",
        "restoration_overlay",
        "site_footprint",
    ] | None = None
    road_parameters: RoadPlanningParameters | None = None
    linear_parameters: LinearAssetPlanningParameters | None = None
    facility_parameters: FacilityPlanningParameters | None = None
    axis_parameters: AxisPlanningParameters | None = None
    polygon_parameters: PolygonPlanningParameters | None = None
    site_area_parameters: SiteAreaPlanningParameters | None = None

    @model_validator(mode="after")
    def validate_target_contract(self) -> "PlanningIntervention":
        if not self.target_id:
            self.target_id = self.intervention_id
        if self.execution_mode == "non_spatial":
            if self.expected_output_kind != "action":
                raise ValueError("non-spatial interventions must declare action output")
        elif self.expected_output_kind == "action":
            raise ValueError("spatial interventions cannot declare action output")
        expected_by_category = {
            "facility": {"point"},
            "road": {"line"},
            "axis": {"line"},
            "restoration": {"polygon"},
            "protection": {"polygon"},
            "zone": {"polygon"},
            "site_area": {"parcel", "polygon"},
        }
        if self.expected_output_kind not in expected_by_category[self.category]:
            raise ValueError(
                f"category={self.category} cannot produce "
                f"expected_output_kind={self.expected_output_kind}"
            )
        allowed_assets = {
            "facility": {"none", "facility"},
            "site_area": {"none"},
            "road": set(LINEAR_ASSET_KINDS),
            "axis": {"none", "axis"},
            "restoration": {"none"},
            "protection": {"none"},
            "zone": {"none", "land_use"},
        }
        if self.asset_kind not in allowed_assets[self.category]:
            raise ValueError(
                f"asset_kind={self.asset_kind} is incompatible with "
                f"category={self.category}"
            )
        if self.expected_output_kind == "line" and self.category == "road":
            if self.asset_kind == "none":
                raise ValueError("line interventions require an explicit asset_kind")
            if self.asset_kind == "road" and self.linear_parameters is not None:
                raise ValueError("road asset_kind cannot use linear_parameters")
            if self.asset_kind != "road" and self.road_parameters is not None:
                raise ValueError("non-road linear assets cannot use road_parameters")
        elif self.asset_kind not in {"none", "facility", "land_use", "axis"}:
            raise ValueError("linear asset_kind requires line output")
        return self


class InterventionDependency(BaseModel):
    from_intervention_id: str
    to_intervention_id: str
    dependency_type: str = ""


class ProgramIssue(BaseModel):
    """Program-level issue for the G3 gate (mirrors StageIssue)."""

    stage: str = "l3"
    dimension_key: str = ""
    claim_id: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    dimension_keys: list[str] = Field(default_factory=list)
    severity: str = "warning"  # "info" | "warning" | "error"
    code: str = ""
    message: str = ""
    detail: str = ""
    reason: str = ""
    root_issue_id: str = ""
    failure_scope: Literal[
        "field",
        "relation",
        "claim",
        "project_package",
        "program",
    ] = "program"
    dependency_scope: list[str] = Field(default_factory=list)


class ClaimDisposition(BaseModel):
    """Auditable L3 accounting result for one source planning claim."""

    claim_id: str
    dimension_key: str
    status: Literal[
        "admitted",
        "pending_grounding",
        "merged_duplicate",
        "deferred",
        "invalid",
    ]
    reason: str
    missing_requirements: list[str] = Field(default_factory=list)


class L3ProgramFragment(BaseModel):
    """Per-dimension intervention output of the L3 planning profile.

    This is deliberately not an executable ``PlanningProgram``.  The domain
    program assembler is the only boundary that creates that authoritative
    contract.
    """

    dimension_key: str
    claims: list[PlanningClaim] = Field(default_factory=list)
    interventions: list[PlanningIntervention] = Field(default_factory=list)
    dependencies: list[InterventionDependency] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    program_issues: list[ProgramIssue] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    diagnostics: list[ParseDiagnostic] = Field(default_factory=list)
    provenance: "Provenance | None" = None
    trace: "CompilerTrace | None" = None


class PlanningProgram(ContractMeta):
    schema_version: Literal["4.0"] = "4.0"
    interventions: list[PlanningIntervention] = Field(default_factory=list)
    claims: list[PlanningClaim] = Field(default_factory=list)
    pending_grounding_claims: list[PlanningClaim] = Field(default_factory=list)
    claim_dispositions: list[ClaimDisposition] = Field(default_factory=list)
    dependencies: list[InterventionDependency] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    # Wave E enrichment
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    program_issues: list[ProgramIssue] = Field(default_factory=list)
    dimension_provenance: list[Provenance] = Field(default_factory=list)
    provenance: "Provenance | None" = None
    l1_snapshot_ref: str = ""
    l2_strategy_ref: str = ""
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)
    target_rows: list[L3TargetRow] = Field(default_factory=list)
    spatial_requirement_rows: list[L3SpatialRequirementRow] = Field(default_factory=list)
    candidate_request_rows: list[L3CandidateRequestRow] = Field(default_factory=list)

__all__ = [
    "RoadPlanningParameters",
    "RepresentationPurpose",
    "RepresentationType",
    "L3TargetRow",
    "L3SpatialRequirementRow",
    "L3CandidateRequestRow",
    "PlanningIntervention",
    "InterventionDependency",
    "ProgramIssue",
    "ClaimDisposition",
    "L3ProgramFragment",
    "PlanningProgram",
]
