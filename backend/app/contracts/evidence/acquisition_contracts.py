"""Lineage contracts for Evidence provider attempts, pages, and observations."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .provider_attempt import EvidenceObservationRecord, ProviderAttemptStatus


TerminationReason = Literal[
    "provider_exhausted",
    "declared_limit_reached",
    "budget_exhausted",
    "quota_exhausted",
    "failed",
    "cancelled",
]
AcquisitionCompletion = Literal["complete", "partial", "failed", "not_available"]
OriginCompleteness = Literal["complete", "incomplete", "unknown", "not_applicable"]
CompletionBasis = Literal[
    "required_routes_complete",
    "required_route_incomplete",
    "no_required_routes",
    "acquisition_failed",
    "not_available",
]


class ProviderPageRecord(BaseModel):
    """Immutable audit record for one provider acquisition page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_ref: str = Field(min_length=1)
    attempt_ref: str = Field(min_length=1)
    query_fingerprint: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    cursor_in: str = ""
    cursor_out: str = ""
    page_index: int = Field(default=0, ge=0)
    item_count: int = Field(default=0, ge=0)
    response_digest: str = ""
    raw_response_ref: str = ""
    attempt_status: ProviderAttemptStatus
    latency_ms: float = Field(default=0.0, ge=0.0)
    termination_reason: TerminationReason | None = None

    @model_validator(mode="after")
    def _validate_termination(self) -> "ProviderPageRecord":
        if self.termination_reason is not None and self.attempt_status in {
            "NOT_ATTEMPTED",
            "RUNNING",
        }:
            raise ValueError("a non-terminal attempt cannot terminate a provider page")
        return self


class EvidenceObservationSnapshot(BaseModel):
    """Bounded observation set retaining query and attempt lineage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_ref: str = Field(min_length=1)
    query_plan_ref: str = Field(min_length=1)
    query_plan_fingerprint: str = Field(min_length=1)
    attempt_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    records: tuple[EvidenceObservationRecord, ...] = ()
    complete: bool = False
    digest: str = ""

    @model_validator(mode="after")
    def _freeze_digest(self) -> "EvidenceObservationSnapshot":
        payload = self.model_dump(mode="json", exclude={"digest"})
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if self.digest and self.digest != digest:
            raise ValueError("observation snapshot digest does not match its content")
        object.__setattr__(self, "digest", digest)
        return self


class EvidenceAcquisitionReceipt(BaseModel):
    """Replayable completion summary for one immutable query plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_ref: str = Field(min_length=1)
    query_plan_ref: str = Field(min_length=1)
    query_plan_fingerprint: str = Field(min_length=1)
    attempt_refs: tuple[str, ...] = ()
    page_refs: tuple[str, ...] = ()
    required_route_refs: tuple[str, ...] = ()
    completed_required_routes: tuple[str, ...] = ()
    incomplete_required_routes: tuple[str, ...] = ()
    optional_unattempted_routes: tuple[str, ...] = ()
    completion_basis: CompletionBasis = "not_available"
    cache_read_complete: bool = False
    origin_completeness: OriginCompleteness = "not_applicable"
    observation_snapshot_ref: str = ""
    observation_snapshot_digest: str = ""
    completion: AcquisitionCompletion = "not_available"
    termination_reasons: tuple[TerminationReason, ...] = ()
    digest: str = ""

    @model_validator(mode="after")
    def _freeze_digest(self) -> "EvidenceAcquisitionReceipt":
        required = set(self.required_route_refs)
        completed = set(self.completed_required_routes)
        incomplete = set(self.incomplete_required_routes)
        if completed.intersection(incomplete):
            raise ValueError("a route cannot be both completed and incomplete")
        if not completed.issubset(required) or not incomplete.issubset(required):
            raise ValueError("required route completion lists must match required routes")
        if self.completion == "complete" and self.incomplete_required_routes:
            raise ValueError("a complete receipt cannot have incomplete required routes")
        if self.completion == "complete" and any(
            reason in {"budget_exhausted", "quota_exhausted", "failed", "cancelled"}
            for reason in self.termination_reasons
        ):
            raise ValueError("an incomplete termination cannot produce a complete receipt")
        payload = self.model_dump(mode="json", exclude={"digest"})
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if self.digest and self.digest != digest:
            raise ValueError("acquisition receipt digest does not match its content")
        object.__setattr__(self, "digest", digest)
        return self


__all__ = [
    "AcquisitionCompletion",
    "CompletionBasis",
    "OriginCompleteness",
    "EvidenceAcquisitionReceipt",
    "EvidenceObservationSnapshot",
    "ProviderPageRecord",
    "TerminationReason",
]
