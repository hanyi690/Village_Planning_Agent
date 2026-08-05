"""layer_aggregate_node tests - L1/L2/L3 aggregate wiring."""

from types import SimpleNamespace

import pytest

from app.agent.bootstrap.layer_aggregate_node import layer_aggregate_node


@pytest.mark.asyncio
async def test_layer_aggregate_calls_l1(monkeypatch):
    captured = {}

    async def fake_l1(state, *, base_dir=".run-tmp"):
        captured["l1"] = state
        return {
            "l1_snapshot_ref": {"artifact_id": "l1-s1"},
            "l1_gate_decision": {"stage": "l1", "passed": True, "feedback_route": None},
            "l1_review_id": "rev-l1",
        }

    monkeypatch.setattr("app.agent.l1_observe.aggregate.l1_aggregate", fake_l1)

    state = {
        "session_id": "s1",
        "run_id": "s1",
        "context_version": "v1",
        "layer_just_completed": 1,
    }
    result = await layer_aggregate_node(state)
    assert result["l1_snapshot_ref"]["artifact_id"] == "l1-s1"
    assert result["l1_gate_decision"]["passed"] is True
    assert result["l1_review_id"] == "rev-l1"
    assert result["layer_just_completed"] is None


@pytest.mark.asyncio
async def test_layer_aggregate_calls_l2(monkeypatch):
    async def fake_l2(state, *, base_dir=".run-tmp"):
        return {
            "l2_strategy_ref": {"artifact_id": "l2-s1"},
            "l2_gate_decision": {"stage": "l2", "passed": True, "feedback_route": None},
            "l2_review_id": "rev-l2",
        }

    monkeypatch.setattr("app.agent.l2_strategize.aggregate.l2_aggregate", fake_l2)

    state = {"session_id": "s1", "layer_just_completed": 2}
    result = await layer_aggregate_node(state)
    assert result["l2_strategy_ref"]["artifact_id"] == "l2-s1"
    assert result["layer_just_completed"] is None


@pytest.mark.asyncio
async def test_layer_aggregate_calls_l3(monkeypatch):
    async def fake_l3(state, *, base_dir=".run-tmp"):
        return {
            "l3_program_ref": {"artifact_id": "l3-s1"},
            "l3_gate_decision": {"stage": "l3", "passed": True, "feedback_route": None},
            "l3_review_id": "rev-l3",
        }

    monkeypatch.setattr("app.agent.l3_plan.aggregate.l3_aggregate", fake_l3)

    state = {"session_id": "s1", "layer_just_completed": 3}
    result = await layer_aggregate_node(state)
    assert result["l3_program_ref"]["artifact_id"] == "l3-s1"
    assert result["layer_just_completed"] is None


@pytest.mark.asyncio
async def test_layer_aggregate_noop_when_no_flag():
    result = await layer_aggregate_node({"session_id": "s1"})
    assert result == {}


@pytest.mark.asyncio
async def test_layer_aggregate_noop_when_revision():
    result = await layer_aggregate_node(
        {"session_id": "s1", "is_revision": True, "layer_just_completed": 1}
    )
    assert result == {}
