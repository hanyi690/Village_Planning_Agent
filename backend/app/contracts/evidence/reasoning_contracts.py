"""Immutable reasoning artifacts for the EV-02 Evidence sufficiency gate."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ReasoningGate = Literal[
    "source_family",
    "source_authority",
    "independent_sources",
    "temporal_fit",
    "geometry_legal_authority",
    "conflict_policy",
    "allowed_inference",
    "acquisition_completeness",
    "provider_origin_completeness",
    "absence_policy",
]
GateStatus = Literal["pass", "fail", "not_applicable"]
ConflictKind = Literal[
    "value",
    "identity",
    "geometry",
    "temporal",
    "authority",
    "scope",
    "provider_status",
]
ConflictResolutionStatus = Literal["unresolved", "resolved", "rejected"]
SufficiencyTerminalStatus = Literal[
    "sufficient",
    "partial",
    "insufficient",
    "contradicted",
    "not_available",
    "human_required",
    "failed",
]
ConclusionKind = Literal["presence", "absence", "none"]


class CandidateEvidence(BaseModel):
    """One requirement-scoped interpretation of typed observations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_ref: str = Field(min_length=1)
    requirement_ref: str = Field(min_length=1)
    observation_refs: tuple[str, ...] = ()
    claim_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_families: tuple[str, ...] = ()
    source_authorities: tuple[str, ...] = ()
    geometry_authorities: tuple[str, ...] = ()
    legal_authorities: tuple[str, ...] = ()
    spatial_refs: tuple[str, ...] = ()
    independent_source_refs: tuple[str, ...] = ()
    valid_times: tuple[str, ...] = ()
    inference_levels: tuple[str, ...] = ()
    statement: str = ""
    value_digest: str = ""
    locator_refs: tuple[str, ...] = ()
    support_status: Literal["supported", "contradicted", "ambiguous", "unavailable"] = "supported"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ConflictSet(BaseModel):
    """Requirement-scoped conflict detected before sufficiency evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conflict_ref: str = Field(min_length=1)
    requirement_ref: str = Field(min_length=1)
    candidate_refs: tuple[str, ...] = Field(min_length=2)
    conflict_kind: ConflictKind
    policy: Literal["resolve", "defer", "human", "reject"]
    resolution_status: ConflictResolutionStatus = "unresolved"
    resolution_ref: str = ""
    reason: str = ""


class SufficiencyCheck(BaseModel):
    """One ordered policy gate result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: ReasoningGate
    status: GateStatus
    evidence_refs: tuple[str, ...] = ()
    observed: tuple[str, ...] = ()
    expected: tuple[str, ...] = ()
    reason: str = ""


_GATE_ORDER: tuple[ReasoningGate, ...] = (
    "source_family",
    "source_authority",
    "independent_sources",
    "temporal_fit",
    "geometry_legal_authority",
    "conflict_policy",
    "allowed_inference",
    "acquisition_completeness",
    "provider_origin_completeness",
    "absence_policy",
)


class RequirementSufficiencyDecision(BaseModel):
    """Final EV-02 decision and its complete gate audit for one requirement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_ref: str = Field(min_length=1)
    policy_ref: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    status: SufficiencyTerminalStatus
    candidate_refs: tuple[str, ...] = ()
    conflict_refs: tuple[str, ...] = ()
    checks: tuple[SufficiencyCheck, ...] = ()
    conclusion_kind: ConclusionKind = "none"
    absence_authorized: bool = False
    reason: str = ""

    @model_validator(mode="after")
    def _validate_gate_order_and_absence(self) -> "RequirementSufficiencyDecision":
        gates = tuple(check.gate for check in self.checks)
        if gates and gates != _GATE_ORDER:
            raise ValueError("sufficiency checks must follow the EV-02 gate order")
        if self.conclusion_kind == "absence" and not self.absence_authorized:
            raise ValueError("absence conclusion requires absence authorization")
        if self.absence_authorized and self.conclusion_kind != "absence":
            raise ValueError("absence authorization requires an absence conclusion")
        return self


class EvidenceSufficiencyResult(BaseModel):
    """Persistable output of the full Candidate → Conflict → Sufficiency chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: SufficiencyTerminalStatus
    candidates: tuple[CandidateEvidence, ...] = ()
    conflicts: tuple[ConflictSet, ...] = ()
    requirement_decisions: tuple[RequirementSufficiencyDecision, ...] = ()
    absence_authorized: bool = False
    reason: str = ""

    @model_validator(mode="after")
    def _validate_absence(self) -> "EvidenceSufficiencyResult":
        authorized = any(
            decision.absence_authorized
            for decision in self.requirement_decisions
        )
        if self.absence_authorized != authorized:
            raise ValueError("aggregate absence authorization does not match requirement decisions")
        return self


__all__ = [
    "CandidateEvidence",
    "ConflictKind",
    "ConflictResolutionStatus",
    "ConflictSet",
    "ConclusionKind",
    "EvidenceSufficiencyResult",
    "GateStatus",
    "ReasoningGate",
    "RequirementSufficiencyDecision",
    "SufficiencyCheck",
    "SufficiencyTerminalStatus",
]
