"""
Backend Configuration Constants

Shared constants for the backend services.
"""

# Session Event Configuration
MAX_SESSION_EVENTS = 5000

# Event Cleanup Configuration
EVENT_CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes
SESSION_TTL_HOURS = 24

# SSE Queue Configuration
SSE_QUEUE_SIZE = 500


__all__ = [
    "MAX_SESSION_EVENTS",
    "EVENT_CLEANUP_INTERVAL_SECONDS",
    "SESSION_TTL_HOURS",
    "SSE_QUEUE_SIZE",
]