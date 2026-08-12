"""Planning context provider port (blueprint M0/M5 boundary)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlanningContextProvider(Protocol):
    """Returns the versioned planning context for a session.

    Implementations must return a fresh, immutable context snapshot; callers
    must never refresh or mutate it in place.
    """

    def get_context(self, session_id: str) -> object:
        """Return the current PlanningContext (or None when unavailable)."""
        ...

    async def aget_context(self, session_id: str) -> object:
        """Async variant used by workflow stages and commands."""
        ...


__all__ = ["PlanningContextProvider"]
