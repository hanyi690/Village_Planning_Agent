"""EXECUTE must never synthesize a planning classification."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.materialization.plan_builder import build_execution_plan
from app.modules.schema.contracts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
)
from app.modules.schema.contracts.deferral_contracts import (
    DeferralLedger,
    HumanDeferralDecision,
    TargetDeferral,
)
from app.modules.schema.contracts.selection_contracts import TargetAssignment
from app.workflow.stages import execute as execute_stage


def _target(
    target_id: str,
    *,
    output_kind: str,
    execution_mode: str = "spatial",
    classification_decision=None,
):
    return SimpleNamespace(
        target_id=target_id,
        execution_mode=execution_mode,
        expected_output_kind=output_kind,
        classification_decision=classification_decision,
    )


def _intent(*targets):
    fields = {
        "project_targets": [],
        "zone_targets": [],
        "facilities": [],
        "development_axes": [],
        "road_targets": [],
    }
    for target_type, target in targets:
        fields[
            {
                "project": "project_targets",
                "zone": "zone_targets",
                "facility": "facilities",
                "axis": "development_axes",
                "road": "road_targets",
            }[target_type]
        ].append(target)
    return SimpleNamespace(**fields)


def _selection(*targets):
    return SimpleNamespace(
        target_assignments=[
            TargetAssignment(
                target_id=target.target_id,
                target_type=target_type,
                expected_output_kind=target.expected_output_kind,
                target_binding={"target_id": target.target_id},
            )
            for target_type, target in targets
        ]
    )


def _resolved_decision(target_id: str) -> ClassificationDecision:
    return ClassificationDecision(
        target_id=target_id,
        code_system=ClassificationSystem.VNE,
        candidate_codes=["V11"],
        selected_code="V11",
        evidence_refs=["human-review:classification"],
        status="resolved",
    )


def _ledger_for(target_id: str) -> DeferralLedger:
    return DeferralLedger(
        entries=(
            TargetDeferral(
                target_id=target_id,
                reason="classification requires an explicit decision",
                source_refs=("artifact:human-review",),
                decision=HumanDeferralDecision(
                    decision_id=f"defer-{target_id}",
                    decided_by="human-review",
                    rationale="classification is not resolved",
                ),
            ),
        )
    )


def test_unresolved_polygon_without_ledger_is_not_a_worker_task():
    target = _target("zone-1", output_kind="polygon")

    plan = build_execution_plan(
        _intent(("zone", target)),
        _selection(("zone", target)),
        [],
    )

    assert plan.worker_tasks == []
    assert plan.deferred_tasks == []


def test_unresolved_polygon_with_ledger_is_explicitly_deferred():
    target = _target("zone-1", output_kind="polygon")

    plan = build_execution_plan(
        _intent(("zone", target)),
        _selection(("zone", target)),
        [],
        deferral_ledger=_ledger_for(target.target_id),
    )

    assert plan.worker_tasks == []
    assert [task.target_id for task in plan.deferred_tasks] == [target.target_id]


def test_resolved_polygon_enters_worker_tasks():
    target = _target(
        "zone-1",
        output_kind="polygon",
        classification_decision=_resolved_decision("zone-1"),
    )

    plan = build_execution_plan(
        _intent(("zone", target)),
        _selection(("zone", target)),
        [],
    )

    assert [task.target_id for task in plan.worker_tasks] == [target.target_id]
    assert plan.deferred_tasks == []


@pytest.mark.asyncio
async def test_execute_entry_returns_diagnostic_before_context_or_workers(monkeypatch):
    target = _target("zone-1", output_kind="polygon")
    intent = _intent(("zone", target))
    selection = _selection(("zone", target))
    loaded = {
        "target_projection": intent,
        "site_selection": selection,
        "execution_plan": build_execution_plan(intent, selection, []),
        "deferral_ledger": None,
    }

    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )

    async def context_must_not_be_loaded(state):
        raise AssertionError("classification failure must stop before context/workers")

    monkeypatch.setattr(execute_stage, "_require_context", context_must_not_be_loaded)

    result = await execute_stage.execute_node(
        {"run_id": "run-1", "session_id": "run-1", "artifact_refs": {}}
    )

    assert result["fatal_error"]["code"] == "classification_decision_required"
    assert result["delivery_status"] == "diagnostic_only"
    assert result["artifact_refs"] == {"execution_diagnostics": {"digest": "diagnostic"}}


@pytest.mark.parametrize(
    ("target_type", "output_kind", "execution_mode"),
    [
        ("project", "point", "spatial"),
        ("project", "action", "non_spatial"),
        ("axis", "line", "spatial"),
    ],
)
def test_point_action_line_targets_keep_existing_passthrough(
    target_type: str, output_kind: str, execution_mode: str
):
    target = _target(
        f"{target_type}-1",
        output_kind=output_kind,
        execution_mode=execution_mode,
    )

    plan = build_execution_plan(
        _intent((target_type, target)),
        _selection((target_type, target)),
        [],
    )

    assert [task.target_id for task in plan.worker_tasks] == [target.target_id]
