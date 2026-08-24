from types import SimpleNamespace

import pytest

from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
from app.contracts.spatial.planned_state_contracts import PlannedState
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, ExecutionResult


@pytest.mark.asyncio
async def test_reconcile_stage_binds_execution_outputs_by_name(monkeypatch):
    from app.workflow.stages import reconcile as reconcile_stage

    program = SimpleNamespace(interventions=[])
    intent = SimpleNamespace(spatial_reference_specs=[])
    grounding = SimpleNamespace()
    execution_plan = ExecutionPlan(worker_tasks=[])
    execution_result = ExecutionResult()
    changeset = ParcelChangeSet()
    planned_state = PlannedState()
    calls = {}

    async def fake_context(_state):
        return SimpleNamespace()

    def fake_load_ref(_state, key, _cls):
        return {
            "planning_program": program,
            "target_projection": intent,
            "grounding_result": grounding,
            "execution_result": execution_result,
            "execution_plan": execution_plan,
            "validation_certificate": SimpleNamespace(
                can_reconcile=True,
                status="passed",
            ),
        }.get(key)

    def fake_load_embedded(_state, _descriptor, cls):
        if cls is ParcelChangeSet:
            return changeset
        if cls is PlannedState:
            return planned_state
        return None

    def fake_reconcile_aggregate(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(inconsistencies=[])

    monkeypatch.setattr(reconcile_stage, "_require_context", fake_context)
    monkeypatch.setattr(reconcile_stage, "_load_ref_artifact", fake_load_ref)
    monkeypatch.setattr(reconcile_stage, "_adopt_context", lambda *_args: {})
    monkeypatch.setattr(reconcile_stage, "_retry_patch", lambda *_args: {})
    monkeypatch.setattr(reconcile_stage, "_evaluate_progress_gate", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(reconcile_stage, "persist_stage_artifact", lambda *_args, **_kwargs: {"digest": "reconcile"})
    monkeypatch.setattr(reconcile_stage, "stage_completion_patch", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        "app.workflow.stages.support._load_embedded_artifact",
        fake_load_embedded,
    )
    monkeypatch.setattr(
        "app.domain.validation.reconcile.reconcile_aggregate",
        fake_reconcile_aggregate,
    )

    result = await reconcile_stage.reconcile_node({
        "session_id": "session-1",
        "run_id": "run-1",
        "artifact_refs": {},
        "retry_counts": {},
    })

    assert result == {"ok": True}
    assert calls["program"] is program
    assert calls["specs"] == []
    assert calls["grounding_result"] is grounding
    assert calls["changeset"] is changeset
    assert calls["planned_state"] is planned_state
    assert calls["intent"] is intent
    assert calls["execution_plan"] is execution_plan
    assert calls["execution_result"] is execution_result
