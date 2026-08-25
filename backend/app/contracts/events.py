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
    LAYER_PAUSED = "layer_paused"
    EXECUTION_RESUMED = "execution_resumed"

    # Dimension events
    DIMENSION_START = "dimension_start"
    DIMENSION_COMPLETE = "dimension_complete"
    DIMENSION_DELTA = "dimension_delta"
    DIMENSION_ERROR = "dimension_error"

    # Cascade events
    CASCADE_IMPACT = "cascade_impact"
    CASCADE_COMPLETE = "cascade_complete"

    # AI response events
    AI_RESPONSE_DELTA = "ai_response_delta"
    AI_RESPONSE_COMPLETE = "ai_response_complete"

    # Checkpoint events
    CHECKPOINT_SAVED = "checkpoint_saved"
    REVISION_COMPLETED = "revision_completed"

    # Tool events
    TOOL_STARTED = "tool_started"
    TOOL_STATUS = "tool_status"

    # GIS events
    GIS_RESULT = "gis_result"
    GIS_LAYER_UPDATE = "gis_layer_update"

    # RAG events
    RAG_QUERY = "rag_query"
    RAG_RESULT = "rag_result"

    # Config events
    RAG_CONFIG_UPDATED = "rag_config_updated"
    STEP_MODE_UPDATED = "step_mode_updated"
    HUMAN_REVIEW_PAUSED = "human_review_paused"


__all__ = ["SSEEventType"]
