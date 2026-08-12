"""External retrieval port; provider adapters live outside this package."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.contracts.workflow.repair import ExternalSearchRequest, ExternalSearchResult


@runtime_checkable
class ExternalSearchPort(Protocol):
    """Optional EXPLORE evidence provider boundary."""

    async def search(self, request: ExternalSearchRequest) -> ExternalSearchResult:
        """Return a typed success, empty, or unresolved retrieval result."""
        ...


__all__ = ["ExternalSearchPort"]
