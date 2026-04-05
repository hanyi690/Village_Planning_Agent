"""
Backend Constants Module
"""

from .sse_events import SSEEventType
from .config import (
    MAX_SESSION_EVENTS,
    EVENT_CLEANUP_INTERVAL_SECONDS,
    SESSION_TTL_HOURS,
    SSE_QUEUE_SIZE,
)

__all__ = [
    "SSEEventType",
    "MAX_SESSION_EVENTS",
    "EVENT_CLEANUP_INTERVAL_SECONDS",
    "SESSION_TTL_HOURS",
    "SSE_QUEUE_SIZE",
]