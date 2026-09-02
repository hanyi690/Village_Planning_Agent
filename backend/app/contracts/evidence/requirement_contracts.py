"""Requirement, claim, and coverage contracts for bounded evidence retrieval."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.evidence.reasoning_contracts import (
    CandidateEvidence,
    ConflictSet,
    EvidenceSufficiencyResult,
    SufficiencyCheck,
    SufficiencyTerminalStatus,
)


RequirementKind = Literal[
    "claim",
    "identity",
    "spatial",
    "constraint",
    "metric",
    "source",
]
EvidenceStatus = Literal["supported", "contradicted", "ambiguous", "unavailable"]
CoverageStatus = Literal[
    "supported",
    "contradicted",
    "ambiguous",
    "unavailable",
    "unresolved",
]
CoverageStopReason = Literal[
    "sufficient",
    "source_exhausted",
    "human_required",
    "budget_exhausted",
]


class EvidenceRequirement(BaseModel):
    """One auditable question that must be supported before a decision."""

    requirement_id: str
    requirement_ref: str = ""
    schema_version: str = "1.0"
    request_id: str = ""
    requesting_artifact_ref: str = ""
    requesting_artifact_revision: str = ""
    producer_stage: str = "EXPLORE"
    statement: str
    kind: RequirementKind = "claim"
    subject_refs: tuple[str, ...] = Field(default_factory=tuple)
    purpose: str = ""
    required: bool = True
    source_families: tuple[str, ...] = Field(default_factory=tuple)
    scope: tuple[str, ...] = Field(default_factory=tuple)
    temporal_scope: str = ""
    valid_time: str = ""
    spatial_granularity: str = "none"
    allowed_inference: Literal["exact", "derived", "inferred", "text_only"] = "exact"
    evidence_role: str = "planning_background"
    success_condition: str = ""
    # Gap scheduling metadata.  Evidence may resolve a requirement as soon
    # as the current stage has enough subject/capability information; a later
    # stage is recorded only when the missing decision depends on downstream
    # semantics (for example representation purpose).
    earliest_resolution_stage: str = ""
    deferred_until: str = ""
    retrieval_capability: str = ""
    policy_ref: str = "source_semantic_support.v1"
    contract_version: Literal["1.0"] = "1.0"
    gap_status: Literal[
        "open",
        "ready_for_retrieval",
        "retrieving",
        "resolved",
        "not_available",
        "requires_human_confirmation",
    ] = "open"
    source_artifact_refs: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("requirement_id", "statement")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("evidence requirement identity and statement are required")
        return normalized

    @model_validator(mode="after")
    def _normalize_identity_and_policy(self) -> "EvidenceRequirement":
        if not self.requirement_ref:
            object.__setattr__(self, "requirement_ref", self.requirement_id)
        if self.requirement_ref != self.requirement_id:
            raise ValueError("requirement_ref must match requirement_id")
        if not self.purpose:
            object.__setattr__(self, "purpose", self.evidence_role)
        if not self.subject_refs and self.scope:
            object.__setattr__(self, "subject_refs", self.scope)
        if not self.valid_time and self.temporal_scope:
            object.__setattr__(self, "valid_time", self.temporal_scope)
        if self.policy_ref == "source_semantic_support.v1":
            default_policy = {
                "spatial": "location_identity_support.v1",
                "identity": "facility_existence.v1",
                "constraint": "legal_extent_support.v1",
            }.get(self.kind)
            if default_policy:
                object.__setattr__(self, "policy_ref", default_policy)
        return self


class EvidenceClaim(BaseModel):
    """A source-backed claim that can be attached to one or more requirements."""

    claim_id: str
    statement: str
    status: EvidenceStatus = "supported"
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_families: tuple[str, ...] = Field(default_factory=tuple)
    locators: tuple[str, ...] = Field(default_factory=tuple)
    spatial_refs: tuple[str, ...] = Field(default_factory=tuple)
    authority: str = "advisory"
    snapshot_refs: tuple[str, ...] = Field(default_factory=tuple)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    support_relation: str = "supports"
    derived_from: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("claim_id", "statement")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("evidence claim identity and statement are required")
        return normalized

    @property
    def locator_complete(self) -> bool:
        return bool(self.locators)


class RequirementCoverage(BaseModel):
    """Coverage decision for one EvidenceRequirement."""

    requirement_id: str
    status: CoverageStatus
    claim_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_families_covered: tuple[str, ...] = Field(default_factory=tuple)
    locators_complete: bool = False
    conflict_refs: tuple[str, ...] = Field(default_factory=tuple)
    unresolved_reason: str = ""
    policy_ref: str = ""
    policy_version: str = ""
    candidate_refs: tuple[str, ...] = Field(default_factory=tuple)
    sufficiency_status: SufficiencyTerminalStatus | None = None
    sufficiency_checks: tuple[SufficiencyCheck, ...] = Field(default_factory=tuple)
    conclusion_kind: Literal["presence", "absence", "none"] = "none"

    @field_validator("requirement_id")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("requirement coverage identity is required")
        return normalized


class EvidenceCoverage(ContractMeta):
    """Bounded completeness result for one requirement set and retrieval run."""

    run_id: str = ""
    request_id: str = ""
    requirement_set_fingerprint: str
    source_scope: Literal["scoped", "project_wide", "declared"] = "scoped"
    source_families_queried: tuple[str, ...] = Field(default_factory=tuple)
    requirements: tuple[EvidenceRequirement, ...] = Field(default_factory=tuple)
    requirement_coverage: tuple[RequirementCoverage, ...] = Field(default_factory=tuple)
    claims: tuple[EvidenceClaim, ...] = Field(default_factory=tuple)
    unresolved_requirements: tuple[str, ...] = Field(default_factory=tuple)
    unavailable_source_families: tuple[str, ...] = Field(default_factory=tuple)
    conflict_refs: tuple[str, ...] = Field(default_factory=tuple)
    stop_reason: CoverageStopReason
    query_trace: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    candidate_evidence: tuple[CandidateEvidence, ...] = Field(default_factory=tuple)
    conflict_sets: tuple[ConflictSet, ...] = Field(default_factory=tuple)
    sufficiency_decision: EvidenceSufficiencyResult | None = None

    @field_validator("requirement_set_fingerprint")
    @classmethod
    def _require_fingerprint(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("requirement set fingerprint is required")
        return normalized

    @model_validator(mode="after")
    def _validate_references(self) -> "EvidenceCoverage":
        requirement_ids = tuple(item.requirement_id for item in self.requirements)
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("evidence requirement IDs must be unique")
        coverage_ids = tuple(item.requirement_id for item in self.requirement_coverage)
        unknown = set(coverage_ids).difference(requirement_ids)
        if unknown:
            raise ValueError(f"coverage references unknown requirements: {sorted(unknown)}")
        if self.stop_reason == "sufficient" and self.unresolved_requirements:
            raise ValueError("sufficient coverage cannot contain unresolved requirements")
        return self

    @property
    def sufficient(self) -> bool:
        return self.stop_reason == "sufficient" and not self.unresolved_requirements


__all__ = [
    "CoverageStatus",
    "CoverageStopReason",
    "EvidenceClaim",
    "EvidenceCoverage",
    "EvidenceRequirement",
    "EvidenceStatus",
    "RequirementCoverage",
]
