"""Place evidence index port (blueprint M3 boundary).

The canonical resolution contract lives in
``app.modules.schema.contracts.place_resolution_contracts``.  Adapters (KG,
gazetteer, bundle, external geocoder) are wired behind this protocol so
GROUND/SELECT only ever see a typed ``PlaceResolutionResult``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlaceEvidenceIndex(Protocol):
    """Resolve a place reference to typed, evidence-scored candidates."""

    async def resolve(self, request: object) -> object:
        """Return a PlaceResolutionResult for the request.

        Status values distinguish ``exact``, ``ambiguous``, ``unresolved``
        and ``conflict``; never pick the first candidate implicitly.
        """
        ...


__all__ = ["PlaceEvidenceIndex"]
