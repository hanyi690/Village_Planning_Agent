"""Planning context provider ports (blueprint M0/M5 boundary).

``PlanningContextProvider`` is the sync/async session-context boundary used by
workflow stages.  ``ContextProviderPort`` is the injected run-scoped provider
bundle carried by ``PlanningPorts`` (get_context / get_dataset / get_version).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


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


class ContextProviderPort(Protocol):
    """Run-scoped context/dataset access injected via ``PlanningPorts``."""

    def get_context(self, run_id: str) -> Any: ...
    def get_dataset(self, run_id: str, dataset_id: str) -> Any: ...
    def get_version(self, run_id: str) -> str: ...


__all__ = ["ContextProviderPort", "PlanningContextProvider"]
