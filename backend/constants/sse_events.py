"""
SSE Event Types - Centralized Event Type Constants

All SSE event type strings are defined here for consistency.
"""


class SSEEventType(str):
    """SSE Event Type Constants"""

    # Connection events
    CONNECTED = "connected"
    HEARTBEAT = "heartbeat"
    COMPLETED = "completed"
    ERROR = "error"
    RESUMED = "resumed"
    PAUSE = "pause"

    # Layer events
    LAYER_STARTED = "layer_started"
    LAYER_COMPLETED = "layer_completed"

    # Dimension events
    DIMENSION_START = "dimension_start"
    DIMENSION_COMPLETE = "dimension_complete"
    DIMENSION_DELTA = "dimension_delta"

    # AI response events
    AI_RESPONSE_DELTA = "ai_response_delta"
    AI_RESPONSE_COMPLETE = "ai_response_complete"

    # Tool events
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


__all__ = ["SSEEventType"]