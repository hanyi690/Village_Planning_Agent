"""Derived relations container over the single-owner RelationEvidence model."""

from __future__ import annotations

from pydantic import Field

from app.contracts.base import JsonObject, StrictContractModel
from app.contracts.evidence.relation_evidence import RelationEvidence


class DerivedRelations(StrictContractModel):
    """Typed container of directed relations plus their query trace."""

    relations: list[RelationEvidence] = Field(default_factory=list)
    query_trace: list[JsonObject] = Field(default_factory=list)


__all__ = ["DerivedRelations"]
