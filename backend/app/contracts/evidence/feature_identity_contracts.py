"""Canonical identity contracts for multi-source bundle features."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


BsmKind = Literal["source", "synthetic", "unknown"]


class BundleFeatureIdentity(BaseModel):
    """Stable identity of one feature in one immutable bundle snapshot."""

    bundle_feature_bsm: str
    canonical_name: str = ""
    entity_type: str = ""
    role: str = ""
    aliases: list[str] = Field(default_factory=list)
    admin_code_12: str = ""
    sequence_code_8: str = ""
    source_feature_id: str = ""
    source_layer: str = ""
    source_bsm: str | None = None
    bsm_kind: BsmKind = "unknown"
    geometry_digest: str = ""
    bundle_snapshot_digest: str = ""
    crs: str = "EPSG:4326"


class FeatureEvidenceRef(BaseModel):
    """A reference to a bundle/KG feature; it never embeds executable geometry."""

    model_config = ConfigDict(extra="forbid")

    identity: BundleFeatureIdentity
    entity_refs: list[str] = Field(default_factory=list)
    geometry_ref: str | None = None
    geometry_authority: Literal["bundle", "none"] = "bundle"
    relation_refs: list[str] = Field(default_factory=list)
    related_parcel_bsms: list[str] = Field(default_factory=list)
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


__all__ = ["BsmKind", "BundleFeatureIdentity", "FeatureEvidenceRef"]
