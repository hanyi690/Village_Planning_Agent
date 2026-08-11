import pytest
from types import SimpleNamespace

import asyncio


pytestmark = pytest.mark.e2e


def _line_task(worker_type, target_id, target_type, binding):
    from app.modules.schema.contracts.execution_plan_contracts import WorkerTask
    from app.modules.schema.contracts.selection_contracts import TargetAssignment

    return WorkerTask(
        task_id=f"{worker_type.value}:{target_id}",
        worker_type=worker_type,
        target_id=target_id,
        target_type=target_type,
        expected_output_kind="line",
        assignment=TargetAssignment(
            target_id=target_id,
            target_type=target_type,
            expected_output_kind="line",
            target_binding=binding,
        ),
    )


def _persisted_outcome(monkeypatch, session_id, plan, intent, worker_result, route):
    from app.agent.bootstrap import post_l3_main_nodes
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision

    context = SimpleNamespace(version="1", bundle=None, village_anchors=[], kg=None, kg_session_ref="")
    context.snapshot_meta = lambda: {"session_id": session_id, "version": "1"}
    captured = []

    class Graph:
        async def ainvoke(self, state, config):
            return {
                "parcel_changeset": None,
                "tasks_to_run": [route],
                "execution_errors": [],
                "worker_results": [worker_result],
                "worker_conflict_diagnostics": [],
            }

    async def require_context(state):
        return context

    def load_artifact(state, key, model):
        if key == "intent_compilation":
            return IntentCompilationResult(typed_intent=intent)
        if key == "site_selection":
            return SiteSelectionDecision()
        if key == "execution_plan":
            return plan
        return None

    monkeypatch.setattr(post_l3_main_nodes, "_require_context", require_context)
    monkeypatch.setattr(post_l3_main_nodes, "_load_ref_artifact", load_artifact)
    monkeypatch.setattr(post_l3_main_nodes, "_persist_artifact", lambda state, module, kind, payload: captured.append((kind, payload)) or {"artifact_id": kind})
    monkeypatch.setattr("app.services.runtime.PlanningRuntimeService._execute_subgraph", Graph())
    asyncio.run(post_l3_main_nodes.execute_node({"session_id": session_id}))
    return next(payload for kind, payload in captured if kind == "ExecutionOutcome")


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
    context = SimpleNamespace(version="1", bundle=None, village_anchors=[], kg=None, kg_session_ref="")
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
        "app.modules.kg.manager.get_kg_manager",
        lambda: SimpleNamespace(get_session_kg=lambda session_id: SimpleNamespace(
            g=SimpleNamespace(
                subjects=lambda predicate, entity_type: ["facility"] if str(entity_type).endswith("FacilityTarget") else [],
                objects=lambda subject, predicate: ["facility-active"],
            ),
        )),
    )

    asyncio.run(post_l3_main_nodes.execute_node({"session_id": "runtime-route"}))

    assert captured["route"]["tasks_to_run"] == ["facility"]
    assert "execution_errors" not in captured["route"]


