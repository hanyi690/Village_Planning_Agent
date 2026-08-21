"""Bounded evidence packet shared by retrieval, LLM selection, and planning."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.evidence.feature_identity_contracts import FeatureEvidenceRef


class SpatialRelationEvidence(BaseModel):
    relation_id: str
    subject: FeatureEvidenceRef
    predicate: str
    object: FeatureEvidenceRef
    metric_value: float | None = None
    metric_unit: str | None = None
    tolerance: float | None = None
    crs: str = "EPSG:4326"
    computation_method: str = ""
    provenance_refs: list[str] = Field(default_factory=list)


class EvidencePacket(ContractMeta):
    """Small, auditable retrieval result; full reports are excluded by default."""

    request: str
    query_fingerprint: str = ""
    bundle_snapshot_digest: str = ""
    kg_version: str = ""
    l1_snapshot_ref: str = ""
    l1_scope_refs: list[str] = Field(default_factory=list)
    candidate_refs: list[FeatureEvidenceRef] = Field(default_factory=list)
    candidate_total: int = Field(default=0, ge=0)
    candidate_offset: int = Field(default=0, ge=0)
    candidate_limit: int = Field(default=12, ge=1)
    candidates_truncated: bool = False
    next_candidate_offset: int | None = Field(default=None, ge=0)
    relation_evidence: list[SpatialRelationEvidence] = Field(default_factory=list)
    source_spans: list[str] = Field(default_factory=list)
    external_refs: list[str] = Field(default_factory=list)
    ambiguity_status: Literal["resolved", "multiple", "unresolved"] = "unresolved"
    sufficiency: Literal["sufficient", "partial", "insufficient"] = "insufficient"
    missing_evidence: list[str] = Field(default_factory=list)
    query_trace: list[dict[str, Any]] = Field(default_factory=list)


__all__ = ["SpatialRelationEvidence", "EvidencePacket"]
