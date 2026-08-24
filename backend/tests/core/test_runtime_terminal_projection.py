"""Runtime terminal and public status projection regressions."""

from __future__ import annotations

import pytest


def test_recoverable_typed_failure_projects_paused():
    from app.workflow.plan_state.state import state_to_ui_status

    result = state_to_ui_status(
        {
            "phase": "layer1",
            "fatal_error": {
                "stage": "L1",
                "dimension": "transportation",
                "code": "llm_typed_output_error",
            },
            "paused_stage": "l1",
        },
        is_interrupted=True,
    )

    assert result["status"] == "paused"


def test_exhausted_typed_failure_projects_failed():
    from app.workflow.plan_state.state import state_to_ui_status

    result = state_to_ui_status(
        {
            "phase": "completed",
            "fatal_error": {
                "stage": "layer1",
                "dimension": "transportation",
                "code": "LLM_DIMENSION_RETRY_EXHAUSTED",
            },
            "delivery_status": "diagnostic_only",
            "diagnostic_terminal": {"reason": "provider_dimension_retry_exhausted"},
        },
        is_interrupted=False,
    )

    assert result["status"] == "failed"
    assert result["phase"] == "completed"


def test_delivery_status_is_terminal_even_when_phase_projection_lags():
    from app.infrastructure.runtime.planning_runtime_service import _has_terminal_delivery

    assert _has_terminal_delivery(
        {"phase": "post_l3", "delivery_status": "complete"}
    ) is True
    assert _has_terminal_delivery(
        {"phase": "post_l3", "deliver_gate": {"feedback_route": "PASS"}}
    ) is True
    assert _has_terminal_delivery({"phase": "post_l3"}) is False


@pytest.mark.asyncio
async def test_unfinished_normal_stream_is_persisted_as_failed_terminal(monkeypatch):
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    updates: list[dict] = []
    db_updates: list[dict] = []

    async def _aupdate_state(_session_id, patch, as_node=None):
        updates.append({"patch": patch, "as_node": as_node})
        return True

    async def _update_session(_session_id, patch):
        db_updates.append(patch)
        return True

    monkeypatch.setattr(PlanningRuntimeService, "aupdate_state", _aupdate_state)
    monkeypatch.setattr(
        "app.infrastructure.runtime.planning_runtime_service.update_planning_session_async",
        _update_session,
    )
    monkeypatch.setattr(PlanningRuntimeService, "_append_event", lambda *_args: _ok())

    diagnostic = await PlanningRuntimeService._terminalize_unfinished_stream(
        "session-1", {"phase": "layer1"}
    )

    assert diagnostic["code"] == "RUNTIME_STREAM_COMPLETED_WITHOUT_TERMINAL"
    assert updates[0]["patch"]["delivery_status"] == "diagnostic_only"
    assert updates[0]["patch"]["phase"] == "completed"
    assert updates[0]["patch"]["statutory_complete"] is False
    assert updates[0]["patch"]["fatal_error"] == diagnostic
    assert updates[0]["as_node"] == "end_diagnostic"
    assert db_updates == [{"status": "failed", "execution_error": diagnostic["message"]}]


@pytest.mark.asyncio
async def test_terminal_delivery_marks_history_session_completed(monkeypatch):
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    db_updates: list[dict] = []

    async def _update_session(_session_id, patch):
        db_updates.append(patch)
        return True

    monkeypatch.setattr(
        "app.infrastructure.runtime.planning_runtime_service.update_planning_session_async",
        _update_session,
    )

    await PlanningRuntimeService._mark_terminal_delivery("session-1")

    assert db_updates[0]["status"].value == "completed"
    assert db_updates[0]["completed_at"] is not None
    assert db_updates[0]["execution_error"] is None


async def _ok(*_args, **_kwargs):
    return True


@pytest.mark.asyncio
async def test_session_projection_uses_newest_layer_event_when_checkpoint_lags(monkeypatch):
    from app.application.projections.session import SessionProjectionService

    control = {
        "status": "running",
        "phase": "layer1",
        "active_stage": "L1",
        "config": {"project_name": "demo", "village_name": "village"},
    }

    async def _load(_session_id):
        return control

    async def _persisted(_session_id):
        return {}

    async def _manifest_read(_session_id, _key):
        return None

    async def _latest(_session_id):
        return {
            "type": "progress",
            "data": {"type": "layer_started", "layer": 3, "layer_name": "详细规划"},
            "seq": 9,
        }

    async def _last_seq(_session_id):
        return 9

    monkeypatch.setattr("app.application.projections.session.load_workflow_state", _load)
    monkeypatch.setattr("app.application.projections.session.get_planning_session_async", _persisted)
    monkeypatch.setattr("app.application.projections.session.artifact_queries.read", _manifest_read)
    monkeypatch.setattr("app.application.projections.session.run_event_queries.latest", _latest)
    monkeypatch.setattr("app.application.projections.session.run_event_queries.last_seq", _last_seq)

    view = await SessionProjectionService().get("session-1")

    assert view.phase == "layer3"
    assert view.active_stage == "L3"
    assert view.progress == 55.0
    assert view.last_event_seq == 9


def test_session_projection_derives_phase_from_stage_only_event():
    from app.application.projections.session import _project_live_phase

    assert _project_live_phase(
        {"phase": "layer1"},
        {"type": "progress", "data": {"type": "step_report", "stage": "L3"}},
    ) == "layer3"
