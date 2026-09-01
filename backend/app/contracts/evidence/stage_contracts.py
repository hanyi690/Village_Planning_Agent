"""Evidence bootstrap/readiness contract.

Evidence retrieval itself is demand-driven and can be invoked by every
planning layer.  The bootstrap product only proves that its DATA/KG inputs
and the cache/text adapters are available; it never claims a requirement was
substantiated and never contains geometry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.evidence.external_observation_contracts import (
    ExternalObservationSnapshot,
)
from app.contracts.evidence.provider_attempt import (
    EvidenceAuthority,
    EvidenceConfidence,
    ProviderAttempt,
)


class EvidenceGapScheduleRecord(BaseModel):
    """Flat, bounded scheduler row carried across stage boundaries."""

    model_config = ConfigDict(extra="forbid")

    stage: Literal["evidence"] = "evidence"
    gap_ref: str
    producer_stage: str = ""
    subject_refs: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    source_digest: str = ""
    earliest_resolution_stage: str = "evidence"
    deferred_until: str = ""
    allowed_sources: tuple[str, ...] = ()
    retrieval_capability: str = ""
    status: Literal[
        "open",
        "ready_for_retrieval",
        "resolved",
        "not_available",
        "requires_human_confirmation",
    ] = "open"
    evidence_refs: tuple[str, ...] = ()
    failure_reason: str = ""
    recovery_pointer: str = ""


class EvidenceGapLedger(ContractMeta):
    """Immutable evidence-gap input published independently of readiness."""

    stage: Literal["evidence"] = "evidence"
    source_catalog_digest: str = ""
    world_model_snapshot_digest: str = ""
    upstream_gap_refs: tuple[str, ...] = ()
    gap_rows: tuple[EvidenceGapScheduleRecord, ...] = ()
    provider_attempts: tuple[ProviderAttempt, ...] = ()
    confidence_components: EvidenceConfidence = Field(
        default_factory=EvidenceConfidence
    )
    authority: EvidenceAuthority = Field(default_factory=EvidenceAuthority)


class EvidenceExternalObservationSnapshot(ContractMeta):
    """Cache-only external observations frozen for one Evidence bootstrap."""

    stage: Literal["evidence"] = "evidence"
    cache_only: Literal[True] = True
    cache_digest: str = ""
    snapshot: ExternalObservationSnapshot
    provider_attempts: tuple[ProviderAttempt, ...] = ()


class EvidenceStageSnapshot(ContractMeta):
    """Bounded readiness summary consumed by L1 and later evidence calls."""

    stage: Literal["evidence"] = "evidence"
    status: Literal["ready", "blocked"] = "ready"
    # These are the exact immutable DATA/KG descriptors consumed by Evidence.
    # The legacy string fields below remain as business snapshot identifiers;
    # they are not authority references and must never be used for replay.
    data_catalog_artifact_ref: ArtifactRef
    data_snapshot_artifact_ref: ArtifactRef
    world_model_artifact_ref: ArtifactRef
    data_snapshot_ref: str = ""
    data_snapshot_digest: str = ""
    data_artifact_ref: str = ""
    source_catalog_ref: str = ""
    source_catalog_digest: str = ""
    world_model_snapshot_ref: str = ""
    world_model_snapshot_digest: str = ""
    schema_mapping_artifact_ref: str = ""
    schema_mapping_digest: str = ""
    source_families: tuple[str, ...] = ()
    capability_refs: tuple[str, ...] = ()
    external_cache_digest: str = ""
    external_cache_complete: bool = False
    external_observations_ref: ArtifactRef | None = None
    gap_ledger_ref: ArtifactRef | None = None
    external_status_counts: dict[str, int] = Field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    gap_refs: tuple[str, ...] = ()
    upstream_gap_refs: tuple[str, ...] = ()
    scheduled_gap_count: int = 0
    immediate_supplement_count: int = 0
    unresolved_gap_count: int = 0
    gap_rows: tuple[EvidenceGapScheduleRecord, ...] = ()
    provider_attempts: tuple[ProviderAttempt, ...] = ()
    confidence_components: EvidenceConfidence = Field(
        default_factory=EvidenceConfidence
    )
    authority: EvidenceAuthority = Field(default_factory=EvidenceAuthority)


__all__ = [
    "EvidenceExternalObservationSnapshot",
    "EvidenceGapLedger",
    "EvidenceGapScheduleRecord",
    "EvidenceStageSnapshot",
]
