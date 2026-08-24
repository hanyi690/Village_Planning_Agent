"""Application queries for durable run-event replay and live subscription."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.infrastructure.events import EventRepository, event_hub


@dataclass(frozen=True)
class EventSync:
    events: list[dict[str, Any]]
    last_seq: int
    resync_required: bool


@dataclass(frozen=True)
class EventStream:
    queue: asyncio.Queue[dict[str, Any]]
    replay: list[dict[str, Any]]
    last_seq: int
    resync_required: bool
    needs_resync: Callable[[], bool]


class RunEventQueryService:
    """Single application boundary for REST sync and SSE replay."""

    async def sync(self, session_id: str, after: int = 0) -> EventSync:
        events, last_seq = await EventRepository.sync_window(session_id, after)
        oldest = min(
            (int(event.get("seq") or 0) for event in events),
            default=last_seq,
        )
        resync_required = after > 0 and last_seq > after and not events
        if events and oldest > after + 1:
            resync_required = True
        return EventSync(
            events=[] if resync_required else events,
            last_seq=last_seq,
            resync_required=resync_required,
        )

    async def last_seq(self, session_id: str) -> int:
        return await EventRepository.last_seq(session_id)

    async def latest(self, session_id: str) -> dict[str, Any] | None:
        return await EventRepository.latest(session_id)

    async def recent(self, session_id: str, limit: int = 512) -> list[dict[str, Any]]:
        return await EventRepository.recent(session_id, limit=limit)

    async def open_stream(self, session_id: str, after: int = 0) -> EventStream:
        # Register before reading the log so events published during replay are
        # present in the live queue. The route filters queue events through the
        # replay watermark to avoid duplicate delivery.
        queue = await event_hub.subscribe(session_id)
        sync = await self.sync(session_id, after)
        return EventStream(
            queue=queue,
            replay=sync.events,
            last_seq=sync.last_seq,
            resync_required=sync.resync_required,
            needs_resync=lambda: event_hub.is_desynced(session_id, queue),
        )

    async def close_stream(
        self,
        session_id: str,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        await event_hub.unsubscribe(session_id, queue)


run_event_queries = RunEventQueryService()

__all__ = ["EventStream", "EventSync", "RunEventQueryService", "run_event_queries"]
