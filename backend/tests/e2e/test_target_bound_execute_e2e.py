import pytest
from types import SimpleNamespace

import asyncio


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


def test_select_aggregate_assigns_duplicate_facility_types_once_per_target(monkeypatch):
    from app.agent.select.aggregate import select_aggregate
    from app.modules.schema.contracts.grounding_contracts import GroundingResult
    from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent
    from app.modules.spatial_ops.selection import PlacementDecision

    placed = FacilityTarget(target_id="facility-placed", type="卫生室")
    unplaced = FacilityTarget(target_id="facility-unplaced", type="卫生室")
    intent = SpatialPlanningIntent(facilities=[placed, unplaced])
    context = SimpleNamespace(
        session_id="select-assignment-test",
        bundle=SimpleNamespace(polygons={"landuse_current": []}),
        village_anchors=[],
        constraint_index=None,
    )

    def place(facility, *args):
        if facility.target_id == "facility-placed":
            facility.anchor_point = (116.0, 24.0)
            return PlacementDecision(
                target_id=facility.target_id,
                selected_bsm="P-1",
                anchor_point=facility.anchor_point,
                selected_score=0.8,
                status="placed",
            ), "P-1"
        return PlacementDecision(
            target_id=facility.target_id,
            status="unplaced",
        ), ""

    monkeypatch.setattr("app.agent.select.aggregate._place_facility", place)

    decision, _ = select_aggregate(GroundingResult(), intent, context)

    assignments = {item.target_id: item for item in decision.target_assignments}
    assert len(decision.target_assignments) == 2
    assert set(assignments) == {"facility-placed", "facility-unplaced"}
    assert assignments["facility-placed"].status == "placed"
    assert assignments["facility-placed"].anchor_point == (116.0, 24.0)
    assert assignments["facility-placed"].target_binding["target_id"] == "facility-placed"
    assert assignments["facility-unplaced"].status == "unplaced"
    assert assignments["facility-unplaced"].target_binding["target_id"] == "facility-unplaced"


def test_execute_runtime_route_builds_kg_from_plan_scope_not_stale_intent(monkeypatch):
    from app.agent.bootstrap import post_l3_main_nodes
    from app.agent.execute.nodes.route_prepare import _route_tasks_node
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType
    from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision, TargetAssignment

    task = WorkerTask(
        task_id="facility_placement:facility-active",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id="facility-active",
        target_type="facility",
        expected_output_kind="point",
        assignment=TargetAssignment(
            target_id="facility-active",
            target_type="facility",
            status="placed",
            anchor_point=(116.0, 24.0),
            expected_output_kind="point",
            target_binding={"target_id": "facility-active", "type": "卫生室"},
        ),
    )
    plan = ExecutionPlan(worker_tasks=[task])
    stale_intent = SpatialPlanningIntent(facilities=[
        FacilityTarget(target_id="facility-deferred", type="卫生室"),
        FacilityTarget(target_id="facility-active", type="卫生室"),
    ])
    captured = {}
    context = SimpleNamespace(version="1", bundle=None, village_anchors=[], kg=object(), kg_session_ref="")
    context.snapshot_meta = lambda: {"session_id": "runtime-route", "version": "1"}

    class Graph:
        async def ainvoke(self, state, config):
            captured["route"] = await _route_tasks_node(state)
            return {"parcel_changeset": None, "execution_errors": [], "worker_conflict_diagnostics": []}

    async def require_context(state):
        return context

    def load_artifact(state, key, model):
        if key == "intent_compilation":
            return IntentCompilationResult(typed_intent=stale_intent)
        if key == "site_selection":
            return SiteSelectionDecision()
        if key == "execution_plan":
            return plan
        return None

    monkeypatch.setattr(post_l3_main_nodes, "_require_context", require_context)
    monkeypatch.setattr(post_l3_main_nodes, "_load_ref_artifact", load_artifact)
    monkeypatch.setattr(post_l3_main_nodes, "_persist_artifact", lambda *args: {"artifact_id": args[2]})
    monkeypatch.setattr("app.services.runtime.PlanningRuntimeService._execute_subgraph", Graph())
    monkeypatch.setattr(
        "app.modules.kg.builder.layer3.build_intent_layer",
        lambda kg, intent: captured.setdefault("kg_target_ids", [item.target_id for item in intent.facilities]),
    )
    monkeypatch.setattr(
        "app.modules.kg.manager.get_kg_manager",
        lambda: SimpleNamespace(get_session_kg=lambda session_id: SimpleNamespace(
            g=SimpleNamespace(
                subjects=lambda predicate, entity_type: ["facility"] if str(entity_type).endswith("FacilityTarget") else [],
                objects=lambda subject, predicate: ["facility-active"],
            ),
        )),
    )

    asyncio.run(post_l3_main_nodes.execute_node({"session_id": "runtime-route"}))

    assert captured["kg_target_ids"] == ["facility-active"]
    assert captured["route"]["tasks_to_run"] == ["facility"]
    assert "execution_errors" not in captured["route"]