@pytest.mark.asyncio
async def test_execute_wrapper_preserves_l4_failure_and_routes_terminal_diagnostic(monkeypatch):
    from langgraph.graph import END, START, StateGraph

    from app.agent.bootstrap import graph as bootstrap_graph
    from app.agent.bootstrap import post_l3_main_nodes, stage_audit
    from app.agent.plan_state.state import AgentState
    from app.modules.schema.contracts.execution_plan_contracts import (
        ExecutionPlan,
        ExecutionResult,
        WorkerResult,
        WorkerTask,
        WorkerType,
    )
    from app.modules.schema.contracts.parse_contracts import (
        FacilityTarget,
        SpatialPlanningIntent,
    )
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import (
        SiteSelectionDecision,
        TargetAssignment,
    )

    target_id = "facility-l4-coverage"
    task = WorkerTask(
        task_id=f"facility_placement:{target_id}",
        worker_type=WorkerType.FACILITY_PLACEMENT,
        target_id=target_id,
        target_type="facility",
        expected_output_kind="point",
        assignment=TargetAssignment(
            target_id=target_id,
            target_type="facility",
            status="placed",
            anchor_point=(116.0, 24.0),
            expected_output_kind="point",
            target_binding={"target_id": target_id, "type": "卫生室"},
        ),
    )
    execution_plan = ExecutionPlan(worker_tasks=[task])
    intent = SpatialPlanningIntent(
        facilities=[FacilityTarget(target_id=target_id, type="卫生室")]
    )
    context = SimpleNamespace(
        version="1",
        bundle=None,
        village_anchors=[],
        kg=None,
        kg_session_ref="",
    )
    context.snapshot_meta = lambda: {
        "session_id": "execute-l4-terminal",
        "version": "1",
    }
    captured = {}

    class ExecuteGraph:
        async def ainvoke(self, state, config):
            return {
                "parcel_changeset": SimpleNamespace(changes=[]),
                "layout_configs": [],
                "tasks_to_run": ["facility"],
                "worker_results": [
                    WorkerResult(
                        worker_type="facility",
                        task_results=[
                            ExecutionResult(
                                task_id=task.task_id,
                                target_id=target_id,
                                status="succeeded",
                                expected_output_kind="point",
                            )
                        ],
                    )
                ],
                "execution_errors": [],
                "worker_conflict_diagnostics": [],
                "validation_result": {"passed": True},
            }

    async def require_context(_state):
        return context

    def load_artifact(_state, key, _model):
        if key == "intent_compilation":
            return IntentCompilationResult(typed_intent=intent)
        if key == "site_selection":
            return SiteSelectionDecision()
        if key == "execution_plan":
            return execution_plan
        return None

    async def fail_l4_write(execute_state):
        captured["execution_outcome"] = execute_state.execution_outcome
        return {
            "l4_write_error": "execution_outcome_target_coverage",
            "missing_targets": [[target_id, "point"]],
            "execution_outcome_target_ids": [],
        }

    async def skip_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(post_l3_main_nodes, "_require_context", require_context)
    monkeypatch.setattr(post_l3_main_nodes, "_load_ref_artifact", load_artifact)
    monkeypatch.setattr(
        post_l3_main_nodes,
        "_persist_artifact",
        lambda _state, _module, kind, _payload: {
            "artifact_id": kind,
            "artifact_type": kind,
            "semantic_checksum": f"{kind}-content",
        },
    )
    monkeypatch.setattr(
        "app.services.runtime.PlanningRuntimeService._execute_subgraph",
        ExecuteGraph(),
    )
    monkeypatch.setattr(
        "app.agent.execute.planned_state_builder.changeset_to_planned_state",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.agent.execute.nodes.write_l4._write_l4_node",
        fail_l4_write,
    )
    monkeypatch.setattr(stage_audit, "_save", skip_audit)
    monkeypatch.setattr(
        bootstrap_graph,
        "_diagnostic_manifest_patch",
        lambda *args, **kwargs: {},
    )

    builder = StateGraph(AgentState)
    builder.add_node("execute", post_l3_main_nodes.execute_node)
    builder.add_node("validate", lambda _state: {"phase": "validate-reached"})
    builder.add_node(
        bootstrap_graph.END_DIAGNOSTIC,
        bootstrap_graph.end_diagnostic_node,
    )
    builder.add_edge(START, "execute")
    builder.add_conditional_edges(
        "execute",
        bootstrap_graph.route_after_execute,
        {
            "validate": "validate",
            bootstrap_graph.END_DIAGNOSTIC: bootstrap_graph.END_DIAGNOSTIC,
        },
    )
    builder.add_edge("validate", END)
    builder.add_edge(bootstrap_graph.END_DIAGNOSTIC, END)
    graph = builder.compile()

    final = await graph.ainvoke(
        {"session_id": "execute-l4-terminal", "artifact_refs": {}}
    )

    outcome = captured["execution_outcome"]
    assert outcome.task_results[0].target_id == target_id
    assert outcome.task_results[0].status == "succeeded"
    diagnostics_ref = final["artifact_refs"]["execution_diagnostics"]
    assert diagnostics_ref["artifact_type"] == "ExecutionDiagnostics"
    assert final["fatal_error"] == {
        "stage": "EXECUTE",
        "code": "execution_outcome_target_coverage",
        "message": "L4 write failed: execution_outcome_target_coverage",
        "missing_targets": [[target_id, "point"]],
    }
    assert final["delivery_status"] == "diagnostic_only"
    assert final["diagnostic_terminal"]["stage"] == "execute"
    assert final["diagnostic_terminal"]["reason"] == "execution_outcome_target_coverage"
    assert final.get("phase") != "validate-reached"
    assert "EXECUTE" in final["stage_audit"]
    assert "l4_write_result" not in AgentState.__annotations__
    assert "execution_outcome_target_coverage" not in AgentState.__annotations__


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


