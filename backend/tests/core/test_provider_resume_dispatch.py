from __future__ import annotations

import pytest
from langgraph.types import Send

from app.workflow.layers.layer_router import provider_resume_dispatch_node
from app.workflow.root_graph import (
    _provider_resume_patch,
    apply_human_review_decision,
    route_after_human_review,
)


def _failed_state() -> dict:
    return {
        "session_id": "resume-session",
        "phase": "layer3",
        "paused_stage": "l3",
        "dimension_retry_limit": 1,
        "dimension_retry_counts": {"traffic_planning": 1, "industry": 1},
        "fatal_error": {
            "stage": "L3",
            "dimension": "traffic_planning",
            "code": "llm_stream_timeout",
        },
        "provider_failures": [
            {
                "stage": "L3",
                "dimension": "traffic_planning",
                "code": "llm_stream_timeout",
            },
            {
                "stage": "L3",
                "dimension": "industry",
                "code": "llm_provider_circuit_open",
            },
        ],
    }


def test_provider_resume_collects_every_failed_dimension_without_revision() -> None:
    patch = _provider_resume_patch(_failed_state(), [])

    assert patch is not None
    assert patch["provider_resume_dimensions"] == ["traffic_planning", "industry"]
    assert patch["fatal_error"] is None
    assert patch["provider_failures"] == []
    assert patch["is_revision"] is False


def test_provider_resume_dispatches_exactly_once_and_consumes_list() -> None:
    state = {
        "phase": "layer3",
        "provider_resume_dimensions": ["traffic_planning", "industry", "industry"],
    }

    assert route_after_human_review(state) == "provider_resume_dispatch"
    command = provider_resume_dispatch_node(state)

    assert command.update == {"provider_resume_dimensions": []}
    assert all(isinstance(item, Send) for item in command.goto)
    assert [item.arg["dimension_key"] for item in command.goto] == [
        "traffic_planning",
        "industry",
    ]
    assert all(item.arg["is_revision"] is False for item in command.goto)


def test_provider_resume_fails_closed_after_dimension_budget() -> None:
    state = _failed_state()
    state["dimension_retry_counts"]["industry"] = 2

    patch = _provider_resume_patch(state, [])

    assert patch is not None
    assert patch["provider_resume_dimensions"] == []
    assert patch["delivery_status"] == "diagnostic_only"
    assert patch["diagnostic_terminal"]["dimensions"] == ["industry"]


@pytest.mark.asyncio
async def test_unattended_l3_approval_retries_invalid_dimensions_instead_of_bypassing() -> None:
    state = {
        "session_id": "l3-source-retry",
        "phase": "layer3",
        "paused_stage": "l3",
        "max_retries": 3,
        "retry_counts": {},
        "human_review_decisions": {"action": "approve", "feedback": "继续"},
        "human_review_items": [
            {
                "request_type": "program_rework",
                "context": {
                    "dimension_key": "traffic_planning",
                    "message": "道路结构化参数无效",
                },
            }
        ],
    }

    patch = await apply_human_review_decision(state)

    assert patch["autonomous_decision"] == "retry_invalid_l3_dimensions"
    assert patch["is_revision"] is True
    assert patch["revision_target_dimensions"] == ["traffic_planning"]
    assert patch["retry_counts"]["l3:traffic_planning"] == 1