def test_execution_outcome_persistence_marks_unresolved_and_deferred_tasks(monkeypatch):
    from app.agent.bootstrap import post_l3_main_nodes
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType, WorkerResult
    from app.modules.schema.contracts.parse_contracts import RoadTarget, SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision, TargetAssignment

    def road_task(target_id):
        return WorkerTask(
            task_id=f"road_construction:{target_id}",
            worker_type=WorkerType.ROAD_CONSTRUCTION,
            target_id=target_id,
            target_type="road",
            expected_output_kind="line",
            assignment=TargetAssignment(
                target_id=target_id,
                target_type="road",
                expected_output_kind="line",
                target_binding={"target_id": target_id, "road_level": "村道"},
            ),
        )

    active = road_task("road-active")
    deferred = road_task("road-deferred")
    plan = ExecutionPlan(worker_tasks=[active], deferred_tasks=[deferred])
    context = SimpleNamespace(version="1", bundle=None, village_anchors=[], kg=None, kg_session_ref="")
    context.snapshot_meta = lambda: {"session_id": "outcome-status", "version": "1"}
    captured = []

    class Graph:
        async def ainvoke(self, state, config):
            return {
                "parcel_changeset": None,
                "tasks_to_run": [],
                "execution_errors": [{"stage": "road", "code": "road_deferred", "message": "deferred"}],
                "worker_results": [WorkerResult(
                    worker_type="road",
                    unresolved_items=[{"code": "road_unresolved", "message": "no route"}],
                )],
                "worker_conflict_diagnostics": [],
            }

    async def require_context(state):
        return context

    def load_artifact(state, key, model):
        if key == "intent_compilation":
            return IntentCompilationResult(typed_intent=SpatialPlanningIntent(road_targets=[RoadTarget(target_id="road-active")]))
        if key == "site_selection":
            return SiteSelectionDecision()
        if key == "execution_plan":
            return plan
        return None

    monkeypatch.setattr(post_l3_main_nodes, "_require_context", require_context)
    monkeypatch.setattr(post_l3_main_nodes, "_load_ref_artifact", load_artifact)
    monkeypatch.setattr(post_l3_main_nodes, "_persist_artifact", lambda state, module, kind, payload: captured.append((kind, payload)) or {"artifact_id": kind})
    monkeypatch.setattr("app.services.runtime.PlanningRuntimeService._execute_subgraph", Graph())

    asyncio.run(post_l3_main_nodes.execute_node({"session_id": "outcome-status"}))

    outcome = next(payload for kind, payload in captured if kind == "ExecutionOutcome")
    statuses = {item.target_id: item.status for item in outcome.task_results}
    assert statuses == {"road-active": "failed", "road-deferred": "deferred"}
