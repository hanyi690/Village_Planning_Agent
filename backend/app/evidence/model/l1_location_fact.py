"""Typed L1 place mention feeding the PlaceEvidenceIndex."""

from __future__ import annotations

from pydantic import Field

from .base import StrictContractModel


class L1LocationFact(StrictContractModel):
    """A typed L1 place mention; semantic evidence, never spatial truth.

    Feeds ``PlaceEvidenceIndexService.resolve`` and maps onto
    ``PlaceResolutionCandidate`` in the resolution chain.
    """

    entity_ref: str
    entity_type: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    geometry_ref: str | None = None


__all__ = ["L1LocationFact"]
