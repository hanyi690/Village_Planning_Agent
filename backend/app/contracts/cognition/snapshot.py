"""Serializable World Model snapshot descriptor."""

from __future__ import annotations

from app.contracts.base import StrictContractModel


class SessionWorldModelSnapshot(StrictContractModel):
    snapshot_ref: str
    session_id: str
    version: int
    source_catalog_ref: str = ""
    source_catalog_digest: str = ""
    schema_mapping_ref: str = ""
    schema_mapping_digest: str = ""
    parent_snapshot_ref: str = ""
    parent_snapshot_digest: str = ""
    graph_digest: str
    current_world_digest: str = ""
    source_record_refs: tuple[str, ...] = ()
    entity_refs: tuple[str, ...] = ()
    representation_refs: tuple[str, ...] = ()
    assertion_refs: tuple[str, ...] = ()
    identity_binding_refs: tuple[str, ...] = ()
    planned_refs: tuple[str, ...] = ()
    data_dependency_graph_digest: str = ""


__all__ = ["SessionWorldModelSnapshot"]
