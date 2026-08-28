"""Contracts for the L1 semantic scope used by evidence retrieval.

L1 is the semantic bridge from report language to a bounded village/object
scope.  These models intentionally contain no geometry or BSM: those are
resolved later from the KG, bundle, and deterministic topology evidence.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.contracts.l1.l1_contracts import LocationScopeMention


class L1MentionContext(BaseModel):
    """One report-derived mention with its semantic and provenance context."""

    mention_ref: str
    mention: str
    normalized_name: str
    role: str = "unknown"
    aliases: list[str] = Field(default_factory=list)
    spatial_hint: str = ""
    related_mentions: list[str] = Field(default_factory=list)
    scope_mentions: list[LocationScopeMention] = Field(default_factory=list)
    source_report_ref: str = ""
    source_span: str = ""
    dimension_key: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class L1SemanticScope(BaseModel):
    """A bounded semantic scope linking report mentions to village context.

    A scope is deliberately pre-geometric.  ``scope_mentions`` and
    ``object_mentions`` are semantic inputs; later retrieval binds them to KG
    entities, bundle features, and topology relations.
    """

    scope_id: str
    village_mentions: list[str] = Field(default_factory=list)
    village_fact_refs: list[str] = Field(default_factory=list)
    scope_mentions: list[LocationScopeMention] = Field(default_factory=list)
    object_mentions: list[L1MentionContext] = Field(default_factory=list)
    relation_hints: list[dict[str, Any]] = Field(default_factory=list)
    source_observation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    geometry_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    unresolved_reasons: list[str] = Field(default_factory=list)
    query_trace: list[dict[str, Any]] = Field(default_factory=list)


__all__ = ["L1MentionContext", "L1SemanticScope"]
