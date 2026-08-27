import asyncio

import pytest


@pytest.mark.asyncio
async def test_summary_supervisor_deduplicates_same_identity():
    from app.infrastructure.tasks.task_supervisor import TaskSupervisor, build_summary_task_key

    supervisor = TaskSupervisor()
    gate = asyncio.Event()
    first = supervisor.create_task(build_summary_task_key("s", 1, "d", 1), gate.wait())
    second = supervisor.create_task(build_summary_task_key("s", 1, "d", 1), asyncio.sleep(0))
    await asyncio.sleep(0)
    assert first.cancelled()
    assert second is not first
    await supervisor.cancel_all()


@pytest.mark.asyncio
async def test_update_summary_requires_matching_report_identity(monkeypatch):
    from app.infrastructure.reports.report_store import ReportStore

    class Result:
        def scalar_one_or_none(self):
            return None

    class DB:
        def add(self, obj):
            pass

        async def execute(self, statement):
            return Result()

        async def commit(self):
            pass

    class Session:
        async def __aenter__(self):
            return DB()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.infrastructure.reports.report_store.get_async_session", lambda: Session())
    assert await ReportStore().update_summary("s", "d", 1, "new", report_id="new-id") is False
