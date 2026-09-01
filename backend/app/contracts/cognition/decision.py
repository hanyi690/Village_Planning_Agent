"""Auditable closed-set schema understanding decisions.

The contracts are deliberately collection-scoped.  A large GIS source may
contain thousands of records with one schema; asking an LLM to repeat the
same decision for every feature is both wasteful and impossible to audit.
Profiles therefore summarize bounded physical observations, while decisions
only reference profile/field rows and a closed candidate vocabulary.
"""

from __future__ import annotations

from typing import Literal

from app.contracts.base import StrictContractModel


# Bump this whenever the deterministic profiling, candidate construction, or
# verifier contract changes.  It makes reuse of an older mapping snapshot
# fail closed instead of trusting a named ref alone.
SCHEMA_MAPPING_CODE_CONTRACT_VERSION = "schema-mapping-code-v1"


class SourceFieldProfile(StrictContractModel):
    field_name: str
    physical_types: tuple[str, ...] = ()
    non_null_count: int = 0
    distinct_sample_count: int = 0
    sample_values: tuple[str, ...] = ()


class SourceCollectionProfile(StrictContractModel):
    collection_ref: str
    dataset_ref: str
    layer_ref: str = ""
    geometry_kinds: tuple[str, ...] = ()
    feature_count: int = 0
    source_record_refs: tuple[str, ...] = ()
    source_feature_refs: tuple[str, ...] = ()
    field_profiles: tuple[SourceFieldProfile, ...] = ()
    schema_digest: str = ""
    content_digest: str = ""


class SchemaMappingProposal(StrictContractModel):
    collection_ref: str
    field_name: str = ""
    candidate_property_ref: str | None = None
    candidate_concept_ref: str | None = None
    representation_role_ref: str | None = None
    confidence: float = 0.0


class SchemaMappingProposalBatch(StrictContractModel):
    """One bounded flat provider page; never a whole-source nested result."""

    proposals: tuple[SchemaMappingProposal, ...] = ()


class SchemaMappingDecision(StrictContractModel):
    decision_ref: str = ""
    collection_ref: str
    field_name: str = ""
    candidate_property_ref: str = ""
    candidate_concept_ref: str = ""
    representation_role_ref: str = ""
    status: Literal["accepted", "ambiguous", "unresolved", "rejected"] = "unresolved"
    confidence: float = 0.0
    candidate_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    reason: str = ""
    source_feature_count: int = 0
    source_feature_digest: str = ""
    source_feature_refs: tuple[str, ...] = ()


class SourceSemanticMappingSnapshot(StrictContractModel):
    source_snapshot_ref: str
    source_snapshot_digest: str
    profile_digest: str = ""
    input_digest: str
    candidate_digest: str
    prompt_version: str = ""
    code_contract_version: str = ""
    model_id: str = "deterministic"
    raw_output_digest: str = ""
    verifier_findings: tuple[str, ...] = ()
    collection_profiles: tuple[SourceCollectionProfile, ...] = ()
    decisions: tuple[SchemaMappingDecision, ...] = ()
    decision_fingerprint: str = ""
    mapping_fingerprint: str = ""


__all__ = [
    "SchemaMappingDecision",
    "SchemaMappingProposal",
    "SchemaMappingProposalBatch",
    "SourceCollectionProfile",
    "SourceFieldProfile",
    "SourceSemanticMappingSnapshot",
    "SCHEMA_MAPPING_CODE_CONTRACT_VERSION",
]
