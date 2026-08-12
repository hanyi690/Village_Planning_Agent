from __future__ import annotations

import asyncio

import pytest

import app.application.sessions.session_service as session_service
from app.infrastructure.tasks.task_supervisor import TaskSupervisor

class _CancelRecordingSupervisor:
    def __init__(self):
        self.session_ids: list[str] = []

    async def cancel_session(self, session_id: str) -> None:
        self.session_ids.append(session_id)


async def _cancel_aware_task(cancelled: asyncio.Event) -> None:
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        cancelled.set()
        raise


@pytest.mark.asyncio
async def test_task_supervisor_replaces_existing_task():
    supervisor = TaskSupervisor()
    first_cancelled = asyncio.Event()

    first_task = supervisor.create_task(
        "session-1:summary:1:land_use:1",
        _cancel_aware_task(first_cancelled),
    )
    await asyncio.sleep(0)
    second_task = supervisor.create_task(
        "session-1:summary:1:land_use:1",
        asyncio.sleep(0),
    )

    await asyncio.wait_for(first_cancelled.wait(), timeout=1)
    await second_task
    await asyncio.sleep(0)

    assert first_task.cancelled()
    assert supervisor.active_count == 0


@pytest.mark.asyncio
async def test_task_supervisor_cancel_session_only_cancels_owned_tasks():
    supervisor = TaskSupervisor()
    owned_exact_cancelled = asyncio.Event()
    owned_summary_cancelled = asyncio.Event()
    other_session_cancelled = asyncio.Event()

    other_task = supervisor.create_task(
        "session-2:summary:2:industry:3",
        _cancel_aware_task(other_session_cancelled),
    )
    supervisor.create_task("session-1", _cancel_aware_task(owned_exact_cancelled))
    supervisor.create_task(
        "session-1:summary:1:land_use:1",
        _cancel_aware_task(owned_summary_cancelled),
    )
    await asyncio.sleep(0)

    await supervisor.cancel_session("session-1")
    await asyncio.wait_for(owned_exact_cancelled.wait(), timeout=1)
    await asyncio.wait_for(owned_summary_cancelled.wait(), timeout=1)

    assert not other_task.cancelled()
    assert supervisor.active_count == 1

    await supervisor.cancel_all()
    await asyncio.wait_for(other_session_cancelled.wait(), timeout=1)
    assert supervisor.active_count == 0


@pytest.mark.asyncio
async def test_task_supervisor_logs_background_exception(monkeypatch: pytest.MonkeyPatch):
    errors: list[tuple[str, BaseException]] = []
    monkeypatch.setattr(
        "app.infrastructure.tasks.task_supervisor.logger.error",
        lambda message, key, exc: errors.append((key, exc)),
    )

    async def _boom():
        raise RuntimeError("boom")

    supervisor = TaskSupervisor()
    task = supervisor.create_task("session-1:summary:3:facility:7", _boom())

    with pytest.raises(RuntimeError, match="boom"):
        await task
    await asyncio.sleep(0)

    assert errors
    assert errors[0][0] == "session-1:summary:3:facility:7"
    assert str(errors[0][1]) == "boom"
    assert supervisor.active_count == 0


@pytest.mark.asyncio
async def test_cancel_session_tasks_uses_cancel_session(monkeypatch: pytest.MonkeyPatch):
    supervisor = _CancelRecordingSupervisor()
    monkeypatch.setattr(
        "app.bootstrap.composition.CompositionRoot.get_task_supervisor",
        lambda: supervisor,
    )

    result = await session_service._cancel_session_tasks("session-abc")

    assert result is True
    assert supervisor.session_ids == ["session-abc"]