def test_real_l3_builder_and_runtime_route_use_stable_target_ids(monkeypatch):
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.nodes.route_prepare import _route_tasks_node
    from app.agent.execute.plan_builder import build_execution_plan
    from app.modules.kg.builder.base import PlanningKG
    from app.modules.kg.builder.layer3 import build_intent_layer
    from app.modules.schema.contracts.parse_contracts import (
        AxisTarget,
        FacilityTarget,
        RoadTarget,
        SpatialPlanningIntent,
    )
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision

    intent = SpatialPlanningIntent(
        facilities=[FacilityTarget(
            target_id="facility-stable",
            source_instruction_id="legacy-facility",
            type="卫生室",
        )],
        development_axes=[AxisTarget(
            target_id="axis-stable",
            source_instruction_id="legacy-axis",
            reference_feature="主路",
        )],
        road_targets=[RoadTarget(
            target_id="road-stable",
            source_instruction_id="legacy-road",
            road_level="村道",
        )],
    )
    kg = PlanningKG(village_name="stable-target-test")
    build_intent_layer(kg, intent)
    plan = build_execution_plan(intent, SiteSelectionDecision(), [])

    monkeypatch.setattr(
        "app.modules.kg.manager.get_kg_manager",
        lambda: SimpleNamespace(get_session_kg=lambda session_id: kg),
    )

    route = asyncio.run(_route_tasks_node(ExecuteAgentState(
        session_id="stable-target-test",
        intent=SpatialPlanningIntent(),
        execution_plan=plan,
    )))

    assert route["tasks_to_run"] == ["facility", "axis", "road"]
    assert "execution_errors" not in route


def test_execution_outcome_persistence_marks_successful_zone_by_layout_route(monkeypatch):
    from app.agent.bootstrap import post_l3_main_nodes
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, ExecutionResult, WorkerResult
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent, ZoneTarget
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision, TargetAssignment
    from app.modules.schema.contracts.execution_plan_contracts import WorkerTask, WorkerType

    task = WorkerTask(
        task_id="parcel_transformation:zone-1",
        worker_type=WorkerType.PARCEL_TRANSFORMATION,
        target_id="zone-1",
        target_type="zone",
        expected_output_kind="polygon",
        assignment=TargetAssignment(
            target_id="zone-1",
            target_type="zone",
            expected_output_kind="polygon",
            target_binding={"target_id": "zone-1", "land_use": "居住用地"},
        ),
    )
    plan = ExecutionPlan(worker_tasks=[task])
    context = SimpleNamespace(version="1", bundle=None, village_anchors=[], kg=None, kg_session_ref="")
    context.snapshot_meta = lambda: {"session_id": "zone-outcome", "version": "1"}
    captured = []

    class Graph:
        async def ainvoke(self, state, config):
            return {
                "parcel_changeset": None,
                "tasks_to_run": ["layout"],
                "execution_errors": [],
                "worker_results": [WorkerResult(
                    worker_type="zone",
                    task_results=[ExecutionResult(
                        task_id=task.task_id,
                        target_id=task.target_id,
                        status="succeeded",
                        expected_output_kind="polygon",
                        output_artifacts=["polygon"],
                    )],
                )],
                "worker_conflict_diagnostics": [],
            }

    async def require_context(state):
        return context

    def load_artifact(state, key, model):
        if key == "intent_compilation":
            return IntentCompilationResult(typed_intent=SpatialPlanningIntent(zone_targets=[ZoneTarget(target_id="zone-1")]))
        if key == "site_selection":
            return SiteSelectionDecision()
        if key == "execution_plan":
            return plan
        return None

    monkeypatch.setattr(post_l3_main_nodes, "_require_context", require_context)
    monkeypatch.setattr(post_l3_main_nodes, "_load_ref_artifact", load_artifact)
    monkeypatch.setattr(post_l3_main_nodes, "_persist_artifact", lambda state, module, kind, payload: captured.append((kind, payload)) or {"artifact_id": kind})
    monkeypatch.setattr("app.services.runtime.PlanningRuntimeService._execute_subgraph", Graph())

    asyncio.run(post_l3_main_nodes.execute_node({"session_id": "zone-outcome"}))

    outcome = next(payload for kind, payload in captured if kind == "ExecutionOutcome")
    assert outcome.task_results[0].status == "succeeded"


