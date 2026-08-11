from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.agent.l1_observe import analysis_node
from app.agent.l2_strategize import worker as l2_worker
from app.agent.l3_plan import worker as l3_worker
from app.services import session as session_service
from app.services.task_supervisor import TaskSupervisor


class _DummyChunk:
    def __init__(self, content: str):
        self.content = content


class _DummyLLM:
    async def astream(self, _prompt):
        yield _DummyChunk("mock-report")


class _DummyStats:
    def start_dimension(self, *_args, **_kwargs):
        return None

    def record_prompt(self, *_args, **_kwargs):
        return None

    def record_rag_time(self, *_args, **_kwargs):
        return None

    def record_llm_time(self, *_args, **_kwargs):
        return None

    def end_dimension(self, *_args, **_kwargs):
        return None


class _DummyStore:
    async def get_latest_version(self, _session_id: str, _dimension_key: str) -> int:
        return 0


class _RecordingSupervisor:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def create_task(self, key: str, coro):
        self.calls.append((key, coro.cr_code.co_name))
        coro.close()
        return None


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


def _patch_worker_common(monkeypatch: pytest.MonkeyPatch, module, *, layer: int) -> _RecordingSupervisor:
    supervisor = _RecordingSupervisor()

    monkeypatch.setattr(
        "app.services.composition.CompositionRoot.get_task_supervisor",
        lambda: supervisor,
    )
    monkeypatch.setattr(module, "get_dimension_config", lambda dim_key: SimpleNamespace(
        key=dim_key,
        name=f"Dimension {dim_key}",
        layer=layer,
        layer_depends_on=[],
        tools=[],
    ))
    monkeypatch.setattr(module, "_get_llm", lambda: _DummyLLM())
    monkeypatch.setattr(module, "run_rag", lambda *_args, **_kwargs: _async_result(("", None)))
    monkeypatch.setattr(module, "publish_dimension_start", _async_noop)
    monkeypatch.setattr(module, "publish_dimension_delta", _async_noop)
    monkeypatch.setattr(module, "publish_dimension_complete", _async_noop)
    monkeypatch.setattr(module, "provider_failure_open", lambda _session_id: False)
    monkeypatch.setattr(module, "generate_summary_regex", lambda *_args, **_kwargs: "{}")
    monkeypatch.setattr(module, "save_report_immediate", _async_noop)
    monkeypatch.setattr(module, "save_step_report", _async_noop)
    monkeypatch.setattr(
        "app.services.report_store.ReportStore.get_instance",
        lambda: _DummyStore(),
    )
    monkeypatch.setattr(
        "app.utils.stats_collector.StatsCollector.get_instance",
        lambda: _DummyStats(),
    )
    return supervisor


async def _async_noop(*_args, **_kwargs):
    return None


async def _async_result(value):
    return value


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
        "app.services.task_supervisor.logger.error",
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
        "app.services.composition.CompositionRoot.get_task_supervisor",
        lambda: supervisor,
    )

    result = await session_service._cancel_session_tasks("session-abc")

    assert result is True
    assert supervisor.session_ids == ["session-abc"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "func_name", "layer"),
    [
        (analysis_node, "analyze_dimension", 1),
        (l2_worker, "analyze_l2_dimension", 2),
        (l3_worker, "analyze_l3_dimension", 3),
    ],
)
async def test_workers_schedule_summary_enrichment_via_task_supervisor(
    monkeypatch: pytest.MonkeyPatch,
    module,
    func_name: str,
    layer: int,
):
    supervisor = _patch_worker_common(monkeypatch, module, layer=layer)

    monkeypatch.setattr(module, "retrieve_evidence", _raise_for_test)

    if module is analysis_node:
        monkeypatch.setattr(
            "app.agent.l1_observe.pipeline.DataPipeline",
            lambda: SimpleNamespace(get_professional_data=_async_noop),
        )
        monkeypatch.setattr(
            "app.agent.l1_observe.formatters.generate_professional_data_section",
            lambda *_args, **_kwargs: "",
        )
        monkeypatch.setattr(module, "load_dependency_reports", lambda *_args, **_kwargs: _async_result(("", "")))
    elif module is l2_worker:
        monkeypatch.setattr(module, "load_dependency_reports", lambda *_args, **_kwargs: _async_result(("", "")))
    else:
        monkeypatch.setattr(
            module,
            "load_layered_dependency_reports",
            lambda *_args, **_kwargs: _async_result(("", "", "")),
        )

    state = {
        "dimension_key": "land_use",
        "session_id": "session-123",
        "project_name": "Village",
        "config": {},
    }

    result = await getattr(module, func_name)(state)

    assert result["pending_reports"][0]["version"] == 1
    assert supervisor.calls == [("session-123:summary:1:land_use:1" if layer == 1 else f"session-123:summary:{layer}:land_use:1", "enrich_summary_background")]


async def _raise_for_test(*_args, **_kwargs):
    raise RuntimeError("skip external evidence")
