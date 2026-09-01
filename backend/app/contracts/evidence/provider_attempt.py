"""Typed Evidence acquisition attempts and source authority components."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ProviderAttemptStatus = Literal[
    "NOT_ATTEMPTED",
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


class EvidenceQuery(BaseModel):
    """A compiled query plan, distinct from the requirement it serves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_ref: str = Field(min_length=1)
    requirement_refs: tuple[str, ...] = ()
    normalized_query: str = ""
    provider: str = ""
    scope: tuple[str, ...] = ()
    query_fingerprint: str = ""


class EvidenceObservationRecord(BaseModel):
    """What a source actually returned; it is not a canonical entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observation_ref: str = Field(min_length=1)
    query_ref: str = ""
    attempt_ref: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    source_ref: str = ""
    locator: str = ""
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
    """One provider × stage × query attempt, including incomplete outcomes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_ref: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    query_fingerprint: str = ""
    requirement_refs: tuple[str, ...] = ()
    status: ProviderAttemptStatus
    reason_code: str = ""
    retryable: bool = False
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
        if self.status == "NOT_ATTEMPTED" and self.pages_completed:
            raise ValueError("not-attempted provider rows cannot contain completed pages")
        return self


def provider_attempt_from_legacy(
    row: Any,
    *,
    requirement_refs: tuple[str, ...] = (),
) -> ProviderAttempt:
    """Normalize the pre-migration provider-run dictionary without losing it."""

    payload = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row or {})
    provider = str(payload.get("provider") or "unknown").strip() or "unknown"
    stage = str(payload.get("stage") or "unknown").strip() or "unknown"
    run_id = str(payload.get("run_id") or "missing").strip() or "missing"
    legacy_status = str(payload.get("status") or "not_attempted").strip().casefold()
    status_map = {
        "not_attempted": "NOT_ATTEMPTED",
        "success_nonempty": "SUCCESS_NONEMPTY",
        "success_empty": "SUCCESS_EMPTY",
        "partial": "PARTIAL",
        "missing": "MISSING_CAPABILITY",
        "missing_capability": "MISSING_CAPABILITY",
        "failed": "FAILED_PERMANENT",
        "failed_retryable": "FAILED_RETRYABLE",
        "failed_permanent": "FAILED_PERMANENT",
        "quota_exhausted": "QUOTA_EXHAUSTED",
        "timeout": "TIMEOUT",
        "auth_failed": "AUTH_FAILED",
    }
    status = status_map.get(legacy_status, "FAILED_PERMANENT")
    query_fingerprint = str(payload.get("query_fingerprint") or "").strip()
    if not query_fingerprint:
        query_fingerprint = hashlib.sha256(
            json.dumps(
                {"provider": provider, "stage": stage, "run_id": run_id},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    attempt_ref = str(payload.get("attempt_ref") or "").strip()
    if not attempt_ref:
        attempt_ref = "evidence.attempt." + hashlib.sha256(
            f"{provider}|{stage}|{run_id}|{query_fingerprint}".encode("utf-8")
        ).hexdigest()[:24]
    return ProviderAttempt(
        attempt_ref=attempt_ref,
        provider=provider,
        stage=stage,
        query_fingerprint=query_fingerprint,
        requirement_refs=requirement_refs,
        status=status,
        reason_code=str(
            payload.get("reason_code")
            or payload.get("completion_reason")
            or ("legacy_status:" + legacy_status if legacy_status else "")
        ),
        retryable=status in {"FAILED_RETRYABLE", "TIMEOUT"},
        pages_completed=int(payload.get("pages_completed") or 0),
        response_digest=str(payload.get("response_digest") or ""),
        raw_response_ref=str(payload.get("raw_response_ref") or ""),
        latency_ms=float(payload.get("latency_ms") or 0.0),
        metadata={
            "legacy_status": legacy_status,
            "status_counts": dict(payload.get("status_counts") or {}),
            "normalized_record_count": int(payload.get("normalized_record_count") or 0),
            "cache_only": bool(payload.get("cache_only", False)),
        },
    )


__all__ = [
    "EvidenceAuthority",
    "EvidenceConfidence",
    "ProviderAttempt",
    "ProviderAttemptStatus",
    "provider_attempt_from_legacy",
]
