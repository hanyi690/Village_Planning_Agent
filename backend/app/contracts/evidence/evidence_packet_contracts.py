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
    crs: str = ""
    computation_method: str = ""
    provenance_refs: list[str] = Field(default_factory=list)


class EvidencePacket(ContractMeta):
    """Small, auditable retrieval result; full reports are excluded by default."""

    request: str
    query_fingerprint: str = ""
    bundle_snapshot_digest: str = ""
    # DATA/World-Model lineage is explicit in V2; legacy packets may leave
    # these empty while their compatibility Bundle digest remains populated.
    data_snapshot_ref: str = ""
    data_snapshot_digest: str = ""
    world_model_snapshot_ref: str = ""
    world_model_snapshot_digest: str = ""
    kg_version: str = ""
    l1_snapshot_ref: str = ""
    l1_scope_refs: list[str] = Field(default_factory=list)
    candidate_refs: list[FeatureEvidenceRef] = Field(default_factory=list)
    candidate_total: int = Field(default=0, ge=0)
    # ``candidate_total`` counts source features/representations.  Identity
    # cardinality is separate because one WorldEntity may legitimately own a
    # point, several polygons, or many continuous road segments.
    candidate_identity_total: int = Field(default=0, ge=0)
    candidate_entity_refs: list[str] = Field(default_factory=list)
    identity_grouping: Literal[
        "world_entity",
        "mixed",
        "source_feature",
        "none",
    ] = "none"
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
