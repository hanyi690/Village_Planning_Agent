"""Regression tests for the L1 aggregate/grounding state hand-off."""

from __future__ import annotations

import asyncio

from app.workflow.layers.layer_aggregate_node import layer_aggregate_node


def test_l1_grounding_keeps_snapshot_and_gate_refs(monkeypatch):
    async def fake_l1_aggregate(_state):
        return {
            "artifact_refs": {
                "l1_snapshot": {"key": "snapshot"},
                "l1_gate": {"key": "gate"},
            },
        }

    async def fake_ground_anchors(_state):
        return {"artifact_refs": {"grounded_anchors": {"key": "anchors"}}}

    monkeypatch.setattr(
        "app.domain.assessment.aggregate.l1_aggregate",
        fake_l1_aggregate,
    )
    monkeypatch.setattr("app.domain.ground.ground_anchors", fake_ground_anchors)

    state = {
        "session_id": "merge-test",
        "run_id": "merge-test",
        "phase": "layer1",
        "layer_just_completed": 1,
        "context_version": "1",
        "context_ref": {"session_id": "merge-test", "version": "1"},
        "artifact_refs": {},
        "retry_counts": {},
    }

    result = asyncio.run(layer_aggregate_node(state))

    assert set(result["artifact_refs"]) == {
        "l1_snapshot",
        "l1_gate",
        "grounded_anchors",
    }
    assert result["layer_just_completed"] is None
