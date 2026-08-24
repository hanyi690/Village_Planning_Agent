"""L2 stage contracts — development strategy and conflicts."""

from __future__ import annotations

from pydantic import BaseModel

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from .l1_contracts import EvidenceGap
from app.contracts.workflow.parse_result_contracts import ParseDiagnostic
from app.contracts.workflow.parsing_contracts import CompilerTrace
from app.contracts.artifacts.provenance import Provenance


class StrategyConflict(BaseModel):
    description: str
    between: list[str] = []
    severity: str = "warning"


class StrategyIssue(BaseModel):
    """Strategy-level issue for the G2 gate (mirrors StageIssue)."""

    stage: str = "l2"
    severity: str = "warning"  # "info" | "warning" | "error"
    code: str = ""
    message: str = ""
    detail: str = ""


class L2StrategyFragment(BaseModel):
    """Per-dimension compiled output of the L2_STRATEGY profile."""

    dimension_key: str
    goals: list[str] = []
    strategies: list[str] = []
    priorities: list[str] = []
    conflicts: list[StrategyConflict] = []
    evidence_gaps: list[EvidenceGap] = []
    strategy_issues: list[StrategyIssue] = []
    spatial_structure: str = ""
    diagnostics: list[ParseDiagnostic] = []
    provenance: "Provenance | None" = None
    trace: "CompilerTrace | None" = None


class L2Strategy(ContractMeta):
    development_goals: list[str] = []
    spatial_structure: str = ""
    implementation_priorities: list[str] = []
    strategy_conflicts: list[StrategyConflict] = []
    evidence_refs: list[str] = []
    # Wave D enrichment
    evidence_gaps: list[EvidenceGap] = []
    sources: list[EvidenceSource] = []
    strategy_issues: list[StrategyIssue] = []
    dimension_provenance: list[Provenance] = []
    provenance: "Provenance | None" = None
    evidence_requirements: list[EvidenceRequirement] = []


__all__ = [
    "StrategyConflict",
    "StrategyIssue",
    "L2StrategyFragment",
    "L2Strategy",
]
