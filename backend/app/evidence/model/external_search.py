"""External search evidence claims; read-only, cannot create planning objects."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import JsonObject, StrictContractModel


class ExternalClaimDraft(StrictContractModel):
    """A provider claim that must be normalized and deconflicted downstream.

    This model has no geometry, BSM, classification or planning fields; it can
    only ever be evidence, never an entity or a plan mutation.
    """

    claim_text: str
    source: str
    url: str = ""
    published_at: str = ""
    confidence: float = 0.0


class ExternalSearchEvidence(StrictContractModel):
    """Typed container for one external retrieval attempt."""

    claims: list[ExternalClaimDraft] = Field(default_factory=list)
    provider: str = ""
    request_id: str = ""
    query_purpose: str = ""
    source_domain: str = ""
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
    ] = "unresolved"
    latency_ms: int | None = None
    cost: JsonObject | None = None


__all__ = ["ExternalClaimDraft", "ExternalSearchEvidence"]
