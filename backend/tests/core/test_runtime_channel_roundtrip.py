"""The runtime channel replaces the workflow_progress artifact carrier."""

from __future__ import annotations

from app.workflow.runtime_adapter import initial_workflow_state, materialize_workflow_state, pack_workflow_patch
from app.workflow.state import WorkflowState


def test_runtime_channel_is_a_declared_workflow_state_field():
    assert "runtime" in WorkflowState.__annotations__


def test_initial_state_carries_runtime_channel():
    state = initial_workflow_state({"session_id": "s1", "phase": "layer1", "paused_stage": "ground"})
    assert "runtime" in state
    assert state["runtime"]["paused_stage"] == "ground"


def test_pack_and_materialize_roundtrip_preserves_stage_local_keys():
    initial = initial_workflow_state({"session_id": "s1", "phase": "layer1"})
    packed = pack_workflow_patch(initial, {"current_stage": "ground", "next_stage": "select", "paused_stage": "l1"})
    assert "runtime" in packed
    materialized = materialize_workflow_state(packed)
    assert materialized["current_stage"] == "ground"
    assert materialized["next_stage"] == "select"
    assert materialized["paused_stage"] == "l1"


def test_runtime_channel_excludes_reducer_and_identity_keys():
    initial = initial_workflow_state({
        "session_id": "s1", "phase": "layer1",
        "artifact_refs": {}, "retry_counts": {"ground": 1}, "messages": [],
    })
    carrier = initial["runtime"]
    assert "session_id" not in carrier
    assert "artifact_refs" not in carrier
    assert "phase" not in carrier
    assert "messages" not in carrier
    assert carrier["retry_counts"] == {"ground": 1}


def test_parallel_provider_failures_are_first_class_checkpoint_channels():
    state = initial_workflow_state({
        "session_id": "s1",
        "phase": "layer3",
        "fatal_error": {"code": "llm_stream_timeout", "dimension": "traffic"},
        "provider_failures": [
            {"code": "llm_stream_timeout", "dimension": "traffic"},
        ],
        "dimension_retry_counts": {"traffic": 1},
    })

    assert state["fatal_error"]["dimension"] == "traffic"
    assert state["provider_failures"][0]["dimension"] == "traffic"
    assert state["dimension_retry_counts"] == {"traffic": 1}
    assert "provider_failures" not in state["runtime"]

    cleared = pack_workflow_patch(state, {
        "fatal_error": None,
        "provider_failures": [],
    })
    assert cleared["fatal_error"] is None
    assert cleared["provider_failures"] == []
