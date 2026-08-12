from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import routes
from app.api.v1.contracts import ResumeRequest
from app.application.commands.resume_workflow import (
    ResumeConflictError,
    ResumeRequestError,
    ResumeWorkflowCommand,
    ResumeWorkflowService,
)
from app.modules.schema.contracts.resume_contracts import ResumeMode


def _snapshot(*, checkpoint_id: str, values: dict) -> SimpleNamespace:
    return SimpleNamespace(
        config={"configurable": {"checkpoint_id": checkpoint_id}},
        values=values,
        next=("deliver",),
        tasks=(),
    )


class _Runtime:
    def __init__(self, current=None, historical=None):
        self.current = current
        self.historical = historical
        self.interrupt_calls = []
        self.fork_calls = []

    async def current_snapshot(self, session_id):
        return self.current

    async def checkpoint_snapshot(self, session_id, checkpoint_id):
        return self.historical

    async def resume_interrupt(self, session_id, resume_data, *, expected_event_id):
        self.interrupt_calls.append((session_id, resume_data, expected_event_id))

    async def fork_checkpoint(
        self,
        session_id,
        *,
        checkpoint_id,
        state_values,
        replay_from_stage,
        branch_id,
    ):
        self.fork_calls.append(
            (session_id, checkpoint_id, state_values, replay_from_stage, branch_id)
        )


def _human_values() -> dict:
    return {
        "phase": "paused",
        "human_interrupt": {"event_id": "event-1", "channel": "review"},
    }


def _checkpoint_values() -> dict:
    return {
        "phase": "layer3",
        "previous_layer": 3,
        "layer_just_completed": 3,
    }


@pytest.mark.asyncio
async def test_application_service_preserves_interrupt_checkpoint_and_cas_token():
    runtime = _Runtime(current=_snapshot(checkpoint_id="cp-human", values=_human_values()))
    service = ResumeWorkflowService(runtime)

    result = await service.execute(
        ResumeWorkflowCommand(
            session_id="session-1",
            mode="interrupt",
            event_id="event-1",
            action="approve",
            feedback="confirmed",
        )
    )

    assert result.mode == "interrupt"
    assert result.checkpoint_id == "cp-human"
    assert result.resume_plan.mode is ResumeMode.INTERRUPT
    assert runtime.interrupt_calls == [
        ("session-1", {"action": "approve", "feedback": "confirmed"}, "event-1")
    ]


@pytest.mark.asyncio
async def test_application_service_forks_historical_checkpoint_with_plan_and_branch():
    runtime = _Runtime(
        historical=_snapshot(checkpoint_id="cp-history", values=_checkpoint_values())
    )
    service = ResumeWorkflowService(runtime)

    result = await service.execute(
        ResumeWorkflowCommand(
            session_id="session-1",
            mode="checkpoint",
            checkpoint_id="cp-history",
            replay_from_stage="execute",
        )
    )

    assert result.mode == "checkpoint"
    assert result.checkpoint_id == "cp-history"
    assert result.branch_id.startswith("fork-")
    assert result.resume_plan.mode is ResumeMode.RERUN
    assert runtime.fork_calls[0][0:2] == ("session-1", "cp-history")
    assert runtime.fork_calls[0][3] == "execute"
    assert runtime.fork_calls[0][4] == result.branch_id


@pytest.mark.asyncio
async def test_application_service_rejects_missing_resume_fields_before_runtime():
    runtime = _Runtime()
    service = ResumeWorkflowService(runtime)

    with pytest.raises(ResumeRequestError, match="event_id and action"):
        await service.execute(
            ResumeWorkflowCommand(session_id="session-1", mode="interrupt")
        )

    with pytest.raises(ResumeRequestError, match="checkpoint_id"):
        await service.execute(
            ResumeWorkflowCommand(session_id="session-1", mode="checkpoint")
        )


@pytest.mark.asyncio
async def test_route_only_maps_application_422_and_409(monkeypatch):
    class _FailingService:
        def __init__(self, error):
            self.error = error

        async def execute(self, command):
            raise self.error

    request = ResumeRequest(mode="checkpoint", checkpoint_id="cp-1")
    monkeypatch.setattr(
        routes,
        "resume_workflow_service",
        _FailingService(ResumeRequestError("checkpoint resume requires checkpoint_id")),
    )
    with pytest.raises(HTTPException) as invalid:
        await routes.resume_session("session-1", request)
    assert invalid.value.status_code == 422

    monkeypatch.setattr(
        routes,
        "resume_workflow_service",
        _FailingService(ResumeConflictError("checkpoint cannot be forked")),
    )
    with pytest.raises(HTTPException) as conflict:
        await routes.resume_session("session-1", request)
    assert conflict.value.status_code == 409


def test_route_does_not_know_graph_or_task_supervisor():
    path = Path(__file__).resolve().parents[2] / "app" / "api" / "v1" / "routes.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    source = path.read_text(encoding="utf-8")
    start = source.index("@router.post('/sessions/{session_id}/resume'")
    end = source.index("@router.get('/sessions/{session_id}/events/sync'")
    resume_source = source[start:end]
    assert "._graph" not in resume_source
    assert "CompositionRoot" not in resume_source
    assert "_trigger_planning_execution" not in resume_source
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        for node in ast.walk(tree)
    )
