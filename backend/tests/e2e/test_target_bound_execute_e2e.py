import pytest


pytestmark = pytest.mark.e2e


def test_worker_task_carries_stable_target_assignment_binding():
    from app.modules.schema.contracts.selection_contracts import TargetAssignment

    assignment = TargetAssignment(
        target_id="facility-2",
        target_type="facility",
        selected_bsm="parcel-2",
        anchor_point=(116.0, 24.0),
        expected_output_kind="point",
        target_binding={"type": "卫生室", "target_id": "facility-2"},
    )

    assert assignment.target_id == "facility-2"
    assert assignment.anchor_point == (116.0, 24.0)


def test_plan_binding_wins_over_stale_intent_for_facility_anchor():
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.nodes.facility_worker import _facility_worker
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
    from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent
    from app.modules.schema.contracts.selection_contracts import TargetAssignment

    task = WorkerTask(
        task_id="facility_placement:facility-2",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id="facility-2",
        target_type="facility",
        expected_output_kind="point",
        assignment=TargetAssignment(
            target_id="facility-2",
            target_type="facility",
            status="placed",
            anchor_point=(116.0, 24.0),
            expected_output_kind="point",
            target_binding={"target_id": "facility-2", "type": "卫生室"},
        ),
    )
    stale_intent = SpatialPlanningIntent(
        facilities=[FacilityTarget(target_id="facility-2", type="卫生室")]
    )

    result = _facility_worker(
        ExecuteAgentState(
            intent=stale_intent,
            execution_plan=ExecutionPlan(schema_version="2.0", worker_tasks=[task]),
        )
    )

    feature = result.layers[0]["data"]["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["geometry"]["coordinates"] == [116.0, 24.0]


def test_plan_uses_duplicate_target_ids_and_excludes_ledger_deferred_targets():
    from app.agent.execute.plan_builder import build_execution_plan
    from app.modules.schema.contracts.deferral_contracts import DeferralLedger, HumanDeferralDecision, TargetDeferral
    from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision, TargetAssignment

    intent = SpatialPlanningIntent(facilities=[
        FacilityTarget(target_id="facility-1", type="卫生室", anchor_point=(116.0, 24.0)),
        FacilityTarget(target_id="facility-2", type="卫生室", anchor_point=(117.0, 25.0)),
    ])
    selection = SiteSelectionDecision(target_assignments=[
        TargetAssignment(
            target_id=facility.target_id,
            target_type="facility",
            status="placed",
            anchor_point=facility.anchor_point,
            expected_output_kind="point",
            target_binding=facility.model_dump(mode="json"),
        )
        for facility in intent.facilities
    ])
    ledger = DeferralLedger(entries=(TargetDeferral(
        target_id="facility-1",
        reason="human deferral",
        decision=HumanDeferralDecision(decision_id="review-1"),
    ),))

    plan = build_execution_plan(intent, selection, [], deferral_ledger=ledger)

    assert [task.target_id for task in plan.worker_tasks] == ["facility-2"]
    assert plan.worker_tasks[0].assignment.anchor_point == (117.0, 25.0)
    assert [task.target_id for task in plan.deferred_tasks] == ["facility-1"]
