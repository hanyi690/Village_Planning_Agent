"""Persisted, self-contained Evidence retrieval artifact contract."""

from __future__ import annotations

import re

from pydantic import Field, field_validator, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    ExplorationRequest,
    SpatialCognitionEvidence,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.evidence.acquisition_contracts import (
    EvidenceAcquisitionReceipt,
    EvidenceObservationSnapshot,
    ProviderPageRecord,
)
from app.contracts.evidence.requirement_contracts import EvidenceCoverage
from app.contracts.evidence.proposal_contracts import EvidenceProposalBatch
from app.contracts.evidence.retrieval_contracts import (
    EvidenceRetrievalAuthority,
    EvidenceRetrievalBootstrapRefs,
    EvidenceRetrievalOutcome,
)
from app.contracts.evidence.provider_attempt import (
    EvidenceAuthority,
    EvidenceConfidence,
    ProviderAttempt,
)


_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class EvidenceRetrievalArtifact(ContractMeta):
    """One replayable retrieval result, intentionally without its own ref."""

    fingerprint: str
    canonical_request: ExplorationRequest
    evidence_bundle: EvidenceBundle
    evidence_packet: EvidencePacket
    coverage: EvidenceCoverage
    outcome: EvidenceRetrievalOutcome
    authority: EvidenceRetrievalAuthority
    bootstrap_refs: EvidenceRetrievalBootstrapRefs
    query_plan_ref: str = ""
    observation_snapshot: EvidenceObservationSnapshot | None = None
    acquisition_receipt: EvidenceAcquisitionReceipt | None = None
    page_records: tuple[ProviderPageRecord, ...] = ()
    spatial_cognition: SpatialCognitionEvidence | None = None
    provider_attempts: tuple[ProviderAttempt, ...] = ()
    confidence_components: EvidenceConfidence = Field(
        default_factory=EvidenceConfidence
    )
    evidence_authority: EvidenceAuthority = Field(
        default_factory=EvidenceAuthority
    )
    proposal_batch: EvidenceProposalBatch | None = None

    @model_validator(mode="after")
    def _validate_round_lineage(self) -> "EvidenceRetrievalArtifact":
        if self.proposal_batch is None:
            return self
        round_contract = self.authority.cognition_round
        if (
            self.proposal_batch.round_id != round_contract.round_id
            or self.proposal_batch.wm_epoch != round_contract.wm_epoch
            or self.proposal_batch.parent_world_model_snapshot_ref
            != round_contract.parent_world_model_snapshot_ref
            or self.proposal_batch.parent_world_model_digest
            != round_contract.parent_world_model_snapshot_digest
            or self.proposal_batch.requirement_set_digest
            != round_contract.requirement_set_digest
            or round_contract.proposal_fingerprint
            != self.proposal_batch.proposal_fingerprint
        ):
            raise ValueError("retrieval artifact proposal batch is outside CognitionRound")
        return self

    @field_validator("fingerprint")
    @classmethod
    def _validate_fingerprint(cls, value: str) -> str:
        if not _FINGERPRINT.fullmatch(str(value or "")):
            raise ValueError("retrieval fingerprint must be 64 lowercase hex characters")
        return value


__all__ = ["EvidenceRetrievalArtifact"]
