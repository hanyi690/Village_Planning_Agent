"""Canonical identity contracts for DATA-backed Evidence features."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceFeatureIdentity(BaseModel):
    """Identity for a generic DATA source record.

    This is the canonical identity on the V2 path.  A source feature may be
    unnamed and is never required to carry a cadastral BSM.  ``entity_refs``
    live on :class:`FeatureEvidenceRef` because one source record can be
    linked to multiple cognition entities during reconciliation.
    """

    model_config = ConfigDict(extra="forbid")

    canonical_name: str = ""
    entity_type: str = ""
    role: str = ""
    aliases: list[str] = Field(default_factory=list)
    source_feature_id: str = ""
    source_layer: str = ""
    geometry_digest: str = ""
    source_dataset_ref: str = ""
    source_snapshot_digest: str = ""
    crs: str = ""
    source_crs: str = ""
    normalized_crs: str = ""
    source_snapshot_ref: str = ""

class FeatureEvidenceRef(BaseModel):
    """A reference to a source feature; it never embeds executable geometry.

    ``geometry_ref`` is opaque until GROUND resolves it.  DATA references use
    ``resource:<dataset_ref>:<source_feature_ref>``.
    """

    model_config = ConfigDict(extra="forbid")

    identity: SourceFeatureIdentity
    entity_refs: list[str] = Field(default_factory=list)
    geometry_ref: str | None = None
    resource_ref: str = ""
    representation_refs: list[str] = Field(default_factory=list)
    source_snapshot_ref: str = ""
    normalized_crs: str = ""
    geometry_authority: Literal["data_resource_catalog", "none"] = "none"
    relation_refs: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    l1_fact_refs: list[str] = Field(default_factory=list)
    l1_snapshot_ref: str = ""
    selection_evidence: dict[str, float] = Field(default_factory=dict)
    source_authority_score: float = Field(default=0.0, ge=0.0, le=1.0)
    semantic_match_score: float = Field(default=0.0, ge=0.0, le=1.0)
    spatial_support_score: float = Field(default=0.0, ge=0.0, le=1.0)
    external_support_score: float = Field(default=0.0, ge=0.0, le=1.0)
    retrieval_score: float = Field(default=0.0, ge=0.0, le=1.0)
    selection_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


__all__ = [
    "SourceFeatureIdentity",
    "FeatureEvidenceRef",
]
