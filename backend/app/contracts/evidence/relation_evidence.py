"""Cross-boundary relation evidence contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.contracts.base import JsonObject, StrictContractModel


class RelationEvidence(StrictContractModel):
    """A directed, source-backed relation between two canonical entities."""

    subject_ref: str
    predicate: str
    object_ref: str
    inverse_predicate: str | None = None
    subject_type: str | None = None
    object_type: str | None = None
    spatial_scope: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    confidence: float
    query_trace: list[JsonObject] = Field(default_factory=list)


class DirectionalRelation(StrEnum):
    """Direction of a stored ``RelationEvidence`` triple."""

    DIRECT = "direct"
    INVERSE = "inverse"


__all__ = ["DirectionalRelation", "RelationEvidence"]
