"""Place resolution exports; single owner is the schema contracts module."""

from __future__ import annotations

from enum import StrEnum

from app.modules.schema.contracts.place_resolution_contracts import (
    PlaceResolutionCandidate,
    PlaceResolutionResult,
)


class PlaceResolutionStatus(StrEnum):
    """Fine-grained place resolution outcome.

    The reused ``PlaceResolutionResult.status`` literal only carries
    resolved/ambiguous/unresolved; this enum keeps the finer distinctions
    used by the evidence index so GROUND never guesses a candidate.
    """

    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"
    INSUFFICIENT_GEOMETRY = "insufficient_geometry"


__all__ = [
    "PlaceResolutionCandidate",
    "PlaceResolutionResult",
    "PlaceResolutionStatus",
]