def test_execution_outcome_persistence_keeps_mixed_facility_task_statuses(monkeypatch):
    from app.agent.bootstrap import post_l3_main_nodes
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, ExecutionResult, WorkerResult
    from app.modules.schema.contracts.parse_contracts import FacilityTarget, SpatialPlanningIntent
    from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
    from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision, TargetAssignment
    from app.modules.schema.contracts.execution_plan_contracts import WorkerTask, WorkerType

    def task(target_id):
        return WorkerTask(
            task_id=f"facility_placement:{target_id}",
            worker_type=WorkerType.FACILITY_PLACEMENT,
            target_id=target_id,
            target_type="facility",
            expected_output_kind="point",
            assignment=TargetAssignment(
                target_id=target_id,
                target_type="facility",
                expected_output_kind="point",
                target_binding={"target_id": target_id, "type": "卫生室"},
            ),
        )

    succeeded = task("facility-ok")
    failed = task("facility-failed")
    plan = ExecutionPlan(worker_tasks=[succeeded, failed])
    context = SimpleNamespace(version="1", bundle=None, village_anchors=[], kg=None, kg_session_ref="")
    context.snapshot_meta = lambda: {"session_id": "facility-outcome", "version": "1"}
    captured = []

    class Graph:
        async def ainvoke(self, state, config):
            return {
                "parcel_changeset": None,
                "tasks_to_run": ["facility"],
                "execution_errors": [],
                "worker_results": [WorkerResult(
                    worker_type="facility",
                    task_results=[
                        ExecutionResult(task_id=succeeded.task_id, target_id=succeeded.target_id, status="succeeded", expected_output_kind="point"),
                        ExecutionResult(task_id=failed.task_id, target_id=failed.target_id, status="failed", expected_output_kind="point", errors=["no anchor"]),
                    ],
                )],
                "worker_conflict_diagnostics": [],
            }

    async def require_context(state):
        return context

    def load_artifact(state, key, model):
        if key == "intent_compilation":
            return IntentCompilationResult(typed_intent=SpatialPlanningIntent(facilities=[
                FacilityTarget(target_id="facility-ok", type="卫生室"),
                FacilityTarget(target_id="facility-failed", type="卫生室"),
            ]))
        if key == "site_selection":
            return SiteSelectionDecision()
        if key == "execution_plan":
            return plan
        return None

    monkeypatch.setattr(post_l3_main_nodes, "_require_context", require_context)
    monkeypatch.setattr(post_l3_main_nodes, "_load_ref_artifact", load_artifact)
    monkeypatch.setattr(post_l3_main_nodes, "_persist_artifact", lambda state, module, kind, payload: captured.append((kind, payload)) or {"artifact_id": kind})
    monkeypatch.setattr("app.services.runtime.PlanningRuntimeService._execute_subgraph", Graph())

    asyncio.run(post_l3_main_nodes.execute_node({"session_id": "facility-outcome"}))

    outcome = next(payload for kind, payload in captured if kind == "ExecutionOutcome")
    assert {item.target_id: item.status for item in outcome.task_results} == {
        "facility-ok": "succeeded",
        "facility-failed": "failed",
    }


