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


def test_grounding_fallback_budget_stops_serial_llm_calls(monkeypatch):
    from app.domain.ground import anchors

    monkeypatch.setattr("app.core.settings.GROUND_MAX_LLM_CALLS", 2)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_CALL_TIMEOUT_S", 30)
    budget = anchors._new_ground_llm_budget()

    assert anchors._reserve_ground_llm_call(budget) == 30
    assert anchors._reserve_ground_llm_call(budget) == 30
    assert anchors._reserve_ground_llm_call(budget) is None


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


def test_name_backfill_budget_is_independent_from_anchor_budget():
    from app.domain.ground import anchors

    anchor_budget = anchors._new_ground_llm_budget()
    name_budget = anchors._new_name_backfill_budget()

    assert name_budget is not anchor_budget
    assert name_budget["remaining"] == anchor_budget["remaining"]
    assert name_budget["scope_key"] == "name_backfill"


def test_dimension_send_always_has_official_run_timeout(monkeypatch):
    from app.workflow.layers.layer_router import _send_worker

    monkeypatch.setattr("app.core.settings.DIMENSION_EXECUTION_TIMEOUT_S", 17.5)
    monkeypatch.setattr("app.core.settings.DIMENSION_TIMEOUT_S", {})

    send = _send_worker("l1_worker", {"dimension_key": "location"})

    assert send.timeout is not None
    assert send.timeout.run_timeout == 17.5
    assert send.timeout.idle_timeout is None


@pytest.mark.asyncio
async def test_grounding_fallbacks_are_bounded_concurrent(monkeypatch):
    from types import SimpleNamespace

    from app.domain.ground import anchors

    monkeypatch.setattr("app.core.settings.GROUND_MAX_LLM_CALLS", 8)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_CALL_TIMEOUT_S", 30)
    monkeypatch.setattr("app.core.settings.GROUND_LLM_MAX_CONCURRENT", 2)
    budget = anchors._new_ground_llm_budget()
    candidate = SimpleNamespace(
        canonical_name="candidate",
        entity_type="village",
        role="village",
        source_bsms=["bsm-1"],
        geometry_ref="POINT(1 1)",
        score=0.5,
    )
    active = 0
    peak = 0

    class FakeLLM:
        def with_structured_output(self, response_model, **_kwargs):
            class _Structured:
                async def ainvoke(self, prompt):
                    nonlocal active, peak
                    active += 1
                    peak = max(peak, active)
                    await asyncio.sleep(0.02)
                    active -= 1
                    candidate_id = prompt.split("candidate_id=", 1)[1].split()[0]
                    digest = prompt.split("input_digest=", 1)[1].split(";", 1)[0]
                    return response_model(
                        status="selected",
                        selected_candidate_id=candidate_id,
                        input_digest=digest,
                    )

            return _Structured()

    results = await asyncio.gather(*[
        anchors._llm_reason_candidate(
            FakeLLM(), "mention", "village", "hint", [candidate], budget=budget
        )
        for _ in range(5)
    ])

    assert all(result is candidate for result in results)
    assert peak == 2


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
