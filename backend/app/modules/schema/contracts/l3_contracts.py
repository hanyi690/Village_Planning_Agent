"""L3 stage contracts — interventions, dependencies, and the planning program."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .contract_meta import ContractMeta
from .evidence_contracts import EvidenceSource
from .l1_contracts import EvidenceGap
from .parse_result_contracts import ParseDiagnostic
from .parsing_contracts import CompilerTrace
from .provenance import Provenance


class PlanningIntervention(BaseModel):
    intervention_id: str
    name: str
    category: Literal["project", "facility", "road", "restoration", "protection", "zone"] = "project"
    problem_addressed: str = ""
    scale: str = ""
    area_range_ha: tuple[float, float] | None = None
    functions: list[str] = []
    service_population: str | None = None
    implementation_phase: Literal["short", "medium", "long"] = "short"
    spatial_requirements: dict = {}
    constraints: list[str] = []
    evidence_refs: list[str] = []
    derives_from_strategy: str | None = None


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