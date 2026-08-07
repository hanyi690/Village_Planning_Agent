"""Session SSE routes - streaming events and reconnect sync."""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.runtime import PlanningRuntimeService
from app.services.sse import sse_manager
from app.services.checkpoint import checkpoint_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/sessions/{session_id}/stream")
async def stream_events(session_id: str):
    """SSE 事件流端点"""
    if not sse_manager.session_exists(session_id):
        from app.database.operations import get_planning_session_async
        rebuilt = await checkpoint_service.rebuild_session_from_db(session_id, get_planning_session_async, sse_manager)
        if not rebuilt:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    async def event_generator():
        queue = await PlanningRuntimeService.subscribe_with_history(session_id)
        try:
            yield sse_manager.format_sse({"type": "connected", "session_id": session_id, "timestamp": datetime.now().isoformat()})

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    if event.get("type") in ["completed", "error"]:
                        yield sse_manager.format_sse(event)
                        break
                    yield sse_manager.format_sse(event)
                except asyncio.TimeoutError:
                    yield sse_manager.format_sse({"type": "heartbeat", "timestamp": datetime.now().isoformat()})
        except asyncio.CancelledError:
            pass
        finally:
            await sse_manager.unsubscribe(session_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/api/sessions/{session_id}/sync")
async def sync_events(session_id: str, from_seq: int = 0):
    """断线重连同步端点"""
    if not sse_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    events = sse_manager.get_events_from_seq(session_id, from_seq)
    return {"events": events, "last_seq": sse_manager.get_last_seq(session_id), "from_seq": from_seq}


__all__ = ["router"]