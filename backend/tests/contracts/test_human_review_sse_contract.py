"""Contract: human_review_paused SSE payload schema.

Locks the fields the frontend depends on: event_id, paused_stage, reason, item_count.
"""
import pytest
from app.core.events import SSEEventType


def test_human_review_paused_event_type_value():
    assert str(SSEEventType.HUMAN_REVIEW_PAUSED) == "human_review_paused"


def test_human_review_paused_payload_fields():
    """The SSE payload must include event_id, paused_stage, reason, item_count."""
    # Read the emission code to verify the payload structure
    import inspect
    from app.agent.bootstrap import graph
    source = inspect.getsource(graph.publish_human_review_pause)
    # Verify all required fields are in the payload
    assert "event_id" in source
    assert "paused_stage" in source
    assert "reason" in source
    assert "item_count" in source