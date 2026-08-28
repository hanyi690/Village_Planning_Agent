"""Zone allocator port - global MIP parcel-to-zone assignment boundary.

Implemented by the SELECT adapter ``app.modules.select.zone_allocator_adapter``
and consumed by the EXECUTE zone-synthesis worker.  ``allocate`` returns a
``ZoneAllocationSolution`` (never raises on infeasibility).
"""
from __future__ import annotations

from typing import Any, Protocol


class ZoneAllocatorPort(Protocol):
    def allocate(
        self,
        targets: dict,
        candidates: dict,
        constraints: list | None = None,
        metadata: dict | None = None,
    ) -> Any:
        """Allocate candidate parcels to zones and return a ZoneAllocationSolution."""
        ...


__all__ = ["ZoneAllocatorPort"]
