"""Strict contracts for evidence search and bounded workflow repair."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.evidence.model.base import JsonObject, StrictContractModel
from app.evidence.model.relation_evidence import RelationEvidence
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor


class ValidationAdjustment(StrictContractModel):
    """A bounded, idempotent validation repair request."""

    adjustment_id: str
    responsible_stage: str
    affected_target_refs: list[str] = Field(default_factory=list)
    input_refs: dict[str, ArtifactDescriptor] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    bounded_params: JsonObject = Field(default_factory=dict)
    issue_fingerprint: str
    idempotency_key: str


class IterationRecord(StrictContractModel):
    """Immutable audit record for one bounded validation iteration."""

    iteration: int
    issue_fingerprint: str
    parent_checksum: str
    adjustment_refs: list[str] = Field(default_factory=list)
    affected_target_refs: list[str] = Field(default_factory=list)
    before_check_refs: list[str] = Field(default_factory=list)
    after_check_refs: list[str] = Field(default_factory=list)
    spatial_diff_ref: str | None = None
    output_checksum: str


class SearchFailure(StrictContractModel):
    """Typed unresolved outcome for external retrieval."""

    code: Literal[
        "empty",
        "provider_unavailable",
        "provider_timeout",
        "provider_unauthorized",
        "provider_rate_limited",
        "content_failed",
        "stale_source",
        "source_conflict",
        "source_not_allowed",
        "budget_exceeded",
        "unresolved",
        "unexpected",
        "no_results",
    ]
    message: str
    retryable: bool
    local_fallback_allowed: bool


class ExternalSearchRequest(StrictContractModel):
    """Provider-neutral request for optional EXPLORE external retrieval."""

    query_purpose: str
    normalized_entities: list[JsonObject] = Field(default_factory=list)
    entity_scope: list[str] = Field(default_factory=list)
    source_policy: JsonObject = Field(default_factory=dict)
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    freshness: JsonObject = Field(default_factory=dict)
    search_mode: str
    result_limit: int
    content_mode: str
    budget: JsonObject = Field(default_factory=dict)
    parent_refs: list[str] = Field(default_factory=list)
    idempotency_key: str


class ExternalSearchResult(StrictContractModel):
    """Replayable success, empty, or unresolved external evidence result."""

    provider: str
    request_id: str
    resolved_search_mode: str
    result_records: list[JsonObject] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    retrieval_status: Literal[
        "success",
        "empty",
        "unavailable",
        "timeout",
        "failed",
        "conflict",
        "stale",
        "budget_exceeded",
        "unresolved",
    ]
    latency_ms: int | None = None
    cost: JsonObject | None = None
    cache_policy: Literal["cache", "live", "cache_or_live"] = "cache_or_live"
    failure: SearchFailure | None = None

    @model_validator(mode="after")
    def validate_failure_shape(self) -> "ExternalSearchResult":
        failure_statuses = {
            "empty",
            "unavailable",
            "timeout",
            "failed",
            "conflict",
            "stale",
            "budget_exceeded",
            "unresolved",
        }
        if self.retrieval_status == "success" and self.failure is not None:
            raise ValueError("successful search results cannot contain failure")
        if self.retrieval_status in failure_statuses and self.failure is None:
            raise ValueError("unresolved search results require typed failure")
        return self


class AdjustmentFailure(StrictContractModel):
    """Typed repair execution failure without provider-specific details."""

    code: Literal["rejected", "conflict", "budget_exceeded", "unresolved"]
    message: str
    retryable: bool = False


class AdjustmentExecutionResult(StrictContractModel):
    """Typed result returned by a validation adjustment executor."""

    status: Literal["applied", "noop", "rejected", "failed", "human_required"]
    output_refs: dict[str, ArtifactDescriptor] = Field(default_factory=dict)
    iteration: IterationRecord | None = None
    failure: AdjustmentFailure | None = None

    @model_validator(mode="after")
    def validate_failure_shape(self) -> "AdjustmentExecutionResult":
        failure_statuses = {"rejected", "failed", "human_required"}
        if self.status in failure_statuses and self.failure is None:
            raise ValueError("non-successful adjustment results require failure")
        if self.status in {"applied", "noop"} and self.failure is not None:
            raise ValueError("successful adjustment results cannot contain failure")
        return self


__all__ = [
    "AdjustmentExecutionResult",
    "AdjustmentFailure",
    "ExternalSearchRequest",
    "ExternalSearchResult",
    "IterationRecord",
    "RelationEvidence",
    "SearchFailure",
    "ValidationAdjustment",
]
