"""Application transaction and port contracts.

The adapters remain the existing runtime, database, artifact, and event
implementations.  This module only describes the application boundary and
provides a small lifecycle wrapper for commands that need one transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol


class RuntimePort(Protocol):
    async def current_values(self, session_id: str) -> dict[str, object] | None: ...

    async def resume_interrupt(
        self,
        session_id: str,
        resume_data: dict[str, object],
        *,
        expected_event_id: str,
    ) -> None: ...


class SessionRepositoryPort(Protocol):
    async def create(self, values: Mapping[str, object]) -> str: ...

    async def update(self, session_id: str, values: Mapping[str, object]) -> None: ...

    async def delete(self, session_id: str) -> None: ...


class UploadIngestionPort(Protocol):
    async def process(
        self,
        file: object,
        session_id: str,
        category: str,
    ) -> Mapping[str, object]: ...


class PlanningStarterPort(Protocol):
    async def start(self, session_id: str, initial_state: Mapping[str, object]) -> None: ...


class EventRepositoryPort(Protocol):
    async def sync_window(
        self,
        session_id: str,
        after: int,
    ) -> tuple[list[dict[str, object]], int]: ...

    async def last_seq(self, session_id: str) -> int: ...


class ArtifactReaderPort(Protocol):
    async def read(
        self,
        session_id: str,
        artifact_key: str,
    ) -> tuple[Mapping[str, object], object] | None: ...


class UnitOfWork(AbstractAsyncContextManager["UnitOfWork"], Protocol):
    sessions: SessionRepositoryPort
    ingestion: UploadIngestionPort
    starter: PlanningStarterPort
    runtime: RuntimePort

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@dataclass
class ApplicationUnitOfWork:
    """A command-scoped collection of existing application ports."""

    sessions: SessionRepositoryPort
    ingestion: UploadIngestionPort
    starter: PlanningStarterPort
    runtime: RuntimePort

    async def __aenter__(self) -> "ApplicationUnitOfWork":
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


__all__ = [
    "ApplicationUnitOfWork",
    "ArtifactReaderPort",
    "EventRepositoryPort",
    "PlanningStarterPort",
    "RuntimePort",
    "SessionRepositoryPort",
    "UnitOfWork",
    "UploadIngestionPort",
]
