"""Typed Evidence acquisition attempts and source authority components."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProviderAttemptStatus = Literal[
    "NOT_ATTEMPTED",
    "RUNNING",
    "SUCCESS_NONEMPTY",
    "SUCCESS_EMPTY",
    "PARTIAL",
    "MISSING_CAPABILITY",
    "FAILED_RETRYABLE",
    "FAILED_PERMANENT",
    "QUOTA_EXHAUSTED",
    "TIMEOUT",
    "AUTH_FAILED",
]


class EvidenceConfidence(BaseModel):
    """Independent confidence components; no component implies authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    acquisition: float = Field(default=0.0, ge=0.0, le=1.0)
    semantic: float = Field(default=0.0, ge=0.0, le=1.0)
    binding: float = Field(default=0.0, ge=0.0, le=1.0)
    temporal_fit: float = Field(default=0.0, ge=0.0, le=1.0)


class EvidenceAuthority(BaseModel):
    """Authority axes kept separate from confidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_authority: str = "advisory"
    geometry_authority: str = "none"
    legal_authority: str = "none"


class EvidenceObservationRecord(BaseModel):
    """What a source actually returned; it is not a canonical entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_ref: str = Field(min_length=1)
    query_plan_ref: str = ""
    query_ref: str = ""
    attempt_ref: str = Field(min_length=1)
    route_ref: str = ""
    provider: str = Field(min_length=1)
    page_ref: str = ""
    observation_kind: str = ""
    source_family: str = ""
    subject_refs: tuple[str, ...] = ()
    source_ref: str = ""
    source_refs: tuple[str, ...] = ()
    source_record_ref: str = ""
    world_entity_ref: str = ""
    representation_ref: str = ""
    resource_ref: str = ""
    locator: str = ""
    statement: str = ""
    predicate: str = ""
    value: Any = None
    candidate_ref: str = ""
    valid_time: str = ""
    source_authority: str = "advisory"
    geometry_authority: str = "none"
    legal_authority: str = "none"
    raw_payload_ref: str = ""
    content_digest: str = ""
    origin_provider: str = ""
    origin_record_ref: str = ""
    origin_attempt_ref: str = ""
    origin_status: str = ""
    origin_query_fingerprint: str = ""
    origin_page_refs: tuple[str, ...] = ()
    cache_snapshot_ref: str = ""
    cache_digest: str = ""
    locator_crs: str = ""
    contract_version: Literal["1.0"] = "1.0"
    observed_name: str = ""
    observed_value: Any = None
    coordinates_wgs84: tuple[float, float] | None = None
    observed_at: datetime | None = None
    source_digest: str = ""


class EvidenceCandidate(BaseModel):
    """A bounded interpretation assembled from observations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_ref: str = Field(min_length=1)
    observation_refs: tuple[str, ...] = ()
    subject_ref: str = ""
    candidate_kind: str = ""
    confidence: EvidenceConfidence = Field(default_factory=EvidenceConfidence)
    authority: EvidenceAuthority = Field(default_factory=EvidenceAuthority)
    status: Literal["candidate", "ambiguous", "rejected"] = "candidate"


class EvidenceConclusion(BaseModel):
    """Requirement-specific conclusion, still separate from Cognition commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    conclusion_ref: str = Field(min_length=1)
    requirement_ref: str = Field(min_length=1)
    candidate_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    status: Literal["supported", "contradicted", "ambiguous", "unavailable"]
    confidence: EvidenceConfidence = Field(default_factory=EvidenceConfidence)
    authority: EvidenceAuthority = Field(default_factory=EvidenceAuthority)
    reason: str = ""


class ProviderAttempt(BaseModel):
    """One route × stage × query acquisition attempt.

    ``provider`` is the route authority label. For local DATA, World Model,
    source-span, and frozen-cache routes it is not an external provider name;
    ``provider_name`` is populated only for an external provider.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_ref: str = Field(min_length=1)
    attempt_kind: Literal[
        "local_data",
        "current_world",
        "source_span",
        "frozen_cache",
        "external_provider",
    ] = "external_provider"
    query_plan_ref: str = ""
    query_ref: str = ""
    route_ref: str = ""
    provider: str = Field(min_length=1)
    provider_name: str = ""
    stage: str = Field(min_length=1)
    query_fingerprint: str = ""
    requirement_refs: tuple[str, ...] = ()
    status: ProviderAttemptStatus
    reason_code: str = ""
    retryable: bool = False
    page_record_refs: tuple[str, ...] = ()
    item_count: int = Field(default=0, ge=0)
    raw_response_refs: tuple[str, ...] = ()
    next_retry_hint: str = ""
    acquisition_digest: str = ""
    page_index: int = Field(default=0, ge=0)
    pages_completed: int = Field(default=0, ge=0)
    response_digest: str = ""
    raw_response_ref: str = ""
    latency_ms: float = Field(default=0.0, ge=0.0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_terminal_semantics(self) -> "ProviderAttempt":
        if self.status in {"FAILED_RETRYABLE", "TIMEOUT"} and not self.retryable:
            object.__setattr__(self, "retryable", True)
        if self.status in {"NOT_ATTEMPTED", "RUNNING"} and (
            self.pages_completed or self.page_record_refs or self.item_count
        ):
            raise ValueError("non-terminal provider rows cannot contain acquired pages")
        return self

__all__ = [
    "EvidenceAuthority",
    "EvidenceConfidence",
    "EvidenceObservationRecord",
    "ProviderAttempt",
    "ProviderAttemptStatus",
]
