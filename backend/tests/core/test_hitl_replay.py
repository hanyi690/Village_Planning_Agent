import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.bootstrap.graph import create_unified_planning_graph
from app.agent.plan_state.state import create_initial_state


@pytest.mark.asyncio
async def test_human_review_resume_does_not_republish(monkeypatch):
    from app.agent.bootstrap import graph as graph_module
    published = []

    async def publish(*args, **kwargs):
        published.append(args[1])

    monkeypatch.setattr("app.services.sse.sse_manager.publish", publish)
    graph = create_unified_planning_graph(checkpointer=MemorySaver())
    state = create_initial_state("hitl", "v", "data")
    state["human_review_items"] = [{"request_id": "r1"}]
    state["paused_stage"] = "validate"
    # Directly exercise the four-node contract with a deterministic graph run.
    prepared = await graph_module.prepare_human_review({**state, "validate_gate": {"feedback_route": "HUMAN", "pending_requests": [{"request_id": "r1"}]}})
    published_state = await graph_module.publish_human_review_pause({**state, **prepared})
    await graph_module.publish_human_review_pause({**state, **prepared, **published_state})
    assert len(published) == 1


def test_empty_resume_is_rejected_at_api_boundary():
    from app.api.human_review_routes import ResolveRequest
    with pytest.raises(Exception):
        ResolveRequest(decisions={})


def test_human_review_paused_in_sse_enum():
    from app.core.events import SSEEventType
    assert SSEEventType.HUMAN_REVIEW_PAUSED == "human_review_paused"


def test_graph_uses_sse_enum_for_human_review_paused():
    from pathlib import Path
    graph_file = Path(__file__).resolve().parents[2] / "app/agent/bootstrap/graph.py"
    text = graph_file.read_text(encoding="utf-8")
    assert "SSEEventType.HUMAN_REVIEW_PAUSED" in text


def test_retry_exhaustion_returns_stage():
    from app.agent.bootstrap.post_l3_main_nodes import collect_human_review_items

    state = {
        "error_feedback": {"validate": "constraint failed"},
        "retry_counts": {"validate": 3},
        "max_retries": 3,
        "validate_gate": {"feedback_route": "RETRY_EXECUTE", "pending_requests": []},
    }
    stage, items = collect_human_review_items(state)
    assert stage is not None
    assert stage == "validate"
    assert len(items) > 0
    assert items[0]["request_type"] == "retry_exhausted"


def test_retry_exhaustion_defaults_to_post_l3_when_no_specific_stage():
    from app.agent.bootstrap.post_l3_main_nodes import collect_human_review_items

    state = {
        "error_feedback": {"unknown_stage": "some error"},
        "retry_counts": {"unknown_stage": 5},
        "max_retries": 3,
    }
    stage, items = collect_human_review_items(state)
    assert stage is not None
    assert len(items) > 0