def test_axis_worker_persists_mixed_target_outcomes(monkeypatch):
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.nodes.axis_worker import _axis_worker
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, WorkerType
    from app.modules.schema.contracts.parse_contracts import AxisTarget, SpatialPlanningIntent

    axes = [
        AxisTarget(target_id="axis-ok", label="轴线一"),
        AxisTarget(target_id="axis-missing", label="轴线二"),
    ]
    tasks = [
        _line_task(WorkerType.AXIS_CONSTRUCTION, axis.target_id, "axis", axis.model_dump(mode="json"))
        for axis in axes
    ]

    def build(self, intent, **kwargs):
        axis = intent.axes[0]
        if axis.target_id == "axis-ok":
            return {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"name": axis.label},
                    "geometry": {"type": "LineString", "coordinates": [[116.0, 24.0], [116.1, 24.1]]},
                }],
            }
        return None

    monkeypatch.setattr("app.modules.spatial_ops.geometry.axis_builder.AxisBuilder.build", build)
    plan = ExecutionPlan(worker_tasks=tasks)
    result = _axis_worker(ExecuteAgentState(
        intent=SpatialPlanningIntent(development_axes=axes),
        execution_plan=plan,
        tasks_to_run=["axis"],
    ))

    assert {item.target_id: item.status for item in result.task_results} == {
        "axis-ok": "succeeded",
        "axis-missing": "failed",
    }
    assert result.layers[0]["data"]["features"][0]["properties"]["target_id"] == "axis-ok"
    outcome = _persisted_outcome(
        monkeypatch,
        "axis-mixed-outcome",
        plan,
        SpatialPlanningIntent(development_axes=axes),
        result,
        "axis",
    )
    assert {item.target_id: item.status for item in outcome.task_results} == {
        "axis-ok": "succeeded",
        "axis-missing": "failed",
    }


def test_road_worker_persists_mixed_target_outcomes_from_real_planner(monkeypatch, tmp_path):
    from app.agent.execute.execute_state import ExecuteAgentState
    from app.agent.execute.nodes.road_worker import _road_worker
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, WorkerType
    from app.modules.schema.contracts.parse_contracts import RoadTarget, SpatialPlanningIntent

    roads = [
        RoadTarget(
            target_id="road-access",
            road_level="村道",
            start_anchor=(116.004, 24.0005),
            end_anchor=(116.012, 24.0),
            semantic={"raw_text": "修复村道"},
        ),
        RoadTarget(
            target_id="road-on-network",
            road_level="村道",
            start_anchor=(116.02, 24.0),
            end_anchor=(116.025, 24.0),
            semantic={"raw_text": "修复村道"},
        ),
    ]
    tasks = [
        _line_task(WorkerType.ROAD_CONSTRUCTION, road.target_id, "road", road.model_dump(mode="json"))
        for road in roads
    ]
    crs = {"type": "name", "properties": {"name": "EPSG:4326"}}
    gis_data = {
        "road_geojson": {
            "type": "FeatureCollection",
            "crs": crs,
            "features": [{
                "type": "Feature",
                "properties": {"name": "existing-road"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[116.0, 24.0], [116.03, 24.0]],
                },
            }],
        },
        "boundary_geojson": {
            "type": "FeatureCollection",
            "crs": crs,
            "features": [{
                "type": "Feature",
                "properties": {"name": "test-boundary"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[115.99, 23.99], [116.04, 23.99], [116.04, 24.01], [115.99, 24.01], [115.99, 23.99]]],
                },
            }],
        },
        "landuse_current_geojson": {
            "type": "FeatureCollection",
            "crs": crs,
            "features": [{
                "type": "Feature",
                "properties": {"land_use": "建设用地"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[115.99, 23.99], [116.04, 23.99], [116.04, 24.01], [115.99, 24.01], [115.99, 23.99]]],
                },
            }],
        },
    }
    monkeypatch.setattr("app.agent.execute.road_generator._project_root", lambda: tmp_path)
    plan = ExecutionPlan(worker_tasks=tasks)
    result = _road_worker(ExecuteAgentState(
        session_id="road-real-provenance",
        gis_data=gis_data,
        intent=SpatialPlanningIntent(road_targets=roads),
        execution_plan=plan,
        tasks_to_run=["road"],
    ))

    candidate_properties = [
        feature["properties"]
        for layer in result.layers
        if layer.get("layerType") == "planned_road_candidates"
        for feature in layer["data"]["features"]
    ]
    access_properties = [
        properties
        for properties in candidate_properties
        if properties.get("target_id") == "road-access"
    ]
    assert access_properties
    assert all(properties["target_ids"] == ["road-access"] for properties in access_properties)
    assert all(properties["source_id"] != "road-access" for properties in access_properties)
    assert {item.target_id: item.status for item in result.task_results} == {
        "road-access": "succeeded",
        "road-on-network": "failed",
    }
    outcome = _persisted_outcome(
        monkeypatch,
        "road-real-provenance",
        plan,
        SpatialPlanningIntent(road_targets=roads),
        result,
        "road",
    )
    assert {item.target_id: item.status for item in outcome.task_results} == {
        "road-access": "succeeded",
        "road-on-network": "failed",
    }
