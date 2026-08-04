"""Gazetteer contracts - lightweight typed shapes shared across port boundaries.

GazetteerEntryLike mirrors the KG-side GazetteerEntry shape without importing
the kg sub-module, keeping the schema/contracts layer the lowest dependency
layer (safe for ports and adapters to import).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GazetteerEntryLike:
    """A resolved village name -> spatial entity (residential settlement)."""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    entity_uri: str = ""
    bsms: list[str] = field(default_factory=list)
    centroid: tuple[float, float] | None = None
    source: str = ""
    confidence: float = 0.0
    description: str = ""


__all__ = ["GazetteerEntryLike"]
