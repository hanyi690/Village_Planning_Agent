"""Spatial query port (blueprint M2 boundary).

All spatial reads enter through a typed workspace; adapters must not expose
bare GeoJSON or provider-specific types to domain code.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SpatialQueryPort(Protocol):
    """Typed spatial queries against a frozen SpatialWorkspace."""

    async def query_features(self, layer: str, **filters: object) -> list[object]:
        """Return typed SpatialFeature objects (not raw dicts)."""
        ...


__all__ = ["SpatialQueryPort"]
