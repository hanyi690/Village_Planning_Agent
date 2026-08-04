"""Evidence contracts — exploration requests, sources, facts, and bundles."""

from __future__ import annotations

from pydantic import BaseModel

from .contract_meta import ContractMeta
from .provenance import Provenance


class ExplorationRequest(BaseModel):
    run_id: str
    request_type: str  # "evidence_gap" | "fact_check" | "spatial_lookup"
    query: str
    context_refs: list[str] = []
    evidence_gaps_to_resolve: list[str] = []


class EvidenceSource(BaseModel):
    source_type: str  # "report" | "gis_layer" | "kg" | "external" | "api"
    reference: str
    retrieved_at: str = ""
    confidence: float = 1.0


class EvidenceFact(BaseModel):
    statement: str
    confidence: float = 1.0
    source_refs: list[str] = []
    spatial_refs: list[str] = []


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
    provenance: "Provenance | None" = None

__all__ = [
    "ExplorationRequest",
    "EvidenceSource",
    "EvidenceFact",
    "EvidenceGapResolution",
    "EvidenceBundle",
]