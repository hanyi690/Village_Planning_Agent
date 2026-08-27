"""Regression tests for hard worker and grounding fallback boundaries."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_dimension_worker_timeout_returns_merge_safe_provider_failure(monkeypatch):
    from app.workflow import root_graph

    monkeypatch.setattr("app.core.settings.DIMENSION_EXECUTION_TIMEOUT_S", 1.0)
    monkeypatch.setattr("app.core.settings.DIMENSION_TIMEOUT_S", {})

    async def slow_worker(_state):
        await asyncio.sleep(1.1)
        return {"completed_dimensions": {"layer1": ["natural_environment"]}}

    result = await root_graph._audited_dimension_worker(
        slow_worker,
        {"phase": "layer1", "dimension_key": "natural_environment"},
    )

    assert result["provider_failures"] == [{
        "stage": "L1",
        "dimension": "natural_environment",
        "code": "llm_stream_timeout",
        "message": "dimension worker exceeded hard timeout (1.0s)",
    }]
    assert result["dimension_retry_counts"] == {"natural_environment": 1}


@pytest.mark.asyncio
async def test_dimension_worker_transport_error_uses_provider_failure_channel():
    from app.workflow import root_graph

    async def failing_worker(_state):
        raise ConnectionError("temporary provider disconnect")

    result = await root_graph._audited_dimension_worker(
        failing_worker,
        {
            "session_id": "transport-error-channel-test",
            "phase": "layer3",
            "dimension_key": "traffic",
        },
    )

    assert result["provider_failures"] == [{
        "stage": "L3",
        "dimension": "traffic",
        "code": "llm_provider_error",
        "message": "dimension worker provider transport error (ConnectionError)",
    }]
    assert result["dimension_retry_counts"] == {"traffic": 1}


def test_grounding_budget_is_reused_within_scope_and_replaced_between_requests():
    from types import SimpleNamespace

    from app.spatial.grounding.call_budget import get_ground_llm_budget

    owner = SimpleNamespace(session_id="budget-session")
    first = get_ground_llm_budget(owner, scope_key="run:one")
    same = get_ground_llm_budget(owner, scope_key="run:one")
    next_request = get_ground_llm_budget(owner, scope_key="run:two")

    assert same is first
    assert next_request is not first
    assert first["scope_key"] == "run:one"
    assert next_request["scope_key"] == "run:two"


def test_dimension_send_always_has_official_run_timeout(monkeypatch):
    from app.workflow.layers.layer_router import _send_worker

    monkeypatch.setattr("app.core.settings.DIMENSION_EXECUTION_TIMEOUT_S", 17.5)
    monkeypatch.setattr("app.core.settings.DIMENSION_TIMEOUT_S", {})

    send = _send_worker("l1_worker", {"dimension_key": "location"})

    assert send.timeout is not None
    assert send.timeout.run_timeout == 17.5
    assert send.timeout.idle_timeout is None


@pytest.mark.asyncio
async def test_structured_timeout_includes_provider_queue_wait(monkeypatch):
    from pydantic import BaseModel

    from app.infrastructure.llm.structured import run_structured_output

    class Result(BaseModel):
        value: str

    gate = asyncio.Semaphore(1)
    await gate.acquire()

    async def locked_gate():
        return gate

    monkeypatch.setattr(
        "app.infrastructure.llm.factory.get_llm_semaphore",
        locked_gate,
    )

    class ShouldNotRun:
        def with_structured_output(self, *_args, **_kwargs):
            raise AssertionError("provider call started after queue budget expired")

    with pytest.raises(asyncio.TimeoutError):
        await run_structured_output(
            Result,
            [{"role": "user", "content": "return value"}],
            llm=ShouldNotRun(),
            timeout=0.01,
        )


@pytest.mark.asyncio
async def test_structured_provider_timeout_can_start_after_queue(monkeypatch):
    from pydantic import BaseModel

    from app.infrastructure.llm.structured import run_structured_output

    class Result(BaseModel):
        value: str

    gate = asyncio.Semaphore(1)
    await gate.acquire()

    async def locked_gate():
        return gate

    monkeypatch.setattr(
        "app.infrastructure.llm.factory.get_llm_semaphore",
        locked_gate,
    )

    class FakeLLM:
        def with_structured_output(self, *_args, **_kwargs):
            class _Structured:
                async def ainvoke(self, _messages):
                    return Result(value="after-queue")

            return _Structured()

    task = asyncio.create_task(
        run_structured_output(
            Result,
            [{"role": "user", "content": "return value"}],
            llm=FakeLLM(),
            timeout=0.1,
            timeout_includes_queue=False,
        )
    )
    await asyncio.sleep(0.02)
    gate.release()

    assert await task == Result(value="after-queue")
