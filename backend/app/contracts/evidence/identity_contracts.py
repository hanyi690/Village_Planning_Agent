"""Evidence-first identity contracts for L1 place and facility grounding."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.l1.l1_contracts import LocationScopeMention
from app.contracts.ground.spatial_reference_contracts import SearchScopeRef

GeometryGranularity = Literal[
    "exact_feature", "parcel_set", "settlement", "village_scope", "none"
]
ResolutionStatus = Literal[
    "exact_feature",
    "feature_set",
    "inferred_scope",
    "name_only",
    "ambiguous",
    "unresolved",
    # Read compatibility for pre-rename artifacts.
    "resolved",
]
SourceBindingMode = Literal[
    "all_in_scope",
    "explicit_subset",
    "query_subset",
    "semantic_fact_subset",
]
SourceMembership = Literal["required", "alternative", "eligible_subset"]
SourceOperation = Literal["preserve", "harden", "repair", "widen", "reference"]


class EvidenceObservation(BaseModel):
    """One source mention; it is not itself a canonical GIS entity."""

    observation_id: str
    mention: str
    normalized_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    observed_type: str = ""
    role: str = "unknown"
    source_document_ref: str = ""
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_span: str = ""
    report_section: str = ""
    spatial_hint: str = ""
    relation_mentions: list[str] = Field(default_factory=list)
    scope_mentions: list[LocationScopeMention] = Field(default_factory=list)
    temporal_status: str = "current"
    confidence: float = 0.0
    extraction_method: str = "l1"
    geometry_ref: str | None = None


class GroundedEntityBinding(BaseModel):
    """A provenance-preserving binding from mentions to a canonical entity."""

    binding_id: str
    mention_ref: str
    canonical_entity_ref: str = ""
    observation_refs: list[str] = Field(default_factory=list)
    status: ResolutionStatus = "unresolved"
    geometry_granularity: GeometryGranularity = "none"
    geometry_ref: str | None = None
    source_feature_ids: list[str] = Field(default_factory=list)
    source_bsms: list[str] = Field(default_factory=list)
    candidate_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    relation_evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainty_reason: str = ""
    query_trace: list[dict] = Field(default_factory=list)
    search_scope: SearchScopeRef | None = None


class EvidenceObservationSnapshot(ContractMeta):
    """Durable L1 observation input for grounding and resume."""

    schema_version: Literal["1.0"] = "1.0"
    observations: list[EvidenceObservation] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    parent_digest: str = ""


class GroundedEntityBindingSnapshot(ContractMeta):
    """Durable mention-to-entity decisions consumed by later stages."""

    schema_version: Literal["1.0"] = "1.0"
    bindings: list[GroundedEntityBinding] = Field(default_factory=list)
    observation_snapshot_ref: str = ""
    parent_digest: str = ""


class SourceFeatureSetBinding(BaseModel):
    """Audited membership of one planning target in one source collection."""

    binding_id: str
    target_id: str
    source_collection_key: str
    source_snapshot_ref: str
    source_feature_digest: str
    source_feature_ids: list[str] = Field(min_length=1)
    binding_mode: SourceBindingMode
    membership: SourceMembership = "required"
    operation: SourceOperation
    source_fact_refs: list[str] = Field(min_length=1)
    source_semantic_decision_refs: list[str] = Field(default_factory=list)

    @classmethod
    def canonical_ids(cls, values: list[str]) -> list[str]:
        return sorted({str(item).strip() for item in values if str(item).strip()})

    def model_post_init(self, __context: object) -> None:
        self.source_feature_ids = self.canonical_ids(self.source_feature_ids)
        self.source_fact_refs = self.canonical_ids(self.source_fact_refs)
        self.source_semantic_decision_refs = self.canonical_ids(
            self.source_semantic_decision_refs
        )


def infer_geometry_granularity(
    geometry_ref: str | None,
    *,
    entity_ref: str = "",
    source_bsms: list[str] | None = None,
) -> GeometryGranularity:
    """Infer only safe coarse classes from existing grounding metadata."""

    geometry = str(geometry_ref or "").strip()
    if geometry.startswith("village_anchor:") or geometry in {
        "bundled:coarse", "bundled:coarse_scope",
    }:
        return "village_scope"
    if entity_ref and geometry:
        return "exact_feature"
    if source_bsms:
        return "parcel_set"
    return "none"


__all__ = [
    "GeometryGranularity", "ResolutionStatus", "EvidenceObservation",
    "GroundedEntityBinding", "EvidenceObservationSnapshot",
    "GroundedEntityBindingSnapshot",
    "SourceBindingMode", "SourceMembership", "SourceOperation",
    "SourceFeatureSetBinding",
    "infer_geometry_granularity",
]
