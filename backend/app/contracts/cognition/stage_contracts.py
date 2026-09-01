"""Bounded World Model/KG bootstrap product."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from app.contracts.artifacts.contract_meta import ContractMeta
from app.contracts.artifacts.ref import ArtifactRef


class CognitionGapRecord(ContractMeta):
    """A bounded semantic ambiguity queued for Evidence/Cognition recovery."""

    stage: Literal["kg"] = "kg"
    gap_ref: str
    subject_refs: tuple[str, ...] = ()
    subject_count: int = 0
    subject_digest: str = ""
    mapping_decision_ref: str = ""
    source_catalog_digest: str = ""
    missing_fields: tuple[str, ...] = ()
    reason: str
    earliest_resolution_stage: Literal["evidence", "cognition", "human"] = "evidence"
    recovery_pointer: str = ""


class CognitionStageSnapshot(ContractMeta):
    """Summary of the KG-backed World Model for one DATA snapshot."""

    stage: Literal["kg"] = "kg"
    status: Literal["ready", "blocked"] = "ready"
    world_model_ref: str = ""
    world_model_snapshot_ref: str = ""
    world_model_snapshot_digest: str = ""
    source_catalog_ref: str = ""
    source_catalog_digest: str = ""
    schema_mapping_ref: str = ""
    schema_mapping_digest: str = ""
    version: int = 0
    entity_count: int = 0
    entity_part_count: int = 0
    observed_entity_count: int = 0
    source_local_entity_count: int = 0
    accepted_semantic_entity_count: int = 0
    unresolved_entity_count: int = 0
    ambiguous_entity_count: int = 0
    representation_count: int = 0
    available_representation_count: int = 0
    unresolved_representation_count: int = 0
    assertion_count: int = 0
    capability_count: int = 0
    collection_profile_count: int = 0
    schema_decision_count: int = 0
    accepted_schema_decision_count: int = 0
    unresolved_schema_decision_count: int = 0
    gap_count: int = 0
    diagnostics: tuple[str, ...] = ()
    gap_refs: tuple[str, ...] = ()
    gaps: tuple[CognitionGapRecord, ...] = ()


class L1WorldProjectionSnapshot(ContractMeta):
    """Receipt for committing L1 identity cognition into the World Model.

    Observation and binding snapshots remain replay/audit sidecars.  Later
    planning stages validate this receipt and query the bounded WorldModelPort
    projection; they do not deserialize those complete sidecars into prompts.
    """

    stage: Literal["l1_identity_ground"] = "l1_identity_ground"
    status: Literal["ready", "partial"] = "ready"
    l1_snapshot_artifact_ref: ArtifactRef
    observation_artifact_ref: ArtifactRef
    binding_artifact_ref: ArtifactRef
    source_world_model_artifact_ref: ArtifactRef
    resulting_world_model_artifact_ref: ArtifactRef
    source_world_model_snapshot_ref: str
    source_world_model_snapshot_digest: str
    resulting_world_model_snapshot_ref: str
    resulting_world_model_snapshot_digest: str
    resulting_world_model_version: int
    identity_projection_fingerprint: str
    source_context_ref: dict[str, str] = Field(default_factory=dict)
    resulting_context_ref: dict[str, str] = Field(default_factory=dict)
    source_context_fingerprint: str = ""
    resulting_context_fingerprint: str = ""
    work_item_count: int = 0
    source_mention_count: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    relative_location_status_counts: dict[str, int] = Field(
        default_factory=dict
    )
    gap_refs: tuple[str, ...] = ()
    query_filters: tuple[str, ...] = (
        "mention_ref",
        "entity_ref",
        "status",
        "work_item_ref",
        "dimension_ref",
        "scope_ref",
    )
    query_hard_limit: int = 64


__all__ = [
    "CognitionGapRecord",
    "CognitionStageSnapshot",
    "L1WorldProjectionSnapshot",
]
