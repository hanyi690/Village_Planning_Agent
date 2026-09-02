"""Typed authority, outcome, and receipt contracts for Evidence CAS replay."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.artifacts.ref import ArtifactRef


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_RETRIEVAL_ENGINE_VERSION = "evidence-retrieval-v2"


class EvidenceRetrievalBootstrapRefs(BaseModel):
    """Exact Evidence bootstrap artifacts consumed by a retrieval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_snapshot_ref: ArtifactRef
    external_observations_ref: ArtifactRef
    gap_ledger_ref: ArtifactRef


class EvidenceRetrievalAuthority(BaseModel):
    """Frozen workflow identity and upstream descriptors for a retrieval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    workflow_run_id: str = Field(min_length=1)
    branch_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    context_fingerprint: str = Field(min_length=1)
    data_catalog_ref: ArtifactRef
    data_catalog_digest: str
    data_snapshot_ref: ArtifactRef
    data_snapshot_digest: str
    world_model_artifact_ref: ArtifactRef
    world_model_snapshot_ref: str
    world_model_snapshot_digest: str
    evidence_snapshot_ref: ArtifactRef
    external_observations_ref: ArtifactRef
    external_cache_digest: str
    gap_ledger_ref: ArtifactRef
    world_model_mode: str
    engine: str = "evidence_application"
    engine_version: str = EVIDENCE_RETRIEVAL_ENGINE_VERSION
    cache_only_policy: dict[str, bool] = Field(
        default_factory=lambda: {"external": True}
    )


class EvidenceRetrievalOutcome(BaseModel):
    """Terminal retrieval state; only ``sufficient`` authorizes closure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal[
        "sufficient",
        "partial",
        "insufficient",
        "human_required",
        "failed",
    ]
    reason: str = ""
    reason_codes: tuple[str, ...] = ()


class EvidenceRetrievalReceipt(BaseModel):
    """Reference returned to callers after a write-once retrieval commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    retrieval_ref: ArtifactRef
    fingerprint: str
    dedup_hit: bool = False
    query_plan_ref: str = ""
    acquisition_receipt_ref: str = ""

    @field_validator("fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        if not _FINGERPRINT.fullmatch(str(value or "")):
            raise ValueError("retrieval fingerprint must be 64 lowercase hex characters")
        return value


__all__ = [
    "EvidenceRetrievalAuthority",
    "EvidenceRetrievalBootstrapRefs",
    "EVIDENCE_RETRIEVAL_ENGINE_VERSION",
    "EvidenceRetrievalOutcome",
    "EvidenceRetrievalReceipt",
]
