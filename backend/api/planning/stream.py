"""
Planning API Stream - SSE 流端点

服务端推送事件流。
"""

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.services import PlanningRuntimeService
from backend.services.sse_manager import sse_manager
from backend.services.checkpoint_service import checkpoint_service
from backend.database.operations_async import get_planning_session_async
from backend.constants import MAX_SESSION_EVENTS

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/planning/stream/{session_id}")
async def stream_planning(session_id: str):
    """
    SSE 事件流端点

    返回 Server-Sent Events 流，包含规划过程的所有事件。
    """
    # Rebuild session if not in memory
    if not sse_manager.session_exists(session_id):
        rebuilt = await checkpoint_service.rebuild_session_from_db(
            session_id, get_planning_session_async, sse_manager
        )
        if not rebuilt:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    # Log connection state
    session_state = sse_manager.get_session(session_id) or {}
    current_layer = session_state.get("current_layer", "?")
    stream_state = sse_manager.get_stream_state(session_id)
    subscriber_count_before = sse_manager.get_subscriber_count(session_id)

    logger.info(f"[Planning API] [{session_id}] SSE 连接建立")
    logger.info(f"[Planning API] [{session_id}] current_layer={current_layer}, stream_state={stream_state}")
    logger.info(f"[Planning API] [{session_id}] 连接前订阅者数量: {subscriber_count_before}")

    async def event_generator():
        queue = await PlanningRuntimeService.subscribe_with_history(session_id)

        try:
            # Send connected event immediately
            yield sse_manager.format_sse({
                "type": "connected",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            })

            while True:
                try:
                    # Wait for event with timeout
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)

                    # Check for completion events
                    event_type = event.get("type", "")
                    if event_type in ["completed", "error"]:
                        yield sse_manager.format_sse(event)
                        logger.info(f"[Planning API] [{session_id}] SSE 流结束: {event_type}")
                        break

                    yield sse_manager.format_sse(event)

                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield sse_manager.format_sse({
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat()
                    })

        except asyncio.CancelledError:
            logger.info(f"[Planning API] [{session_id}] SSE 连接被取消")
        finally:
            await sse_manager.unsubscribe(session_id, queue)
            logger.info(f"[Planning API] [{session_id}] SSE 连接关闭")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/api/planning/stream/{session_id}/sync")
async def sync_events(session_id: str, from_seq: int = 0):
    """
    Reconnection sync endpoint.

    Returns events from a specific sequence number for SSE reconnection.
    Used by client to recover missed events after reconnection.

    Args:
        session_id: Session identifier
        from_seq: Last sequence number client received (returns events with seq > from_seq)

    Returns:
        JSON with events list and last_seq
    """
    # Check if session exists
    if not sse_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    events = sse_manager.get_events_from_seq(session_id, from_seq)
    last_seq = sse_manager.get_last_seq(session_id)

    logger.info(
        f"[Planning API] [{session_id}] Sync requested from_seq={from_seq}, "
        f"returned {len(events)} events, last_seq={last_seq}"
    )

    return {
        "events": events,
        "last_seq": last_seq,
        "from_seq": from_seq,
    }


__all__ = ["router"]