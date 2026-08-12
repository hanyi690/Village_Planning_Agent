"""Port for ingesting raw files into a frozen session data snapshot."""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from app.data.model.snapshot import SessionDataSnapshot


class DataIngestPort(Protocol):
    def ingest(
        self,
        files: Sequence[Any],
        *,
        session_id: str,
        source: str = "upload",
    ) -> SessionDataSnapshot:
        """Ingest raw files and return a frozen session data snapshot."""
        ...


__all__ = ["DataIngestPort"]
