"""Typed facts emitted by the KG evidence boundary.

The KG may contain many RDF nodes for one source collection.  This contract
keeps the meaning of a returned number together with its collection, snapshot,
feature IDs, and counting basis so downstream L1/RAG/LLM code cannot mistake a
source-feature count for a business-object count.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class KGFactRecord(BaseModel):
    """One auditable, snapshot-scoped fact projected from the KG."""

    fact_id: str
    statement: str
    subject_scope: str
    predicate: str
    value: str | int | float | None = None
    unit: str = ""
    counting_basis: Literal[
        "source_feature", "business_object", "topology_edge", "derived_metric"
    ]
    semantic_group: str = ""
    source_collection_key: str = ""
    source_snapshot_ref: str = ""
    source_feature_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    geometry_kind: str = ""
    derivation: str = ""
    confidence: float = 0.0


__all__ = ["KGFactRecord"]
