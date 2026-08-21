"""Evidence contracts — exploration requests, sources, facts, and bundles."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.provenance import Provenance
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket


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
    statement: str
    confidence: float = 1.0
    source_refs: list[str] = []
    spatial_refs: list[str] = []
    fact_type: str = "statement"
    fields: dict[str, str] = {}
    feature_bsm: str = ""
    related_parcel_bsms: list[str] = []
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
