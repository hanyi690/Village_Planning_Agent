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


def test_single_dimension_failure_resumes_only_that_dimension() -> None:
    """A single failed dimension must NOT re-dispatch the whole layer.

    The layer has twelve dimensions; a provider/quality failure on one of them
    collects exactly that dimension into provider_resume_dimensions so the
    resume re-runs only it, never the other eleven.
    """
    state = {
        "phase": "layer3",
        "fatal_error": {
            "stage": "L3",
            "dimension": "public_service",
            "code": "llm_provider_error",
        },
        "provider_failures": [
            {
                "stage": "L3",
                "dimension": "public_service",
                "code": "llm_provider_error",
            }
        ],
        "dimension_retry_counts": {},
    }

    patch = _provider_resume_patch(state, [])

    assert patch is not None
    assert patch["provider_resume_dimensions"] == ["public_service"]
    command = provider_resume_dispatch_node({**state, **patch})
    assert all(item.arg["dimension_key"] == "public_service" for item in command.goto)
    assert len(command.goto) == 1


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


async def _fake_classification_revision(state, decisions):
    return {
        "classification_revision": True,
        "classification_decision_targets": ["land_use_planning:claim:FA-02"],
        "artifact_refs": {"planning_program": {"descriptor_digest": "rev"}},
    }


@pytest.mark.asyncio
async def test_mixed_pause_approve_with_classification_decisions_applies_revision(
    monkeypatch,
) -> None:
    state = {
        "session_id": "mixed-pause",
        "phase": "layer3",
        "paused_stage": "l3",
        "human_review_decisions": {
            "action": "approve",
            "classification_decisions": [
                {
                    "target_id": "land_use_planning:claim:FA-02",
                    "code_system": "appendix5",
                    "selected_code": "1100",
                    "candidate_codes": ["1100"],
                    "status": "resolved",
                }
            ],
        },
        "human_review_items": [
            {
                "request_type": "classification_decision_required",
                "stage": "l3",
                "context": {"target_ids": ["land_use_planning:claim:FA-02"]},
            },
            {
                "request_type": "transient_llm_failure",
                "stage": "l3",
                "context": {"code": "llm_provider_error", "dimension_key": "traffic_planning"},
            },
        ],
    }
    monkeypatch.setattr(
        "app.workflow.root_graph._apply_classification_revision",
        _fake_classification_revision,
    )

    patch = await apply_human_review_decision(state)

    assert patch["classification_revision"] is True
    assert patch.get("provider_resume_dimensions") is None
    assert patch["provider_failures"] == []
    assert route_after_human_review(patch) == "target_projection"


@pytest.mark.asyncio
async def test_mixed_pause_approve_without_classification_decisions_still_provider_resumes(
    monkeypatch,
) -> None:
    state = {
        "session_id": "mixed-pause-no-decisions",
        "phase": "layer3",
        "paused_stage": "l3",
        "dimension_retry_limit": 1,
        "dimension_retry_counts": {"traffic_planning": 0},
        "human_review_decisions": {"action": "approve", "feedback": "重试"},
        "human_review_items": [
            {
                "request_type": "transient_llm_failure",
                "stage": "l3",
                "context": {"code": "llm_provider_error", "dimension_key": "traffic_planning"},
            }
        ],
    }

    patch = await apply_human_review_decision(state)

    assert patch["provider_resume_dimensions"] == ["traffic_planning"]
    assert not patch.get("classification_revision")
    assert route_after_human_review(patch) == "provider_resume_dispatch"
