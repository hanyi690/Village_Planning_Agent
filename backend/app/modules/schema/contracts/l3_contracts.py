"""L3 stage contracts — interventions, dependencies, and the planning program."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .contract_meta import ContractMeta
from .classification_ref import ClassificationDecision
from .evidence_contracts import EvidenceSource
from .l1_contracts import EvidenceGap
from .parse_result_contracts import ParseDiagnostic
from .parsing_contracts import CompilerTrace
from .provenance import Provenance


class PlanningIntervention(BaseModel):
    intervention_id: str
    name: str
    target_id: str = ""
    execution_mode: Literal["spatial", "non_spatial"] = "spatial"
    expected_output_kind: Literal["parcel", "polygon", "point", "line", "action"] = "parcel"
    category: Literal["project", "facility", "road", "restoration", "protection", "zone"] = "project"
    problem_addressed: str = ""
    scale: str = ""
    area_range_ha: tuple[float, float] | None = None
    functions: list[str] = Field(default_factory=list)
    service_population: str | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    spatial_requirements: dict = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
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
            self.expected_output_kind = "action"
        elif self.expected_output_kind == "action":
            raise ValueError("spatial interventions cannot declare action output")
        elif self.expected_output_kind == "parcel":
            self.expected_output_kind = {
                "facility": "point",
                "road": "line",
                "restoration": "polygon",
                "protection": "polygon",
                "zone": "polygon",
            }.get(self.category, "parcel")
        return self


class InterventionDependency(BaseModel):
    from_intervention_id: str
    to_intervention_id: str
    dependency_type: str = ""


class ProgramIssue(BaseModel):
    """Program-level issue for the G3 gate (mirrors StageIssue)."""

    stage: str = "l3"
    severity: str = "warning"  # "info" | "warning" | "error"
    code: str = ""
    message: str = ""
    detail: str = ""


class L3ProgramFragment(BaseModel):
    """Per-dimension compiled output of the L3_PLANNING profile."""

    dimension_key: str
    interventions: list[PlanningIntervention] = []
    dependencies: list[InterventionDependency] = []
    evidence_gaps: list[EvidenceGap] = []
    program_issues: list[ProgramIssue] = []
    omissions: list[str] = []
    diagnostics: list[ParseDiagnostic] = []
    provenance: "Provenance | None" = None
    trace: "CompilerTrace | None" = None


class PlanningProgram(ContractMeta):
    schema_version: Literal["2.0"] = "2.0"
    interventions: list[PlanningIntervention] = []
    dependencies: list[InterventionDependency] = []
    omissions: list[str] = []
    # Wave E enrichment
    evidence_gaps: list[EvidenceGap] = []
    sources: list[EvidenceSource] = []
    program_issues: list[ProgramIssue] = []
    dimension_provenance: list[Provenance] = []
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
