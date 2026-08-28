"""L3 stage contracts — interventions, dependencies, and the planning program."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
            if self.asset_kind == "road":
                if self.road_parameters is None or self.linear_parameters is not None:
                    raise ValueError("road asset_kind requires only road_parameters")
            elif self.linear_parameters is None or self.road_parameters is not None:
                raise ValueError("non-road linear assets require only linear_parameters")
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

__all__ = [
    "RoadPlanningParameters",
    "PlanningIntervention",
    "InterventionDependency",
    "ProgramIssue",
    "ClaimDisposition",
    "L3ProgramFragment",
    "PlanningProgram",
]
