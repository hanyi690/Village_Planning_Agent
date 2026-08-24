"""Tests for conservative checkpoint recovery after a process restart."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService


@pytest.mark.asyncio
async def test_recover_inflight_sessions_only_schedules_pending_non_human(monkeypatch):
    sessions = [
        {"session_id": "pending"},
        {"session_id": "human"},
        {"session_id": "terminal"},
        {"session_id": "done", "completed_at": "2026-08-22T00:00:00"},
    ]
    snapshots = {
        "pending": SimpleNamespace(
            tasks=(SimpleNamespace(interrupts=()),),
            values={"phase": "layer1", "delivery_status": None},
        ),
        "human": SimpleNamespace(
            tasks=(SimpleNamespace(interrupts=(SimpleNamespace(),)),),
            values={"phase": "layer1"},
        ),
        "terminal": SimpleNamespace(
            tasks=(SimpleNamespace(interrupts=()),),
            values={"phase": "completed", "delivery_status": "diagnostic"},
        ),
    }
    scheduled: list[tuple[str, object]] = []

    class _Supervisor:
        def create_task(self, key, coro):
            scheduled.append((key, coro))
            coro.close()
            return None

    async def _aget_state(session_id: str, subgraphs: bool = False):
        return snapshots.get(session_id)

    async def _resume(session_id: str):
        return {"session_id": session_id}

    monkeypatch.setattr(
        "app.database.operations.list_planning_sessions_async",
        lambda limit=100: _list_sessions(sessions, limit),
    )
    monkeypatch.setattr(PlanningRuntimeService, "aget_state", _aget_state)
    monkeypatch.setattr(PlanningRuntimeService, "resume_from_deepest_checkpoint", _resume)
    monkeypatch.setattr(
        "app.bootstrap.composition.CompositionRoot.get_task_supervisor",
        lambda: _Supervisor(),
    )
    monkeypatch.setattr(PlanningRuntimeService, "_initialized", True)
    monkeypatch.setattr(PlanningRuntimeService, "_graph", object())
    monkeypatch.setenv("RUNTIME_RECOVERY_MAX_SESSIONS", "16")

    result = await PlanningRuntimeService.recover_inflight_sessions()

    assert result == {
        "scanned": 4,
        "scheduled": 1,
        "terminalized": 0,
        "skipped": 3,
        "failed": 0,
    }
    assert [key for key, _ in scheduled] == ["pending:recovery"]


@pytest.mark.asyncio
async def test_recover_inflight_sessions_terminalizes_stale_non_init_cursor(monkeypatch):
    sessions = [{"session_id": "stale"}]
    snapshot = SimpleNamespace(
        tasks=(),
        next=(),
        values={"phase": "layer1", "active_stage": "L1"},
    )
    state_updates: list[tuple[str, dict, str | None]] = []
    db_updates: list[tuple[str, dict]] = []
    events: list[tuple[str, dict]] = []

    async def _aget_state(session_id: str, subgraphs: bool = False):
        return snapshot

    async def _aupdate_state(session_id: str, updates: dict, as_node: str | None = None):
        state_updates.append((session_id, updates, as_node))
        return True

    async def _update_session(session_id: str, updates: dict):
        db_updates.append((session_id, updates))
        return True

    async def _append_event(session_id: str, event: dict):
        events.append((session_id, event))
        return True

    monkeypatch.setattr(
        "app.database.operations.list_planning_sessions_async",
        lambda limit=100: _list_sessions(sessions, limit),
    )
    monkeypatch.setattr(PlanningRuntimeService, "aget_state", _aget_state)
    monkeypatch.setattr(PlanningRuntimeService, "aupdate_state", _aupdate_state)
    monkeypatch.setattr(PlanningRuntimeService, "_append_event", _append_event)
    monkeypatch.setattr(
        "app.infrastructure.runtime.planning_runtime_service.update_planning_session_async",
        _update_session,
    )
    monkeypatch.setattr(
        "app.bootstrap.composition.CompositionRoot.get_task_supervisor",
        lambda: SimpleNamespace(create_task=lambda *args: None),
    )
    monkeypatch.setattr(PlanningRuntimeService, "_initialized", True)
    monkeypatch.setattr(PlanningRuntimeService, "_graph", object())

    result = await PlanningRuntimeService.recover_inflight_sessions()

    assert result == {
        "scanned": 1,
        "scheduled": 0,
        "terminalized": 1,
        "skipped": 0,
        "failed": 0,
    }
    assert state_updates[0][0] == "stale"
    assert state_updates[0][1]["fatal_error"]["code"] == (
        "STALE_CHECKPOINT_NO_EXECUTABLE_CURSOR"
    )
    assert state_updates[0][2] == "end_diagnostic"
    assert db_updates[0][1]["status"] == "failed"
    assert events[0][1]["type"] == "error"


async def _list_sessions(sessions, limit):
    return sessions[:limit]
