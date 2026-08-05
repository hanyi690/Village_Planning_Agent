"""Post-L3 retry loop: node-owned retry_counts + error_feedback + RETRY_L3 surfacing."""

from types import SimpleNamespace

import pytest

from app.agent.bootstrap.post_l3_chain import (
    _retry_or_human,
    _route_after_validate,
)
from app.agent.bootstrap.post_l3_nodes import ground_node
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.modules.schema.contracts.workflow_contracts import (
    GateDecision,
    PendingRequest,
)


def _explore_gate(message="unresolved spec: no candidates resolved"):
    return GateDecision(
        stage="ground",
        passed=False,
        feedback_route="EXPLORE",
        pending_requests=[
            PendingRequest(
                request_id="pr-ground-unresolved-0",
                stage="explore",
                request_type="spatial_reference_unresolved",
                context={
                    "reason": "spatial_reference_unresolved",
                    "message": message,
                    "detail": "",
                },
            )
        ],
    )


def _patch_ground_deps(monkeypatch, grounding, gate):
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.ground_aggregate",
        lambda specs, context: grounding,
    )
    monkeypatch.setattr(
        "app.agent.bootstrap.post_l3_nodes.evaluate_ground_gate",
        lambda result: gate,
    )


@pytest.mark.asyncio
async def test_retry_counts_bump_on_retry(monkeypatch):
    grounding = SimpleNamespace(candidates=[], unresolved=[])
    gate = _explore_gate()
    _patch_ground_deps(monkeypatch, grounding, gate)

    state = PostL3ChainState(
        ground_gate=gate,
        specs=["s1"],
        context=SimpleNamespace(session_id="r1"),
    )
    out = await ground_node(state)
    assert out["retry_counts"]["ground"] == 1
    assert isinstance(out["error_feedback"]["ground"], str)
    assert out["error_feedback"]["ground"]


@pytest.mark.asyncio
async def test_first_run_no_bump(monkeypatch):
    grounding = SimpleNamespace(candidates=[], unresolved=[])
    gate = _explore_gate()
    _patch_ground_deps(monkeypatch, grounding, gate)

    state = PostL3ChainState(
        ground_gate=None,
        specs=["s1"],
        context=SimpleNamespace(session_id="r1"),
    )
    out = await ground_node(state)
    assert "retry_counts" not in out
    assert "error_feedback" not in out


def test_retry_escalates_to_human():
    state = PostL3ChainState(
        ground_gate=_explore_gate(),
        retry_counts={"ground": 3},
        max_retries=3,
    )
    assert _retry_or_human(state, "ground", "ground") == "human_end"


def test_retry_l3_routes_to_human_review():
    gate = GateDecision(stage="validate", passed=False, feedback_route="RETRY_L3")
    state = PostL3ChainState(validate_gate=gate, retry_counts={})
    assert _route_after_validate(state) == "human_review"


@pytest.mark.asyncio
async def test_retrieve_evidence_safe():
    from app.agent.ground.aggregate import retrieve_evidence

    assert await retrieve_evidence(None) == []
    rows = await retrieve_evidence(SimpleNamespace(session_id="r1"))
    assert isinstance(rows, list)
    assert not rows
    rows = await retrieve_evidence(
        SimpleNamespace(session_id="r1"), ["bundle:parcels"]
    )
    assert isinstance(rows, list)
    assert all(hasattr(r, "query_type") for r in rows)
    assert any(r.query_type == "retry:evidence_requests" for r in rows)
