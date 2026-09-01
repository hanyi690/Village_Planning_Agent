"""Canonical identity contracts for multi-source DATA features.

The generic source identity is authoritative for V2.  The Bundle-named model
below remains only so historical artifacts and explicit BSM compatibility
requests can still be read during the migration window.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


BsmKind = Literal["source", "synthetic", "unknown"]


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

    # Read-only compatibility views keep shared Evidence formatting code
    # total while making it impossible for generic DATA identities to carry a
    # fabricated cadastral key.  They are intentionally not serialized.
    @property
    def bundle_feature_bsm(self) -> str:
        return ""

    @property
    def bundle_snapshot_digest(self) -> str:
        return ""

    @property
    def source_bsm(self) -> str:
        return ""

    @property
    def bsm_kind(self) -> str:
        return "unknown"

    @property
    def admin_code_12(self) -> str:
        return ""

    @property
    def sequence_code_8(self) -> str:
        return ""


class BundleFeatureIdentity(BaseModel):
    """Stable identity of one feature in one immutable bundle snapshot."""

    # Compatibility field.  Generic DATA features deliberately leave this
    # empty and use source_feature_id/entity_ref/resource_ref instead.
    bundle_feature_bsm: str = ""
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
    # Generic DATA lineage fields.  The ``bundle_*`` names above remain only
    # for replaying legacy artifacts and stay empty on DATA-only paths.
    source_dataset_ref: str = ""
    source_snapshot_digest: str = ""
    bundle_snapshot_digest: str = ""
    crs: str = "EPSG:4326"


class FeatureEvidenceRef(BaseModel):
    """A reference to a source feature; it never embeds executable geometry.

    ``geometry_ref`` is opaque until GROUND resolves it.  Bundle references
    use ``bundle://feature/...`` while generic DATA references use
    ``resource:<dataset_ref>:<source_feature_ref>``.
    """

    model_config = ConfigDict(extra="forbid")

    # SourceFeatureIdentity is first so generic DATA payloads cannot be
    # silently coerced into the legacy BundleFeatureIdentity shape.  Legacy
    # payloads containing ``bundle_feature_bsm`` continue to validate through
    # the second union member during migration.
    identity: SourceFeatureIdentity | BundleFeatureIdentity
    entity_refs: list[str] = Field(default_factory=list)
    geometry_ref: str | None = None
    resource_ref: str = ""
    representation_refs: list[str] = Field(default_factory=list)
    source_snapshot_ref: str = ""
    normalized_crs: str = ""
    geometry_authority: Literal["bundle", "data_resource_catalog", "none"] = "none"
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


__all__ = [
    "BsmKind",
    "SourceFeatureIdentity",
    "BundleFeatureIdentity",
    "FeatureEvidenceRef",
]
