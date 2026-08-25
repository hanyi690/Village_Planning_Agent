import asyncio

import pytest

import app.database as database
from app.infrastructure.kg import session_kg
from app.infrastructure.llm import instructor_client
from app.infrastructure.events.sse_publisher import SSEPublisher
from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
from app.workflow.layers import layer_router
from app.workflow.plan_state.state_factory import StateFactory
from scripts import run_pipeline_real_jintian as runner


class _PausedListener:
    def __init__(self) -> None:
        self.disconnected = False
        self.waited_event_types: list[str] = []

    async def connect(self) -> bool:
        return True

    async def wait_for_any_event(self, event_types, timeout, filter_func):
        self.waited_event_types = list(event_types)
        await asyncio.sleep(0)
        event = {
            "type": "human_review_paused",
            "data": {
                "event_id": "review-1",
                "paused_stage": "l2",
                "item_count": 2,
            },
        }
        assert filter_func(event) is True
        return event

    async def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_real_runner_returns_human_pause_instead_of_waiting_for_l3(monkeypatch) -> None:
    listener = _PausedListener()
    cancelled = False

    async def fake_execution(session_id, initial_state):
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled = True
            raise

    monkeypatch.setattr(
        PlanningRuntimeService,
        "trigger_planning_execution",
        staticmethod(fake_execution),
    )
    monkeypatch.setattr(StateFactory, "create", staticmethod(lambda **kwargs: {}))
    monkeypatch.setattr(
        SSEPublisher,
        "send_layer_start",
        staticmethod(lambda **kwargs: None),
    )

    result = await runner._run_graph("session-1", listener)

    assert result == {
        "status": "paused",
        "paused_stage": "l2",
        "event_id": "review-1",
        "item_count": 2,
    }
    assert "human_review_paused" in listener.waited_event_types
    assert listener.disconnected is True
    assert cancelled is True


def test_layer_start_is_published_only_from_gate_advance(monkeypatch) -> None:
    starts = []

    monkeypatch.setattr(
        layer_router,
        "_ready_dispatch",
        lambda state, phase: ["ready-dimension"],
    )
    monkeypatch.setattr(
        SSEPublisher,
        "send_layer_start",
        staticmethod(lambda **kwargs: starts.append(kwargs)),
    )

    layer_router.advance_phase_node(
        {
            "phase": "layer1",
            "session_id": "session-1",
        }
    )

    assert starts == [{
        "session_id": "session-1",
        "layer": 2,
        "layer_name": "规划思路",
        "dimension_count": 4,
    }]


@pytest.mark.asyncio
async def test_real_runner_releases_runtime_resources(monkeypatch) -> None:
    calls = []

    async def record(label):
        calls.append(label)

    monkeypatch.setattr(PlanningRuntimeService, "shutdown", staticmethod(lambda: record("runtime")))
    monkeypatch.setattr(instructor_client, "close_cached_clients", lambda: record("provider"))
    monkeypatch.setattr(database, "dispose_async_engine", lambda: record("engine"))
    monkeypatch.setattr(database, "shutdown_database", lambda: record("database"))
    monkeypatch.setattr(session_kg, "shutdown_session_kg_process_pool", lambda: calls.append("kg"))

    await runner._shutdown_runtime()

    assert calls == ["runtime", "provider", "engine", "database", "kg"]
