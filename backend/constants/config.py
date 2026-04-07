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
# Increased from 500 to 2000 to handle high-frequency events (dimension_delta)
SSE_QUEUE_SIZE = 2000

# Queue full wait timeout (100ms) - fallback to pending_events cache
SSE_QUEUE_WAIT_TIMEOUT = 0.1


__all__ = [
    "MAX_SESSION_EVENTS",
    "EVENT_CLEANUP_INTERVAL_SECONDS",
    "SESSION_TTL_HOURS",
    "SSE_QUEUE_SIZE",
    "SSE_QUEUE_WAIT_TIMEOUT",
]