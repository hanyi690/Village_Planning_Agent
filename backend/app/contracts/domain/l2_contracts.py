"""Typed L2 planning decisions.

L2 is a semantic decision boundary, not a second text parser.  The model
returns these small value objects directly; the aggregate only merges and
projects them into the stage artifact used by L3.  No marker, heading or
keyword is interpreted as a planning decision here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from .l1_contracts import EvidenceGap
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


class PlanningObjective(BaseModel):
    """One typed objective or constraint proposed by an L2 dimension."""

    objective_id: str = ""
    statement: str = ""
    kind: Literal["goal", "constraint", "opportunity"] = "goal"
    status: Literal["observed", "proposed", "required"] = "proposed"
    scope: str = ""
    target_year: str = ""
    source_fact_refs: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    rationale: str = ""
    confidence: float | None = None


class TargetMetric(BaseModel):
    """A metric with explicit status; proposed values are not source facts."""

    metric_id: str = ""
    name: str = ""
    value: str | int | float | None = None
    unit: str = ""
    direction: Literal["increase", "decrease", "maintain", "range", "unknown"] = "unknown"
    status: Literal["observed", "proposed", "required"] = "proposed"
    baseline_ref: str = ""
    objective_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[str] = Field(default_factory=list)
    target_year: str = ""
    rationale: str = ""


class StrategyRule(BaseModel):
    """A typed strategy rule that can be traced to objectives and evidence."""

    strategy_id: str = ""
    statement: str = ""
    action: str = ""
    objective_refs: list[str] = Field(default_factory=list)
    target_refs: list[str] = Field(default_factory=list)
    strength: Literal["hard", "soft", "proposed"] = "proposed"
    scope: str = ""
    phase: str = ""
    prerequisite_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[str] = Field(default_factory=list)
    rationale: str = ""
    confidence: float | None = None


class PriorityDecision(BaseModel):
    """Explicit ordering decision; rank is advisory until scenario solving."""

    priority_id: str = ""
    rank: int | None = None
    strategy_refs: list[str] = Field(default_factory=list)
    statement: str = ""
    rationale: str = ""


class SpatialStructureIntent(BaseModel):
    """Non-geometric spatial structure intent passed to L3/GROUND."""

    structure_id: str = ""
    statement: str = ""
    scope: str = ""
    relation_kind: str = ""
    objective_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[str] = Field(default_factory=list)
    grounding_requirements: list[str] = Field(default_factory=list)


class ConflictHypothesis(BaseModel):
    """A model-declared conflict; no lexical conflict detector is used."""

    conflict_id: str = ""
    description: str = ""
    objective_refs: list[str] = Field(default_factory=list)
    strategy_refs: list[str] = Field(default_factory=list)
    severity: Literal["info", "warning", "error"] = "warning"
    resolution: str = ""


class L2EvidenceGap(BaseModel):
    """Typed missing prerequisite; IDs are normalized at the stage boundary."""

    gap_id: str = ""
    dimension: str = ""
    description: str = ""
    required_fact: str = ""
    severity: Literal["info", "warning", "error"] = "warning"


class L2DecisionSet(BaseModel):
    """Structured output for one L2 dimension."""

    schema_version: Literal["2.0"] = "2.0"
    dimension_key: str = ""
    objectives: list[PlanningObjective] = Field(default_factory=list)
    metrics: list[TargetMetric] = Field(default_factory=list)
    strategies: list[StrategyRule] = Field(default_factory=list)
    priorities: list[PriorityDecision] = Field(default_factory=list)
    spatial_structures: list[SpatialStructureIntent] = Field(default_factory=list)
    conflicts: list[ConflictHypothesis] = Field(default_factory=list)
    evidence_gaps: list[L2EvidenceGap] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class L2Strategy(ContractMeta):
    schema_version: str = "2.0"
    decision_sets: list[L2DecisionSet] = Field(default_factory=list)
    objectives: list[PlanningObjective] = Field(default_factory=list)
    metrics: list[TargetMetric] = Field(default_factory=list)
    strategy_rules: list[StrategyRule] = Field(default_factory=list)
    priority_decisions: list[PriorityDecision] = Field(default_factory=list)
    spatial_structure_intents: list[SpatialStructureIntent] = Field(default_factory=list)
    conflict_hypotheses: list[ConflictHypothesis] = Field(default_factory=list)
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
    "PlanningObjective",
    "TargetMetric",
    "StrategyRule",
    "PriorityDecision",
    "SpatialStructureIntent",
    "ConflictHypothesis",
    "L2EvidenceGap",
    "L2DecisionSet",
    "L2Strategy",
]
