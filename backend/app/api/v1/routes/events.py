"""Event sync and SSE stream transport for a session."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.v1.contracts import EventSyncResponse
from app.application.projections.events import public_event
from app.application.queries.run_events import run_event_queries


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/sessions/{session_id}/events/sync", response_model=EventSyncResponse)
async def sync_events(session_id: str, after: int = 0) -> EventSyncResponse:
    sync = await run_event_queries.sync(session_id, after)
    return EventSyncResponse(
        session_id=session_id,
        events=[public_event(session_id, event) for event in sync.events],
        last_seq=sync.last_seq,
        resync_required=sync.resync_required,
    )


@router.get("/sessions/{session_id}/events", response_class=EventSourceResponse)
async def stream_events(
    session_id: str,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterable[ServerSentEvent]:
    stream = await run_event_queries.open_stream(session_id, last_event_id or 0)
    queue = stream.queue
    delivered_seq = int(last_event_id or 0)

    def resync_event(after: int) -> ServerSentEvent:
        return ServerSentEvent(
            data={"schema_version": "1.0", "after": after},
            event="resync_required",
            id=str(after) if after > 0 else None,
            retry=3000,
        )

    try:
        yield ServerSentEvent(comment="connected", retry=3000)
        if stream.resync_required:
            yield resync_event(delivered_seq)
            return
        for event in stream.replay:
            projected = public_event(session_id, event)
            delivered_seq = max(delivered_seq, int(projected["seq"]))
            yield ServerSentEvent(
                data=projected,
                event=str(projected["type"]),
                id=str(projected["seq"]),
                retry=3000,
            )
            if projected["type"] in {"completed", "failed"}:
                return
        while True:
            if stream.needs_resync():
                yield resync_event(delivered_seq)
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                if stream.needs_resync():
                    yield resync_event(delivered_seq)
                    return
                yield ServerSentEvent(comment="heartbeat")
                continue
            if int(event.get("seq") or 0) <= delivered_seq:
                continue
            projected = public_event(session_id, event)
            delivered_seq = max(delivered_seq, int(projected["seq"]))
            yield ServerSentEvent(
                data=projected,
                event=str(projected["type"]),
                id=str(projected["seq"]),
                retry=3000,
            )
            if projected["type"] in {"completed", "failed"}:
                break
    finally:
        await run_event_queries.close_stream(session_id, queue)


__all__ = ["stream_events", "sync_events", "router"]
