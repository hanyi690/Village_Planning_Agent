"""Typed, auditable contracts for verified structured LLM decisions.

These contracts intentionally model decision mechanics only.  They do not
encode planning-domain defaults or repair domain semantics.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


DecisionT = TypeVar("DecisionT")


def canonical_json(value: Any) -> str:
    """Return a deterministic JSON representation suitable for hashing."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_digest(value: Any) -> str:
    """Return the SHA-256 digest for canonical JSON-compatible input."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def schema_digest(model: type[BaseModel]) -> str:
    """Return the stable JSON Schema digest for a proposal contract."""
    return stable_digest(model.model_json_schema())


class StrictDecisionModel(BaseModel):
    """Shared configuration for public verified-decision contracts."""

    model_config = ConfigDict(extra="forbid")


class ClosedSetRef(StrictDecisionModel):
    """A typed reference whose namespace is explicit at every boundary."""

    namespace: Literal[
        "l1_fact",
        "source_segment",
        "source_feature",
        "objective",
        "strategy",
        "claim",
        "target",
        "constraint",
        "candidate",
        "network",
        "demand",
    ]
    ref_id: str = Field(min_length=1)

    @property
    def key(self) -> str:
        return f"{self.namespace}:{self.ref_id}"


class SourceSpanRef(StrictDecisionModel):
    """A hash-addressed span inside a source segment."""

    segment_id: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self) -> "SourceSpanRef":
        if self.end <= self.start:
            raise ValueError("source span end must be greater than start")
        return self


class DecisionContext(StrictDecisionModel):
    """Stable identity and input lineage required for one decision attempt."""

    stage: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    input_digest: str = Field(min_length=1)
    schema_digest: str = ""
    prompt_digest: str = ""
    candidate_set_digest: str = ""
    prompt_version: str = ""
    provider: str = ""
    model: str = ""
    validator_version: str = ""


class SemanticIssue(StrictDecisionModel):
    """A deterministic semantic finding with a stable replay fingerprint."""

    issue_id: str = ""
    fingerprint: str = ""
    stage: str = Field(min_length=1)
    code: str = Field(min_length=1)
    severity: Literal["info", "warning", "error"] = "error"
    fatal_scope: Literal[
        "field",
        "record",
        "dimension",
        "claim",
        "relation",
        "task",
        "dependency_subgraph",
        "stage",
    ] = "record"
    object_ref: str = ""
    field_path: str = ""
    dependency_refs: list[str] = Field(default_factory=list)
    retryable: bool = False
    repair_kind: str = ""
    message: str = ""

    @model_validator(mode="after")
    def canonicalize_identity(self) -> "SemanticIssue":
        self.dependency_refs = sorted({value.strip() for value in self.dependency_refs if value.strip()})
        fingerprint_payload = {
            "stage": self.stage,
            "code": self.code,
            "severity": self.severity,
            "fatal_scope": self.fatal_scope,
            "object_ref": self.object_ref,
            "field_path": self.field_path,
            "dependency_refs": self.dependency_refs,
            "retryable": self.retryable,
            "repair_kind": self.repair_kind,
        }
        derived_fingerprint = stable_digest(fingerprint_payload)
        if self.fingerprint and self.fingerprint != derived_fingerprint:
            raise ValueError("semantic issue fingerprint does not match canonical issue identity")
        self.fingerprint = derived_fingerprint
        if not self.issue_id:
            self.issue_id = f"issue:{derived_fingerprint[:24]}"
        return self


class QuarantinedRecord(StrictDecisionModel):
    """A rejected proposal record retained by digest and issue lineage."""

    record_ref: str = Field(min_length=1)
    payload_digest: str = Field(min_length=1)
    issue_fingerprints: list[str] = Field(default_factory=list)
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def canonicalize_issue_fingerprints(self) -> "QuarantinedRecord":
        self.issue_fingerprints = sorted(set(self.issue_fingerprints))
        return self


class PendingDecision(StrictDecisionModel):
    """A proposal withheld for evidence, review, or an explicit retry."""

    decision_ref: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    issue_fingerprints: list[str] = Field(default_factory=list)
    dependency_refs: list[str] = Field(default_factory=list)
    requires_human_review: bool = False

    @model_validator(mode="after")
    def canonicalize_references(self) -> "PendingDecision":
        self.issue_fingerprints = sorted(set(self.issue_fingerprints))
        self.dependency_refs = sorted({value.strip() for value in self.dependency_refs if value.strip()})
        return self


class RepairOperation(StrictDecisionModel):
    """An auditable proposed change; application is decided by repair policy."""

    operation_id: str = ""
    object_ref: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    before: Any = None
    after: Any = None
    reason_code: str = Field(min_length=1)
    evidence_refs: list[ClosedSetRef] = Field(default_factory=list)
    repair_kind: Literal["shape_only", "identity_resolution", "semantic_change"]
    operation: Literal["set", "remove", "replace"] = "set"
    hard_relation: bool = False
    validator_before: list[str] = Field(default_factory=list)
    validator_after: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_operation(self) -> "RepairOperation":
        self.evidence_refs = sorted(self.evidence_refs, key=lambda item: item.key)
        self.validator_before = sorted(set(self.validator_before))
        self.validator_after = sorted(set(self.validator_after))
        if not self.operation_id:
            identity = self.model_dump(mode="json", exclude={"operation_id"})
            self.operation_id = f"repair:{stable_digest(identity)[:24]}"
        return self


class DecisionCertificate(StrictDecisionModel):
    """A compact, reproducible receipt for one verified decision attempt."""

    input_digest: str = Field(min_length=1)
    schema_digest: str = ""
    prompt_digest: str = ""
    candidate_set_digest: str = ""
    output_digest: str = ""
    accepted_digest: str = ""
    prompt_version: str = ""
    provider: str = ""
    model: str = ""
    validator_version: str = ""
    accepted_refs: list[str] = Field(default_factory=list)
    quarantined_refs: list[str] = Field(default_factory=list)
    pending_refs: list[str] = Field(default_factory=list)
    issue_fingerprints: list[str] = Field(default_factory=list)
    repair_operations: list[RepairOperation] = Field(default_factory=list)

    @model_validator(mode="after")
    def canonicalize_certificate(self) -> "DecisionCertificate":
        for field_name in (
            "accepted_refs",
            "quarantined_refs",
            "pending_refs",
            "issue_fingerprints",
        ):
            setattr(self, field_name, sorted(set(getattr(self, field_name))))
        self.repair_operations = sorted(self.repair_operations, key=lambda item: item.operation_id)
        return self


class RetryState(StrictDecisionModel):
    """Replay information used to stop same-input, same-issue loops."""

    attempt: int = Field(default=1, ge=1)
    input_digest: str = ""
    issue_fingerprint: str = ""
    previous_issue_fingerprint: str = ""
    accepted_digest: str = ""
    output_digest: str = ""
    transport_failure_code: str = ""
    inputs_changed: bool = True
    progress_made: bool = True
    no_progress: bool = False
    should_stop: bool = False


class SemanticValidationOutcome(StrictDecisionModel, Generic[DecisionT]):
    """The semantic validator's explicit routing result for a proposal."""

    accepted: list[DecisionT] = Field(default_factory=list)
    quarantined: list[QuarantinedRecord] = Field(default_factory=list)
    pending: list[PendingDecision] = Field(default_factory=list)
    issues: list[SemanticIssue] = Field(default_factory=list)
    repair_operations: list[RepairOperation] = Field(default_factory=list)


class VerifiedDecisionResult(StrictDecisionModel, Generic[DecisionT]):
    """The only result emitted by the verified structured decision kernel."""

    accepted: list[DecisionT] = Field(default_factory=list)
    quarantined: list[QuarantinedRecord] = Field(default_factory=list)
    pending: list[PendingDecision] = Field(default_factory=list)
    issues: list[SemanticIssue] = Field(default_factory=list)
    certificate: DecisionCertificate
    retry_state: RetryState


__all__ = [
    "ClosedSetRef",
    "DecisionCertificate",
    "DecisionContext",
    "PendingDecision",
    "QuarantinedRecord",
    "RepairOperation",
    "RetryState",
    "SemanticIssue",
    "SemanticValidationOutcome",
    "SourceSpanRef",
    "VerifiedDecisionResult",
    "canonical_json",
    "schema_digest",
    "stable_digest",
]
