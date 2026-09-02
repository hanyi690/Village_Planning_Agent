"""Evidence contracts — exploration requests, sources, facts, and bundles."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.evidence.acquisition_contracts import (
    EvidenceAcquisitionReceipt,
    EvidenceObservationSnapshot,
    ProviderPageRecord,
)
from app.contracts.evidence.provider_attempt import ProviderAttempt
from app.contracts.evidence.proposal_contracts import EvidenceProposalBatch
from app.contracts.evidence.requirement_contracts import EvidenceCoverage, EvidenceRequirement
from app.contracts.evidence.retrieval_contracts import (
    EvidenceRetrievalOutcome,
    EvidenceRetrievalReceipt,
)


class ExplorationRequest(BaseModel):
    run_id: str
    request_type: str  # "evidence_gap" | "fact_check" | "spatial_lookup"
    query: str
    context_refs: list[str] = []
    evidence_gaps_to_resolve: list[str] = []

    # Wave C enrichment
    stage: str = ""  # "L1" | "L2" | "L3"
    dimension_key: str = ""
    query_purpose: str = ""  # "context_injection" | "fact_check" | "gap_resolution"
    questions: list[str] = []
    required_facts: list[str] = []
    entity_scope: list[str] = []  # ["parcels", "facilities", "roads", "waters", ...]
    # Internal routing marker: inferred scopes may guide candidate recall, but
    # an originally unscoped query must still cover all project-owned sources.
    project_wide: bool = False
    candidate_offset: int = Field(default=0, ge=0)
    candidate_limit: int = Field(default=12, ge=1, le=64)
    project_cognition_digest: str = ""
    project_scope: dict[str, Any] = Field(default_factory=dict)
    requirements: list[EvidenceRequirement] = Field(default_factory=list)


class EvidenceSource(BaseModel):
    source_type: str  # "report" | "gis_layer" | "kg" | "external" | "api"
    reference: str
    retrieved_at: str = ""
    confidence: float = 1.0
    # These fields are the source-boundary metadata consumed by planning LLMs
    # and the frontend.  ``source_type`` answers where a row came from;
    # ``evidence_role`` and ``authority`` answer what the row is allowed to
    # support.  They deliberately do not imply geometry authority for reports,
    # RAG or external search.
    evidence_role: str = "context"
    authority: str = "advisory"
    availability: str = "available"
    supports: list[str] = []
    snapshot_ref: str = ""


class EvidenceFact(BaseModel):
    fact_id: str = ""
    statement: str
    confidence: float = 1.0
    source_refs: list[str] = []
    spatial_refs: list[str] = []
    fact_type: str = "statement"
    fields: dict[str, str] = {}
    evidence_span: str = ""
    source_locator: str = ""
    support_relation: str = "quotation"
    support_relations: list[str] = []
    related_fact_refs: list[str] = []
    status: str = "verified"
    evidence_role: str = ""
    source_kind: str = ""
    spatial_granularity: str = "none"
    planning_use: str = "context"

    @model_validator(mode="after")
    def _stable_fact_id(self) -> "EvidenceFact":
        if self.fact_id:
            return self
        material = {
            "statement": self.statement,
            "source_refs": sorted(set(self.source_refs)),
            "spatial_refs": sorted(set(self.spatial_refs)),
            "fact_type": self.fact_type,
            "fields": self.fields,
            "evidence_span": self.evidence_span,
            "source_locator": self.source_locator,
            "support_relation": self.support_relation,
            "support_relations": sorted(set(self.support_relations)),
            "related_fact_refs": sorted(set(self.related_fact_refs)),
            "evidence_role": self.evidence_role,
            "source_kind": self.source_kind,
            "spatial_granularity": self.spatial_granularity,
            "planning_use": self.planning_use,
        }
        digest = hashlib.sha256(
            json.dumps(
                material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:24]
        token = re.sub(
            r"[^a-z0-9_]+",
            "_",
            str(self.fact_type or "statement").casefold(),
        ).strip("_") or "statement"
        if self.fact_type == "external_map_observation":
            provider = re.sub(
                r"[^a-z0-9_]+",
                "_",
                str(self.fields.get("provider") or "provider").casefold(),
            ).strip("_") or "provider"
            stage = re.sub(
                r"[^a-z0-9_]+",
                "_",
                str(self.fields.get("stage") or "stage").casefold(),
            ).strip("_") or "stage"
            self.fact_id = f"evidence.observation.{provider}.{stage}.{digest}"
        else:
            self.fact_id = f"evidence.fact.{token}.{digest}"
        return self


class EvidenceConflict(BaseModel):
    """Auditable relationship between facts returned by different sources."""

    relation: str
    fact_refs: list[str] = []
    reason: str
    subject_scope: str = ""
    counting_bases: list[str] = []


class EvidenceGapResolution(BaseModel):
    gap_id: str
    resolution: str
    resolved_by: str = ""
    evidence_ref: str = ""


class EvidenceBundle(ContractMeta):
    request: str
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    confidence: float = 0.0
    unresolved: list[str] = []
    conflicts: list[EvidenceConflict] = []
    provenance: "Provenance | None" = None


class SpatialCognitionEvidence(BaseModel):
    """KG + bundle spatial cognition, separate from factual evidence."""

    village_overview: str = ""
    spatial_pattern: str = ""
    constraint_coverage: str = ""
    topology_facts: list[str] = []
    entity_annotations: list[str] = []
    kg_confidence: float = 0.0


class ExplorationResult(BaseModel):
    """retrieve_evidence return type - bundle + optional spatial cognition."""

    evidence_bundle: "EvidenceBundle"
    spatial_cognition: "SpatialCognitionEvidence | None" = None
    evidence_packet: EvidencePacket | None = None
    coverage: EvidenceCoverage | None = None
    outcome: EvidenceRetrievalOutcome | None = None
    receipt: EvidenceRetrievalReceipt | None = None
    acquisition_receipt: EvidenceAcquisitionReceipt | None = None
    observation_snapshot: EvidenceObservationSnapshot | None = None
    provider_attempts: tuple[ProviderAttempt, ...] = ()
    page_records: tuple[ProviderPageRecord, ...] = ()
    proposal_batch: EvidenceProposalBatch | None = None


__all__ = [
    "ExplorationRequest",
    "EvidenceSource",
    "EvidenceFact",
    "EvidenceConflict",
    "EvidenceGapResolution",
    "EvidenceBundle",
    "SpatialCognitionEvidence",
    "ExplorationResult",
]
