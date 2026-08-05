"""Tests for layer_completion_check bundle snapshot wiring."""

import pytest


@pytest.fixture(autouse=True)
def _mock_snapshot(monkeypatch):
    import app.services.session_bundle as sb

    calls = []

    async def fake_snapshot(session_id, trigger_reason=None, version=None):
        calls.append((session_id, trigger_reason, version))
        return None

    monkeypatch.setattr(sb, "snapshot_session_bundle", fake_snapshot)
    return calls


@pytest.fixture(autouse=True)
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
    monkeypatch.setattr(
        sse.SSEPublisher, "send_event",
        classmethod(lambda cls, session_id=None, event_type=None, **kw: events.append((event_type, None))),
    )
    return events


def _layer_state(layer, dims, **overrides):
    from app.agent.bootstrap.phase_machine import _layer_to_phase

    state = {
        "session_id": "sess-001",
        "phase": _layer_to_phase(layer),
        "completed_dimensions": {f"layer{layer}": list(dims)},
        "layer_char_counts": {layer: 1200},
        "pending_reports": [],
        "step_mode": False,
        "is_revision": False,
        "revision_impact_tree": {},
        "revision_completed_dims": {},
        "revision_target_dimensions": [],
        "previous_layer": 0,
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_auto_layer_complete_snapshots_layer(monkeypatch, _mock_snapshot, _mock_sse):
    from app.agent.bootstrap.phase_machine import get_layer_dimensions
    from app.agent.plan_state.completion_node import layer_completion_check

    state = _layer_state(1, get_layer_dimensions(1))
    result = await layer_completion_check(state)

    assert "phase" not in result
    assert result["layer_just_completed"] == 1
    assert _mock_snapshot == [("sess-001", "layer1", None)]


@pytest.mark.asyncio
async def test_auto_layer3_complete_snapshots_final(monkeypatch, _mock_snapshot, _mock_sse):
    from app.agent.bootstrap.phase_machine import get_layer_dimensions
    from app.agent.plan_state.completion_node import layer_completion_check

    state = _layer_state(3, get_layer_dimensions(3))
    result = await layer_completion_check(state)

    assert "phase" not in result
    assert result["layer_just_completed"] == 3
    assert _mock_snapshot == [("sess-001", "final", None)]


@pytest.mark.asyncio
async def test_not_complete_no_snapshot(monkeypatch, _mock_snapshot, _mock_sse):
    from app.agent.plan_state.completion_node import layer_completion_check

    dims = ["location", "socio_economic", "villager_wishes"]
    state = _layer_state(1, dims)
    result = await layer_completion_check(state)

    assert result == {}
    assert _mock_snapshot == []


@pytest.mark.asyncio
async def test_step_approve_snapshots_layer(monkeypatch, _mock_snapshot, _mock_sse):
    from app.agent.bootstrap.phase_machine import get_layer_dimensions
    from app.agent.plan_state.completion_node import layer_completion_check

    # Emulate resume data: interrupt() returns the passed payload in langgraph;
    # here we patch interrupt to return {"action": "approve"}.
    monkeypatch.setattr(
        "app.agent.plan_state.completion_node.interrupt",
        lambda payload: {"action": "approve"},
    )

    state = _layer_state(1, get_layer_dimensions(1), step_mode=True)
    result = await layer_completion_check(state)

    assert "phase" not in result
    assert result["layer_just_completed"] == 1
    assert _mock_snapshot == [("sess-001", "layer1", None)]


@pytest.mark.asyncio
async def test_step_reject_snapshots_layer(monkeypatch, _mock_snapshot, _mock_sse):
    from app.agent.bootstrap.phase_machine import get_layer_dimensions
    from app.agent.plan_state.completion_node import layer_completion_check

    monkeypatch.setattr(
        "app.agent.plan_state.completion_node.interrupt",
        lambda payload: {"action": "reject", "dimensions": ["location"], "feedback": ""},
    )

    state = _layer_state(1, get_layer_dimensions(1), step_mode=True)
    result = await layer_completion_check(state)

    assert result["need_revision"] is True
    assert _mock_snapshot == [("sess-001", "layer1", None)]


@pytest.mark.asyncio
async def test_revision_complete_snapshots_revision(monkeypatch, _mock_snapshot, _mock_sse):
    from app.agent.plan_state.completion_node import layer_completion_check

    state = _layer_state(
        1, ["location"],
        phase="layer1",
        is_revision=True,
        revision_impact_tree={"layer1": ["socio_economic"]},
        revision_completed_dims={"layer1": ["socio_economic", "location"]},
        revision_target_dimensions=["location"],
        pending_reports=[],
    )
    result = await layer_completion_check(state)

    assert result["is_revision"] is False
    assert _mock_snapshot == [("sess-001", "revision", None)]


@pytest.mark.asyncio
async def test_no_session_id_no_snapshot(monkeypatch, _mock_snapshot, _mock_sse):
    from app.agent.bootstrap.phase_machine import get_layer_dimensions
    from app.agent.plan_state.completion_node import layer_completion_check

    state = _layer_state(1, get_layer_dimensions(1))
    state["session_id"] = ""
    await layer_completion_check(state)

    assert _mock_snapshot == []
