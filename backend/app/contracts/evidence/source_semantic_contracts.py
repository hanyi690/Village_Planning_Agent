"""Closed-set source-label semantics used by spatial identity binding."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.contract_meta import ContractMeta


class SourceFeatureDescriptor(BaseModel):
    """Immutable source metadata exposed to semantic classification."""

    model_config = ConfigDict(extra="forbid")

    source_feature_id: str
    raw_label: str = ""
    layer_key: str
    geometry_kind: str
    minimal_properties: dict[str, str] = Field(default_factory=dict)


class SourceSemanticCandidate(BaseModel):
    """One meaning backed by the current L1/KG snapshot."""

    model_config = ConfigDict(extra="forbid")

    candidate_ref: str
    display_phrase: str
    origin: Literal["l1_fact", "kg_snapshot", "canonical_exact"]
    supporting_fact_refs: list[str] = Field(min_length=1)
    optional_kg_concept_ref: str = ""
    compatible_layers: list[str] = Field(default_factory=list)
    compatible_geometry_kinds: list[str] = Field(default_factory=list)
    supporting_attributes: dict[str, str] = Field(default_factory=dict)


class SourceFeatureSemanticProposal(BaseModel):
    """Model output for one source item; null means explicit abstention."""

    model_config = ConfigDict(extra="forbid")

    source_feature_id: str
    candidate_ref: str | None = None
    supporting_fact_refs: list[str] = Field(default_factory=list)


class SourceFeatureSemanticProposalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposals: list[SourceFeatureSemanticProposal] = Field(default_factory=list)


class SourceFeatureSemanticDecision(BaseModel):
    """Verified semantic overlay; raw source identity remains untouched."""

    model_config = ConfigDict(extra="forbid")

    source_feature_id: str
    raw_label: str
    semantic_type: str = ""
    status: Literal["accepted", "ambiguous", "unresolved"]
    authority: Literal["canonical_exact", "inferred_current"] = "inferred_current"
    candidate_ref: str = ""
    optional_kg_concept_ref: str = ""
    supporting_fact_refs: list[str] = Field(default_factory=list)
    proposal_digests: list[str] = Field(default_factory=list)
    reason: str = ""


class SourceSemanticClassificationSnapshot(ContractMeta):
    """Persisted, snapshot-scoped source semantic decisions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    source_snapshot_ref: str
    source_snapshot_digest: str
    l1_fact_fingerprint: str
    vocabulary_fingerprint: str
    prompt_version: str
    model_id: str
    effective_temperature: float = 0.0
    normalized_input_digest: str = ""
    raw_output_digests: list[str] = Field(default_factory=list)
    verifier_findings: list[str] = Field(default_factory=list)
    decisions: list[SourceFeatureSemanticDecision] = Field(default_factory=list)
    fingerprint: str


__all__ = [
    "SourceFeatureDescriptor",
    "SourceSemanticCandidate",
    "SourceFeatureSemanticProposal",
    "SourceFeatureSemanticProposalBatch",
    "SourceFeatureSemanticDecision",
    "SourceSemanticClassificationSnapshot",
]
