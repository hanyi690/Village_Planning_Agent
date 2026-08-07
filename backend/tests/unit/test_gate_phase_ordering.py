"""Tests for the phase/gate ordering fix + layer worker routing.

Bug being fixed: ``layer_completion_check`` used to advance ``phase`` at the
same time it set ``layer_just_completed``, so ``after_analysis`` looked up the
WRONG gate (e.g. ``l2_gate_decision`` when L1 had just completed). After the
fix, phase only advances on gate PASS via the ``advance_phase`` node.
"""

import pytest
from langgraph.graph import END
from langgraph.types import Command, Send

from app.agent.bootstrap.phase_machine import get_layer_dimensions


def _minimal_state(**overrides):
    state = {
        "session_id": "s1",
        "phase": "layer1",
        "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
        "step_mode": False,
        "is_revision": False,
        "previous_layer": 0,
        "layer_just_completed": None,
    }
    state.update(overrides)
    return state


def _l1_complete_state(gate_route, **overrides):
    """L1 fully completed, with a gate decision present."""
    state = _minimal_state(
        phase="layer1",
        layer_just_completed=1,
        completed_dimensions={
            "layer1": get_layer_dimensions(1),
            "layer2": [],
            "layer3": [],
        },
        l1_gate_decision={
            "stage": "l1",
            "passed": gate_route is None or gate_route == "PASS",
            "feedback_route": gate_route,
        },
    )
    state.update(overrides)
    return state


def test_after_analysis_explore_does_not_advance_phase():
    """L1 completion with EXPLORE gate -> re-dispatch to worker, no phase advance."""
    from app.agent.conversation_router.edges import after_analysis

    state = _l1_complete_state("EXPLORE")
    result = after_analysis(state)

    assert isinstance(result, list) and len(result) > 0
    assert all(isinstance(s, Send) for s in result)
    assert all(s.node == "l1_worker" for s in result)
    # EXPLORE is NOT a PASS -> phase must not advance
    assert all(s.arg.get("phase") == "layer1" for s in result)


def test_after_analysis_pass_routes_to_advance_phase_and_advances():
    """L1 gate PASS -> after_analysis routes to advance_phase which advances phase to layer2."""
    from app.agent.bootstrap.layer_router import advance_phase_node
    from app.agent.conversation_router.edges import after_analysis

    state = _l1_complete_state("PASS")
    result = after_analysis(state)
    assert result == "advance_phase"

    cmd = advance_phase_node(state)
    assert isinstance(cmd, Command)
    assert cmd.update["phase"] == "layer2"
    assert cmd.update["previous_layer"] == 1
    assert cmd.update["layer_just_completed"] is None
    # Routes to the next layer's dispatch (Sends to worker) or END when nothing ready
    if isinstance(cmd.goto, list):
        assert all(s.node == "l2_worker" for s in cmd.goto)
    else:
        assert cmd.goto == END


def test_after_analysis_pass_none_route_advances():
    """feedback_route=None (the real GateDecision PASS shape) must also advance."""
    from app.agent.conversation_router.edges import after_analysis

    state = _l1_complete_state(None)
    assert after_analysis(state) == "advance_phase"


def test_after_analysis_human_and_rework_do_not_advance():
    """Non-PASS routes must not advance phase."""
    from app.agent.conversation_router.edges import after_analysis

    human = after_analysis(_l1_complete_state("HUMAN"))
    assert human == "human_review"

    rework = after_analysis(_l1_complete_state("L1"))
    assert isinstance(rework, list)
    assert all(s.node == "l1_worker" for s in rework)
    assert all(s.arg.get("phase") == "layer1" for s in rework)


def test_route_by_phase():
    from app.agent.bootstrap.layer_router import route_by_phase

    assert route_by_phase({"phase": "layer1"}) == "l1_worker"
    assert route_by_phase({"phase": "layer2"}) == "l2_worker"
    assert route_by_phase({"phase": "layer3"}) == "l3_worker"
    # unexpected / missing phase -> safe default
    assert route_by_phase({"phase": "completed"}) == "l1_worker"
    assert route_by_phase({}) == "l1_worker"


@pytest.mark.asyncio
async def test_l1_worker_node_delegates(monkeypatch):
    import app.agent.bootstrap.layer_router as lr

    async def fake(state):
        return {"delegated": "l1"}

    monkeypatch.setattr(lr, "analyze_dimension", fake)
    assert await lr.l1_worker_node({"dimension_key": "location"}) == {"delegated": "l1"}


@pytest.mark.asyncio
async def test_l2_worker_node_delegates(monkeypatch):
    import app.agent.bootstrap.layer_router as lr

    captured = {}

    async def fake(state):
        captured["state"] = state
        return {"delegated": "l2"}

    monkeypatch.setattr(lr, "analyze_l2_dimension", fake)
    state = {"phase": "layer2", "dimension_key": "planning_positioning"}
    result = await lr.l2_worker_node(state)
    assert result == {"delegated": "l2"}
    assert captured["state"] == state


@pytest.mark.asyncio
async def test_l3_worker_node_delegates(monkeypatch):
    import app.agent.bootstrap.layer_router as lr

    captured = {}

    async def fake(state):
        captured["state"] = state
        return {"delegated": "l3"}

    monkeypatch.setattr(lr, "analyze_l3_dimension", fake)
    state = {"phase": "layer3", "dimension_key": "spatial_structure"}
    result = await lr.l3_worker_node(state)
    assert result == {"delegated": "l3"}
    assert captured["state"] == state


@pytest.fixture
def _mock_sse(monkeypatch):
    import app.utils.sse_publisher as sse

    events = []

    monkeypatch.setattr(
        sse.SSEPublisher, "send_layer_complete",
        classmethod(lambda cls, session_id=None, layer=None, **kw: events.append(("complete", layer))),
    )
    monkeypatch.setattr(
        sse.SSEPublisher, "send_layer_start",
        classmethod(lambda cls, session_id=None, layer=None, **kw: events.append(("start", layer))),
    )
    return events


@pytest.mark.asyncio
async def test_completion_check_does_not_advance_phase(monkeypatch, _mock_sse):
    """Core fix: layer_completion_check sets layer_just_completed but NOT phase."""
    import app.agent.plan_state.completion_node as node_mod
    from app.agent.bootstrap.phase_machine import _layer_to_phase

    monkeypatch.setattr(node_mod, "_snapshot_bundle", _AsyncNoop())
    monkeypatch.setattr(node_mod, "_maybe_extract_bindings", _AsyncNoop())

    state = _minimal_state(
        phase=_layer_to_phase(1),
        completed_dimensions={"layer1": get_layer_dimensions(1)},
        layer_char_counts={1: 1200},
    )
    result = await node_mod.layer_completion_check(state)

    assert result["layer_just_completed"] == 1
    assert result["previous_layer"] == 1
    assert "phase" not in result


class _AsyncNoop:
    async def __call__(self, *args, **kwargs):
        return None
