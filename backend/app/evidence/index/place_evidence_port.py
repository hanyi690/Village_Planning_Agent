"""PlaceEvidencePort - dependency-inversion boundary for place resolution.

The resolver (or EXPLORE/GROUND) reads place evidence only through this
port; it never touches ``ReportStore`` or the live KG instance directly.
Implementations are built from a ``PlanningContext`` (see
``PlaceEvidenceIndex.build``).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlaceEvidencePort(Protocol):
    """Read-only place resolution view over session evidence."""

    def resolve_mention(
        self, mention: str, role: str = "unknown", hints: str = ""
    ) -> "PlaceResolutionResult": ...

    @classmethod
    def build(cls, context) -> "PlaceEvidenceIndex":
        """Construct a versioned evidence index from a PlanningContext."""
        ...


__all__ = ["PlaceEvidencePort"]