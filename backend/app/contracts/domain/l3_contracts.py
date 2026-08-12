"""L3 stage contracts — interventions, dependencies, and the planning program."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.classification_ref import ClassificationDecision
from app.contracts.evidence.evidence_contracts import EvidenceSource
from .l1_contracts import EvidenceGap
from app.contracts.workflow.parse_result_contracts import ParseDiagnostic
from app.contracts.workflow.parsing_contracts import CompilerTrace
from app.contracts.artifacts.provenance import Provenance
from app.contracts.program import PlanningClaim, ProgramProposal


class PlanningIntervention(BaseModel):
    intervention_id: str
    name: str
    target_id: str = ""
    execution_mode: Literal["spatial", "non_spatial"]
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"]
    category: Literal[
        "project",
        "facility",
        "road",
        "axis",
        "restoration",
        "protection",
        "zone",
    ]
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
    # A formal target classification must be selected in its own namespace.
    # Human-readable ``name``/``functions`` remain semantic context only.
    classification_decision: ClassificationDecision | None = None
    derives_from_strategy: str | None = None

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
            "project": {"parcel", "polygon", "point", "action"},
        }
        if self.expected_output_kind not in expected_by_category[self.category]:
            raise ValueError(
                f"category={self.category} cannot produce "
                f"expected_output_kind={self.expected_output_kind}"
            )
        return self


class InterventionDependency(BaseModel):
    from_intervention_id: str
    to_intervention_id: str
    dependency_type: str = ""


class ProgramIssue(BaseModel):
    """Program-level issue for the G3 gate (mirrors StageIssue)."""

    stage: str = "l3"
    dimension_key: str = ""
    severity: str = "warning"  # "info" | "warning" | "error"
    code: str = ""
    message: str = ""
    detail: str = ""


class L3ProgramFragment(BaseModel):
    """Per-dimension proposal output of the L3 planning profile.

    This is deliberately not an executable ``PlanningProgram``.  The domain
    program assembler is the only boundary that creates that authoritative
    contract.
    """

    dimension_key: str
    claims: list[PlanningClaim] = Field(default_factory=list)
    proposals: list[ProgramProposal] = Field(default_factory=list)
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

__all__ = [
    "PlanningIntervention",
    "InterventionDependency",
    "ProgramIssue",
    "L3ProgramFragment",
    "PlanningProgram",
]
