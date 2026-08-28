"""Typed L2 planning decisions.

L2 is a semantic decision boundary, not a second text parser. The model
returns these small value objects directly; the aggregate only merges and
projects them into the stage artifact used by L3. No marker, heading or
keyword is interpreted as a planning decision here.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.functional_validators import AfterValidator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.contracts.json_container import decode_json_container

from app.contracts.l1.l1_contracts import EvidenceGap


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _nonempty_id(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        raise ValueError("id_must_be_nonempty")
    return text


def _confidence(value: Any) -> float | None:
    if value is None or _clean_text(value) == "":
        return None
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError("confidence_out_of_range")
    return numeric


def _l1_fact_ref(value: Any) -> str:
    text = _clean_text(value)
    if not text.startswith("l1:fact:"):
        raise ValueError("l1_fact_ref_namespace_invalid")
    return text


def _source_segment_ref(value: Any) -> str:
    text = _clean_text(value)
    if not text.startswith("l1:") or text.startswith("l1:fact:"):
        raise ValueError("source_segment_ref_namespace_invalid")
    return text


def _source_feature_ref(value: Any) -> str:
    text = _clean_text(value)
    allowed_prefixes = (
        "bundle://feature/",
        "bundle:annotations_current:",
        "bundle:roads_current:",
        "bundle:facilities_current:",
        "feature:",
        "source:",
        "poi:",
    )
    if not text.startswith(allowed_prefixes):
        raise ValueError("source_feature_ref_namespace_invalid")
    return text


L1FactRef = Annotated[str, AfterValidator(_l1_fact_ref)]
SourceSegmentRef = Annotated[str, AfterValidator(_source_segment_ref)]
SourceFeatureRef = Annotated[str, AfterValidator(_source_feature_ref)]

Severity = Literal["info", "warning", "error"]
ObjectiveKind = Literal["goal", "constraint", "opportunity"]
DecisionStatus = Literal["observed", "proposed", "required"]
MetricDirection = Literal["increase", "decrease", "maintain", "range", "unknown"]
StrategyStrength = Literal["hard", "soft", "proposed"]
CanonicalScope = Literal[
    "village",
    "subarea",
    "corridor",
    "heritage_zone",
    "ecology_zone",
    "hazard_zone",
    "settlement_cluster",
    "service_core",
    "farmland_zone",
    "network_axis",
]
CanonicalPhase = Literal["immediate", "near_term", "mid_term", "long_term", "ongoing"]
CanonicalStrategyAction = Literal[
    "protect",
    "restore",
    "develop",
    "upgrade",
    "manage",
    "guide",
    "connect",
    "activate",
    "risk_control",
    "evidence_bound_spatial_planning",
]
CanonicalRelationKind = Literal[
    "serve",
    "protect",
    "restore",
    "connect",
    "corridor",
    "cluster",
    "blue_axis",
    "core_protection",
    "cultural_corridor",
    "cultural_heritage_cluster",
    "ecological_axis",
    "settlement_guidance",
    "guide_settlement",
    "population_guidance",
    "service_network",
]
CanonicalGroundingRequirement = Literal[
    "candidate_geometry",
    "network_context",
    "network_snapshot",
    "place_binding",
    "demand_points",
    "topology",
    "parcel_membership",
    "source_feature_binding",
]

TypedScope = CanonicalScope
TypedPhase = CanonicalPhase
TypedStrategyAction = CanonicalStrategyAction
TypedRelationKind = CanonicalRelationKind
TypedGroundingRequirement = CanonicalGroundingRequirement


def _normalize_source_fact_refs(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        raise TypeError("source_fact_refs_must_be_a_list")
    result: list[str] = []
    for raw in values:
        text = _clean_text(raw)
        if not text:
            raise ValueError("source_fact_refs_must_not_contain_empty_ids")
        if not text.startswith("l1:fact:"):
            raise ValueError("source_fact_refs_must_use_l1_fact_namespace")
        result.append(text)
    return result


def _normalize_enum_or_none(value: Any, *, field_name: str, allowed: tuple[str, ...]) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if text not in allowed:
        raise ValueError(f"{field_name}_not_in_closed_set")
    return text


def _normalize_grounding_requirements(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        raise TypeError("grounding_requirements_must_be_a_list")
    result: list[str] = []
    for raw in values:
        text = _clean_text(raw)
        if not text:
            raise ValueError("grounding_requirements_must_not_contain_empty_values")
        if text not in CanonicalGroundingRequirement.__args__:
            raise ValueError("grounding_requirement_not_in_closed_set")
        result.append(text)
    return result


class StrictL2Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyConflict(StrictL2Model):
    description: str
    between: list[str] = Field(default_factory=list)
    severity: Severity


class StrategyIssue(StrictL2Model):
    """Strategy-level issue for the G2 gate (mirrors StageIssue)."""

    stage: Literal["l2"] = "l2"
    severity: Severity
    code: str = ""
    message: str = ""
    detail: str = ""


class PlanningObjective(StrictL2Model):
    """One typed objective or constraint proposed by an L2 dimension."""

    objective_id: str = Field(min_length=1)
    statement: str = ""
    kind: ObjectiveKind
    status: DecisionStatus
    scope: TypedScope | None = None
    target_year: str = ""
    source_fact_refs: list[L1FactRef] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)
    rationale: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    _validate_objective_id = field_validator("objective_id", mode="before")(_nonempty_id)
    _validate_confidence = field_validator("confidence", mode="before")(_confidence)

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: Any) -> str | None:
        return _normalize_enum_or_none(
            value,
            field_name="scope",
            allowed=CanonicalScope.__args__,
        )

    @field_validator("source_fact_refs", mode="before")
    @classmethod
    def _normalize_source_fact_refs(cls, value: Any) -> list[str]:
        return _normalize_source_fact_refs(value)


class TargetMetric(StrictL2Model):
    """A metric with explicit status; proposed values are not source facts."""

    metric_id: str = Field(min_length=1)
    name: str = ""
    value: str | int | float | None = None
    unit: str = ""
    direction: MetricDirection
    status: DecisionStatus
    baseline_ref: str = ""
    objective_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[L1FactRef] = Field(default_factory=list)
    target_year: str = ""
    rationale: str = ""

    _validate_metric_id = field_validator("metric_id", mode="before")(_nonempty_id)

    @field_validator("source_fact_refs", mode="before")
    @classmethod
    def _normalize_source_fact_refs(cls, value: Any) -> list[str]:
        return _normalize_source_fact_refs(value)


class StrategyRule(StrictL2Model):
    """A typed strategy rule that can be traced to objectives and evidence."""

    strategy_id: str = Field(min_length=1)
    statement: str = ""
    action: TypedStrategyAction | None = None
    objective_refs: list[str] = Field(default_factory=list)
    target_refs: list[str] = Field(default_factory=list)
    strength: StrategyStrength
    scope: TypedScope | None = None
    phase: TypedPhase | None = None
    prerequisite_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[L1FactRef] = Field(default_factory=list)
    rationale: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    _validate_strategy_id = field_validator("strategy_id", mode="before")(_nonempty_id)
    _validate_confidence = field_validator("confidence", mode="before")(_confidence)

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, value: Any) -> str | None:
        return _normalize_enum_or_none(
            value,
            field_name="action",
            allowed=CanonicalStrategyAction.__args__,
        )

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: Any) -> str | None:
        return _normalize_enum_or_none(
            value,
            field_name="scope",
            allowed=CanonicalScope.__args__,
        )

    @field_validator("phase", mode="before")
    @classmethod
    def _normalize_phase(cls, value: Any) -> str | None:
        return _normalize_enum_or_none(
            value,
            field_name="phase",
            allowed=CanonicalPhase.__args__,
        )

    @field_validator("source_fact_refs", mode="before")
    @classmethod
    def _normalize_source_fact_refs(cls, value: Any) -> list[str]:
        return _normalize_source_fact_refs(value)


class PriorityDecision(StrictL2Model):
    """Explicit ordering decision; rank is advisory until scenario solving."""

    priority_id: str = Field(min_length=1)
    rank: int | None = None
    strategy_refs: list[str] = Field(default_factory=list)
    statement: str = ""
    rationale: str = ""

    _validate_priority_id = field_validator("priority_id", mode="before")(_nonempty_id)


class SpatialStructureIntent(StrictL2Model):
    """Non-geometric spatial structure intent passed to L3/GROUND."""

    structure_id: str = Field(min_length=1)
    statement: str = ""
    scope: TypedScope | None = None
    relation_kind: TypedRelationKind | None = None
    objective_refs: list[str] = Field(default_factory=list)
    source_fact_refs: list[L1FactRef] = Field(default_factory=list)
    grounding_requirements: list[TypedGroundingRequirement] = Field(default_factory=list)

    _validate_structure_id = field_validator("structure_id", mode="before")(_nonempty_id)

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: Any) -> str | None:
        return _normalize_enum_or_none(
            value,
            field_name="scope",
            allowed=CanonicalScope.__args__,
        )

    @field_validator("relation_kind", mode="before")
    @classmethod
    def _normalize_relation_kind(cls, value: Any) -> str | None:
        return _normalize_enum_or_none(
            value,
            field_name="relation_kind",
            allowed=CanonicalRelationKind.__args__,
        )

    @field_validator("grounding_requirements", mode="before")
    @classmethod
    def _normalize_grounding_requirements(cls, value: Any) -> list[str]:
        return _normalize_grounding_requirements(value)

    @field_validator("source_fact_refs", mode="before")
    @classmethod
    def _normalize_source_fact_refs(cls, value: Any) -> list[str]:
        return _normalize_source_fact_refs(value)


class ConflictHypothesis(StrictL2Model):
    """A model-declared conflict; no lexical conflict detector is used."""

    conflict_id: str = Field(min_length=1)
    description: str = ""
    objective_refs: list[str] = Field(default_factory=list)
    strategy_refs: list[str] = Field(default_factory=list)
    severity: Severity
    resolution: str = ""

    _validate_conflict_id = field_validator("conflict_id", mode="before")(_nonempty_id)


class L2EvidenceGap(StrictL2Model):
    """Typed missing prerequisite; IDs are normalized at the stage boundary."""

    gap_id: str = Field(min_length=1)
    dimension: str = ""
    description: str = ""
    required_fact: str = ""
    severity: Severity

    _validate_gap_id = field_validator("gap_id", mode="before")(_nonempty_id)


class L2DecisionSet(StrictL2Model):
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

    @field_validator("source_refs", "diagnostics", mode="before")
    @classmethod
    def decode_provider_lists(cls, value: Any) -> Any:
        if isinstance(value, str):
            decoded = decode_json_container(value)
            if not isinstance(decoded, list):
                raise TypeError("l2 provider list must decode to a list")
            return decoded
        return value


class L2ReportOutput(StrictL2Model):
    """Human-readable L2 report synthesized from one validated decision set."""

    report_body: str = Field(min_length=1)


class L2Strategy(ContractMeta):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "2.0"
    decision_sets: list[L2DecisionSet] = Field(default_factory=list)
    objectives: list[PlanningObjective] = Field(default_factory=list)
    metrics: list[TargetMetric] = Field(default_factory=list)
    strategy_rules: list[StrategyRule] = Field(default_factory=list)
    priority_decisions: list[PriorityDecision] = Field(default_factory=list)
    spatial_structure_intents: list[SpatialStructureIntent] = Field(default_factory=list)
    conflict_hypotheses: list[ConflictHypothesis] = Field(default_factory=list)
    development_goals: list[str] = Field(default_factory=list)
    spatial_structure: str = ""
    implementation_priorities: list[str] = Field(default_factory=list)
    strategy_conflicts: list[StrategyConflict] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)
    strategy_issues: list[StrategyIssue] = Field(default_factory=list)
    dimension_provenance: list[Provenance] = Field(default_factory=list)
    provenance: Provenance | None = None
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)


__all__ = [
    "CanonicalGroundingRequirement",
    "CanonicalPhase",
    "CanonicalRelationKind",
    "CanonicalScope",
    "CanonicalStrategyAction",
    "ConflictHypothesis",
    "L1FactRef",
    "L2DecisionSet",
    "L2EvidenceGap",
    "L2ReportOutput",
    "L2Strategy",
    "PlanningObjective",
    "PriorityDecision",
    "SourceFeatureRef",
    "SourceSegmentRef",
    "SpatialStructureIntent",
    "StrategyConflict",
    "StrategyIssue",
    "StrategyRule",
    "TargetMetric",
]
