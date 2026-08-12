"""Online delivery for durable run events.

The hub owns only live asyncio queues.  Event history and sequence numbers
belong to :class:`EventRepository`; a reconnect must replay from that durable
source instead of an in-process cache.
"""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from typing import Any

from app.contracts.events import SSEEventType
from app.core.settings import SSE_QUEUE_SIZE

from .repository import EventRepository

logger = logging.getLogger(__name__)


class EventConnectionHub:
    """Broadcast persisted events to currently connected SSE clients."""

    _subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
    _desynced: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
    _subscribers_lock = Lock()
    _main_event_loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def save_event_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        cls._main_event_loop = loop

    @classmethod
    async def subscribe(cls, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)
        session_key = str(session_id)
        with cls._subscribers_lock:
            cls._subscribers.setdefault(session_key, set()).add(queue)
            desynced = cls._desynced.get(session_key)
            if desynced is not None:
                desynced.discard(queue)
                if not desynced:
                    cls._desynced.pop(session_key, None)
        return queue

    @classmethod
    async def unsubscribe(
        cls,
        session_id: str,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> None:
        session_key = str(session_id)
        with cls._subscribers_lock:
            subscribers = cls._subscribers.get(session_key)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                cls._subscribers.pop(session_key, None)
            desynced = cls._desynced.get(session_key)
            if desynced is not None:
                desynced.discard(queue)
                if not desynced:
                    cls._desynced.pop(session_key, None)

    @classmethod
    def get_subscriber_count(cls, session_id: str) -> int:
        with cls._subscribers_lock:
            return len(cls._subscribers.get(str(session_id), set()))

    @classmethod
    def is_desynced(
        cls,
        session_id: str,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> bool:
        with cls._subscribers_lock:
            return queue in cls._desynced.get(str(session_id), set())

    @classmethod
    async def wait_for_subscriber(cls, session_id: str, timeout: float = 5.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if cls.get_subscriber_count(session_id):
                return True
            await asyncio.sleep(0.1)
        return False

    @classmethod
    async def publish(cls, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """Persist once, then fan out to live queues.

        Queue overflow never creates a second source of truth.  The event is
        already durable and the client can recover it through event sync on
        reconnect.  High-frequency deltas may be dropped from a live queue;
        terminal/progress facts remain recoverable from the repository.
        """

        persisted = await EventRepository.append(session_id, event)
        session_key = str(session_id)
        with cls._subscribers_lock:
            subscribers = list(cls._subscribers.get(session_key, set()))
            desynced = set(cls._desynced.get(session_key, set()))

        for queue in subscribers:
            if queue in desynced:
                continue
            try:
                queue.put_nowait(persisted)
            except asyncio.QueueFull:
                if cls._mark_desynced(session_key, queue):
                    logger.warning(
                        "SSE live queue full for session %s; event seq=%s is durable and requires resync",
                        session_id,
                        persisted.get("seq"),
                    )

        if not subscribers and persisted.get("type") in {
            SSEEventType.COMPLETED,
            SSEEventType.ERROR,
            SSEEventType.HUMAN_REVIEW_PAUSED,
        }:
            logger.info(
                "No live SSE subscriber for terminal event session=%s seq=%s; durable replay remains available",
                session_id,
                persisted.get("seq"),
            )
        return persisted

    @classmethod
    def publish_sync(cls, session_id: str, event: dict[str, Any]) -> None:
        loop = cls._main_event_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("No event loop available for SSE event %s", event.get("type"))
                return
        asyncio.run_coroutine_threadsafe(cls.publish(session_id, event), loop)

    @classmethod
    def _mark_desynced(
        cls,
        session_id: str,
        queue: asyncio.Queue[dict[str, Any]],
    ) -> bool:
        with cls._subscribers_lock:
            subscribers = cls._subscribers.get(str(session_id))
            if not subscribers or queue not in subscribers:
                return False
            desynced = cls._desynced.setdefault(str(session_id), set())
            if queue in desynced:
                return False
            desynced.add(queue)
            return True


event_hub = EventConnectionHub()

__all__ = ["EventConnectionHub", "event_hub"]
