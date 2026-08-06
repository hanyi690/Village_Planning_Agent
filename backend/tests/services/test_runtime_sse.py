import pytest
from app.services import runtime as runtime_mod
from app.services.runtime import PlanningRuntimeService


class FakeGraph:
    def __init__(self):
        self.captured_command = None

    async def astream(self, *args, **kwargs):
        self.captured_command = args[0] if args else None
        if False:
            yield None


async def _run_with_final_state(monkeypatch, final_state):
    emitted = []

    async def fake_wait_subscriber(session_id, timeout=1.0):
        return True

    async def fake_aget_state_values(session_id):
        return final_state

    async def fake_append_event(session_id, event):
        emitted.append(event)

    monkeypatch.setattr(runtime_mod.sse_manager, "wait_for_subscriber", fake_wait_subscriber)
    monkeypatch.setattr(runtime_mod.sse_manager, "set_execution_active", lambda *a, **k: None)
    monkeypatch.setattr(PlanningRuntimeService, "_graph", FakeGraph())
    monkeypatch.setattr(PlanningRuntimeService, "aget_state_values", fake_aget_state_values)
    monkeypatch.setattr(PlanningRuntimeService, "_append_event", fake_append_event)

    await PlanningRuntimeService._execute_planning("s1", initial_state=None)
    return emitted


@pytest.mark.asyncio
async def test_completed_sse_emitted_only_when_deliver_gate_pass(monkeypatch):
    emitted = await _run_with_final_state(
        monkeypatch, {"phase": "completed", "deliver_gate": {"feedback_route": "PASS"}}
    )
    assert len(emitted) == 1
    assert emitted[0].get("type") == "completed"


@pytest.mark.asyncio
async def test_no_completed_sse_without_deliver_gate(monkeypatch):
    emitted = await _run_with_final_state(monkeypatch, {"phase": "completed"})
    assert emitted == []


@pytest.mark.asyncio
async def test_no_completed_sse_on_retry_deliver_gate(monkeypatch):
    emitted = await _run_with_final_state(
        monkeypatch, {"phase": "completed", "deliver_gate": {"feedback_route": "RETRY_VALIDATE"}}
    )
    assert emitted == []


async def _resume_with_final_state(monkeypatch, final_state, resume_data=None):
    if resume_data is None:
        resume_data = {"action": "approve"}
    emitted = []
    sse_appended = []
    exec_active_calls = []

    async def fake_ensure_initialized():
        return None

    async def fake_aget_state_values(session_id):
        return final_state

    async def fake_append_event(session_id, event):
        emitted.append(event)

    monkeypatch.setattr(PlanningRuntimeService, "ensure_initialized", fake_ensure_initialized)
    graph = FakeGraph()
    monkeypatch.setattr(PlanningRuntimeService, "_graph", graph)
    monkeypatch.setattr(PlanningRuntimeService, "aget_state_values", fake_aget_state_values)
    monkeypatch.setattr(PlanningRuntimeService, "_append_event", fake_append_event)
    monkeypatch.setattr(
        runtime_mod.sse_manager, "append_event",
        lambda session_id, event: sse_appended.append(event),
    )
    monkeypatch.setattr(runtime_mod.sse_manager, "publish_sync", lambda *a, **k: None)
    monkeypatch.setattr(
        runtime_mod.sse_manager, "set_execution_active",
        lambda *a, **k: exec_active_calls.append(a),
    )

    await PlanningRuntimeService.resume_from_interrupt("s1", resume_data)
    return emitted, sse_appended, exec_active_calls, graph


@pytest.mark.asyncio
async def test_resume_emits_completed_when_deliver_pass(monkeypatch):
    emitted, sse_appended, exec_active_calls, _ = await _resume_with_final_state(
        monkeypatch, {"phase": "completed", "deliver_gate": {"feedback_route": "PASS"}}
    )
    assert any(e.get("type") == "completed" for e in emitted)
    assert any(e.get("type") == "resumed" for e in sse_appended)
    assert ("s1", False) in exec_active_calls


@pytest.mark.asyncio
async def test_resume_no_completed_when_deliver_not_pass(monkeypatch):
    emitted, sse_appended, _, _ = await _resume_with_final_state(
        monkeypatch, {"phase": "completed", "deliver_gate": {"feedback_route": "HUMAN"}}
    )
    assert not any(e.get("type") == "completed" for e in emitted)
    assert any(e.get("type") == "resumed" for e in sse_appended)


@pytest.mark.asyncio
async def test_resume_empty_dict_normalized_to_no_op(monkeypatch):
    _, _, _, graph = await _resume_with_final_state(
        monkeypatch, {"phase": "completed"}, resume_data={}
    )
    assert graph.captured_command is not None
    assert graph.captured_command.resume == {"action": "no_op"}
