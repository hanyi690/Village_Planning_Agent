"""EXECUTE must never synthesize a planning classification."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.materialization.execution_boundaries import classification_boundary_diagnostics
from app.contracts.artifacts.classification_ref import (
    ClassificationDecision,
    ClassificationSystem,
)
from app.contracts.artifacts.deferral_contracts import (
    DeferralLedger,
    HumanDeferralDecision,
    TargetDeferral,
)
from app.contracts.workflow.materialization_contracts import TargetAssignment
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
from app.workflow.stages import execute as execute_stage


def build_execution_plan(intent, selection, _briefs, *, deferral_ledger=None, **_kwargs):
    """Test-local plan fixture for classification admission behavior."""
    target_by_id = {
        target.target_id: target
        for field in ("site_area_targets", "zone_targets", "facilities", "development_axes", "road_targets")
        for target in getattr(intent, field, [])
    }
    assignments = {item.target_id: item for item in selection.target_assignments}
    deferred_ids = {entry.target_id for entry in (getattr(deferral_ledger, "entries", None) or [])}
    worker_types = {
        "site_area": WorkerType.SITE_AREA_FOOTPRINT,
        "zone": WorkerType.PARCEL_TRANSFORMATION,
        "facility": WorkerType.FACILITY_PLACEMENT,
        "axis": WorkerType.AXIS_CONSTRUCTION,
        "road": WorkerType.ROAD_CONSTRUCTION,
    }
    workers, deferred = [], []
    for target_id, assignment in assignments.items():
        target = target_by_id[target_id]
        requires = (
            target.expected_output_kind in {"parcel", "polygon"}
            and target.materialization_role not in {"functional_overlay", "protection_overlay", "restoration_overlay"}
        )
        resolved = getattr(getattr(target, "classification_decision", None), "status", "") == "resolved"
        if requires and not resolved:
            if target_id in deferred_ids:
                deferred.append(WorkerTask(
                    task_id=f"deferred:{target_id}", worker_type=WorkerType.PARCEL_TRANSFORMATION,
                    target_id=target_id, target_type=assignment.target_type,
                    expected_output_kind=assignment.expected_output_kind, assignment=assignment,
                    defer_reason="classification requires an explicit decision",
                ))
            continue
        workers.append(WorkerTask(
            task_id=f"task:{target_id}", worker_type=worker_types.get(assignment.target_type, WorkerType.PARCEL_TRANSFORMATION),
            target_id=target_id, target_type=assignment.target_type,
            expected_output_kind=assignment.expected_output_kind, assignment=assignment,
        ))
    return ExecutionPlan(worker_tasks=workers, deferred_tasks=deferred)


def _target(
    target_id: str,
    *,
    output_kind: str,
    execution_mode: str = "spatial",
    classification_decision=None,
    materialization_role: str = "",
):
    return SimpleNamespace(
        target_id=target_id,
        execution_mode=execution_mode,
        expected_output_kind=output_kind,
        classification_decision=classification_decision,
        materialization_role=materialization_role,
    )


def _intent(*targets):
    fields = {
        "site_area_targets": [],
        "zone_targets": [],
        "facilities": [],
        "development_axes": [],
        "road_targets": [],
    }
    for target_type, target in targets:
        fields[
            {
                "site_area": "site_area_targets",
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


def test_overlay_polygon_does_not_require_land_use_classification():
    target = _target(
        "overlay-1",
        output_kind="polygon",
        materialization_role="protection_overlay",
    )

    plan = build_execution_plan(
        _intent(("site_area", target)),
        _selection(("site_area", target)),
        [],
    )

    assert [task.target_id for task in plan.worker_tasks] == [target.target_id]
    assert classification_boundary_diagnostics(_intent(("site_area", target)), plan) == []


@pytest.mark.asyncio
async def test_execute_entry_stops_unapproved_unclassified_scope(monkeypatch):
    # EXECUTE must never continue a reduced scope under an old approval.
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
        lambda state, stage, schema_id, payload: {"digest": "deferred"},
    )

    result = await execute_stage.execute_node(
        {"run_id": "run-1", "session_id": "run-1", "artifact_refs": {}}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_APPROVED_INPUT_REQUIRED"
    assert result["delivery_status"] == "diagnostic_only"


@pytest.mark.parametrize(
    ("target_type", "output_kind", "execution_mode"),
    [
        ("site_area", "point", "spatial"),
        ("site_area", "action", "non_spatial"),
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
