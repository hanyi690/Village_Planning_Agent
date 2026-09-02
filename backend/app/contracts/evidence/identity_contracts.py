"""Evidence-first identity contracts for L1 place and facility grounding."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.l1.l1_contracts import LocationScopeMention
from app.contracts.ground.spatial_reference_contracts import SearchScopeRef

GeometryGranularity = Literal[
    "exact_feature", "feature_set", "parcel_set", "settlement", "village_scope", "none"
]
ResolutionStatus = Literal[
    "exact_feature",
    "feature_set",
    "inferred_scope",
    "name_only",
    "ambiguous",
    "unresolved",
    "not_applicable",
    "resolved",
]
IdentityResolutionStatus = Literal[
    "resolved", "ambiguous", "unresolved", "not_applicable"
]
RelativeLocationStatus = Literal[
    "none", "bound", "ambiguous", "unresolved"
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
    work_item_ref: str = ""
    source_mention_refs: list[str] = Field(default_factory=list)
    dimension_keys: list[str] = Field(default_factory=list)
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
    location_relation: str = ""
    relation_mentions: list[str] = Field(default_factory=list)
    scope_mentions: list[LocationScopeMention] = Field(default_factory=list)
    scope_refs: list[str] = Field(default_factory=list)
    temporal_status: str = "current"
    confidence: float = 0.0
    extraction_method: str = "l1"
    geometry_ref: str | None = None


class GroundedEntityBinding(BaseModel):
    """A provenance-preserving binding from mentions to a canonical entity."""

    binding_id: str
    mention_ref: str
    canonical_entity_ref: str = ""
    identity_status: IdentityResolutionStatus = "unresolved"
    candidate_entity_refs: list[str] = Field(default_factory=list)
    observation_refs: list[str] = Field(default_factory=list)
    status: ResolutionStatus = "unresolved"
    geometry_granularity: GeometryGranularity = "none"
    geometry_ref: str | None = None
    geometry_refs: list[str] = Field(default_factory=list)
    representation_refs: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    entity_part_refs: list[str] = Field(default_factory=list)
    source_feature_ids: list[str] = Field(default_factory=list)
    candidate_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    relation_evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainty_reason: str = ""
    query_trace: list[dict] = Field(default_factory=list)
    search_scope: SearchScopeRef | None = None
    world_model_snapshot_ref: str = ""
    world_model_snapshot_digest: str = ""
    location_expression_ref: str = ""
    location_expression_status: RelativeLocationStatus = "none"
    spatial_relation: str = ""
    anchor_entity_refs: list[str] = Field(default_factory=list)
    anchor_work_item_refs: list[str] = Field(default_factory=list)
    distance_hint: str = ""

    @model_validator(mode="after")
    def normalize_identity_projection(self) -> "GroundedEntityBinding":
        candidates = list(dict.fromkeys(
            str(value).strip()
            for value in (
                *self.candidate_entity_refs,
                self.canonical_entity_ref,
            )
            if str(value).strip()
        ))
        self.candidate_entity_refs = candidates
        if self.status == "not_applicable":
            self.identity_status = "not_applicable"
        elif self.canonical_entity_ref and len(candidates) == 1:
            self.identity_status = "resolved"
        elif len(candidates) > 1 or self.status == "ambiguous":
            self.identity_status = "ambiguous"
        else:
            self.identity_status = "unresolved"
        if self.identity_status == "resolved" and not self.canonical_entity_ref:
            raise ValueError("resolved identity requires canonical_entity_ref")
        if self.canonical_entity_ref and self.canonical_entity_ref not in candidates:
            raise ValueError("canonical entity must belong to identity candidates")
        self.anchor_entity_refs = list(dict.fromkeys(
            str(value).strip()
            for value in self.anchor_entity_refs
            if str(value).strip()
        ))
        self.anchor_work_item_refs = list(dict.fromkeys(
            str(value).strip()
            for value in self.anchor_work_item_refs
            if str(value).strip()
        ))
        if self.location_expression_status != "none" and (
            not self.location_expression_ref or not self.spatial_relation
        ):
            raise ValueError(
                "relative location requires expression and relation"
            )
        if self.location_expression_status == "bound" and (
            not self.anchor_entity_refs
        ):
            raise ValueError(
                "bound relative location requires expression, relation, and anchor entity"
            )
        return self


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
    source_world_model_snapshot_ref: str = ""
    source_world_model_snapshot_digest: str = ""
    status_counts: dict[str, int] = Field(default_factory=dict)
    relative_location_status_counts: dict[str, int] = Field(
        default_factory=dict
    )


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


__all__ = [
    "GeometryGranularity", "ResolutionStatus", "IdentityResolutionStatus",
    "RelativeLocationStatus",
    "EvidenceObservation",
    "GroundedEntityBinding", "EvidenceObservationSnapshot",
    "GroundedEntityBindingSnapshot",
    "SourceBindingMode", "SourceMembership", "SourceOperation",
    "SourceFeatureSetBinding",
]
