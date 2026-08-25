from __future__ import annotations

import pytest

from app.contracts.planning.intent_graph import (
    PlanRelationIntent,
    PlanTargetNode,
    PlanningIntentGraph,
)
from app.contracts.planning.task_graph import PlanningTask, PlanningTaskGraph
from app.contracts.program import PlanningClaim
from app.contracts.domain.planning_semantics import RoadPlanningParameters
from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
from app.domain.program.target_projection.planning_task_graph_compiler import (
    compile_planning_task_graph,
    intent_graph_with_pending_claims,
    pending_claim_grounding_specs,
)
from app.evidence.retrieval.requirements import requirements_from_target_projection


def _graph(*nodes: PlanTargetNode, relations: list[PlanRelationIntent] | None = None) -> PlanningIntentGraph:
    return PlanningIntentGraph(nodes=list(nodes), relations=list(relations or []))


def _tasks(graph: PlanningIntentGraph, target_id: str) -> list[PlanningTask]:
    return [task for task in compile_planning_task_graph(graph).tasks if target_id in task.target_refs]


def test_new_facility_compiles_demand_candidate_and_solver_tasks() -> None:
    node = PlanTargetNode(
        target_id="facility-1",
        target_kind="facility",
        operation="new",
        claim_refs=["claim:facility-1"],
    )

    tasks = _tasks(_graph(node), "facility-1")

    assert [task.task_kind for task in tasks] == [
        "candidate_producer",
        "evidence",
        "solver_subproblem",
    ]
    evidence = next(task for task in tasks if task.task_kind == "evidence")
    assert evidence.capability == "evidence.demand"
    assert evidence.produced_artifact_refs == ["evidence:demand:facility-1"]
    assert any(item.endswith("facility-1") for item in evidence.required_inputs)
    solver = next(task for task in tasks if task.task_kind == "solver_subproblem")
    assert solver.solver_kind == "single_choice"
    assert solver.dependency_task_ids


def test_existing_facility_uses_source_identity_instead_of_demand() -> None:
    node = PlanTargetNode(
        target_id="facility-existing",
        target_kind="facility",
        operation="preserve",
        existing_entity_ref="entity:clinic-1",
    )

    evidence = next(
        task for task in _tasks(_graph(node), "facility-existing") if task.task_kind == "evidence"
    )

    assert evidence.capability == "evidence.source_identity"
    assert evidence.required_inputs == ["source_identity:entity:clinic-1"]
    assert not any("demand" in item for item in evidence.required_inputs)


def test_road_compiles_endpoint_network_candidate_and_network_solver() -> None:
    node = PlanTargetNode(
        target_id="road-1",
        target_kind="road",
        required_capabilities=["road.construction"],
        endpoint_refs=["place:north", "place:south"],
    )

    tasks = _tasks(_graph(node), "road-1")
    capabilities = {task.capability for task in tasks}

    assert {"evidence.endpoint_binding", "evidence.network_snapshot", "road.construction"} <= capabilities
    solver = next(task for task in tasks if task.task_kind == "solver_subproblem")
    assert solver.solver_kind == "network_path"
    assert len(solver.dependency_task_ids) == 1


def test_zone_and_site_area_compile_parcel_resource_tasks() -> None:
    node = PlanTargetNode(target_id="zone-1", target_kind="zone", claim_refs=["claim:zone-1"])
    tasks = _tasks(_graph(node), "zone-1")

    assert any(task.capability == "evidence.parcel_resource_pool" for task in tasks)
    assert any(task.task_kind == "candidate_producer" for task in tasks)
    solver = next(task for task in tasks if task.task_kind == "solver_subproblem")
    assert solver.solver_kind == "parcel_assignment"


def test_topology_validation_depends_on_relevant_target_terminals() -> None:
    facility = PlanTargetNode(target_id="facility-1", target_kind="facility", claim_refs=["claim:f"])
    zone = PlanTargetNode(target_id="zone-1", target_kind="site_area", claim_refs=["claim:z"])
    relation = PlanRelationIntent(
        relation_id="part-1",
        relation_template="part_of",
        subject_ref="facility-1",
        object_ref="zone-1",
        object_ref_kind="target",
    )

    task_graph = compile_planning_task_graph(_graph(facility, zone, relations=[relation]))
    validation = next(task for task in task_graph.tasks if task.relation_refs == ["part-1"])

    assert validation.task_kind == "validation"
    assert validation.dependency_task_ids == [
        "task:facility-1:solver:facility",
        "task:zone-1:solver:parcel",
    ]
    assert "relation_parameters:part-1" in validation.required_inputs


def test_non_spatial_action_remains_a_typed_task_without_geometry() -> None:
    node = PlanTargetNode(target_id="action-1", target_kind="action", operation="new")

    tasks = _tasks(_graph(node), "action-1")

    assert len(tasks) == 1
    assert tasks[0].task_kind == "solver_subproblem"
    assert tasks[0].solver_kind == "single_choice"
    assert not any("candidate" in item for item in tasks[0].produced_artifact_refs)


def test_missing_endpoint_prerequisite_is_explicit_and_stays_planned() -> None:
    node = PlanTargetNode(target_id="road-missing", target_kind="road")
    task_graph = compile_planning_task_graph(_graph(node))
    endpoint = next(task for task in task_graph.tasks if task.capability == "evidence.endpoint_binding")
    candidate = next(task for task in task_graph.tasks if task.task_kind == "candidate_producer")

    assert endpoint.status == "planned"
    assert "missing_input:endpoint_refs:road-missing" in endpoint.diagnostics
    assert "evidence:endpoint_binding:road-missing" in candidate.required_inputs


def test_task_graph_and_compilation_requirements_are_deterministic_and_consumable() -> None:
    road = PlanTargetNode(target_id="road-1", target_kind="road", endpoint_refs=["a"])
    facility = PlanTargetNode(target_id="facility-1", target_kind="facility", claim_refs=["c"])
    first = compile_planning_task_graph(_graph(road, facility))
    second = compile_planning_task_graph(_graph(facility, road))
    result = IntentCompilationResult(
        artifact_id="projection-1",
        intent_graph=_graph(road, facility),
        planning_task_graph=first,
    )

    assert first.fingerprint == second.fingerprint
    requirements = requirements_from_target_projection(result)
    roles = {item.evidence_role for item in requirements}
    assert {
        "planning_task_evidence",
        "planning_task_candidate_producer",
        "planning_task_solver_subproblem",
    } <= roles
    assert all(item.producer_stage == "TARGET_PROJECTION" for item in requirements if item.evidence_role.startswith("planning_task_"))


def test_task_graph_rejects_unknown_dependencies_and_cycles() -> None:
    with pytest.raises(ValueError, match="unknown dependencies"):
        PlanningTaskGraph(
            tasks=[PlanningTask(task_id="a", task_kind="evidence", dependency_task_ids=["missing"])]
        )

    with pytest.raises(ValueError, match="dependency cycle"):
        PlanningTaskGraph(
            tasks=[
                PlanningTask(task_id="a", task_kind="evidence", dependency_task_ids=["b"]),
                PlanningTask(task_id="b", task_kind="evidence", dependency_task_ids=["a"]),
            ]
        )


def test_task_graph_rejects_stale_supplied_fingerprint() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        PlanningTaskGraph(
            tasks=[PlanningTask(task_id="a", task_kind="evidence")],
            fingerprint="stale",
        )


def test_pending_spatial_claim_becomes_typed_ground_work_and_task_node() -> None:
    claim = PlanningClaim(
        claim_id="pending-facility",
        dimension_key="public_service",
        statement="新增文化设施",
        planning_role="spatial_intervention",
        project_package_ref="pkg-culture",
        suggested_category="facility",
        suggested_output_kind="point",
        asset_kind="facility",
        facility_parameters={"facility_type": "文化设施", "action": "new"},
        location_hints=["社前村"],
    )

    specs = pending_claim_grounding_specs([claim])
    assert len(specs) == 1
    assert specs[0].target_id == claim.claim_id
    assert specs[0].reference is not None
    assert specs[0].reference.kind == "place_name"
    assert specs[0].unresolved_reason == "pending_grounding"

    graph = compile_planning_task_graph(PlanningIntentGraph(), pending_claims=[claim])
    target_tasks = [task for task in graph.tasks if claim.claim_id in task.target_refs]
    assert target_tasks
    assert any(task.task_kind == "candidate_producer" for task in target_tasks)
    assert any(task.task_kind == "solver_subproblem" for task in target_tasks)


def test_pending_road_task_preserves_typed_endpoints_without_spatial_requirements() -> None:
    claim = PlanningClaim(
        claim_id="pending-road",
        dimension_key="traffic",
        statement="连接村委会与北侧聚落的新建道路",
        planning_role="spatial_intervention",
        project_package_ref="pkg-road",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        intervention_action="new",
        road_parameters=RoadPlanningParameters(
            action="new",
            connects=["村委会", "北侧聚落"],
        ),
    )

    graph = compile_planning_task_graph(PlanningIntentGraph(), pending_claims=[claim])
    endpoint = next(
        task
        for task in graph.tasks
        if task.task_id == "task:pending-road:evidence:endpoint_binding"
    )

    assert set(endpoint.required_inputs) == {
        "endpoint_refs:pending-road",
        "endpoint:北侧聚落",
        "endpoint:村委会",
    }
    assert not any(item.startswith("missing_input:endpoint_refs") for item in endpoint.diagnostics)


def test_pending_relations_enter_ground_graph_with_canonical_claim_endpoints() -> None:
    claim = PlanningClaim(
        claim_id="pending-facility",
        dimension_key="public_service",
        statement="新增文化设施",
        planning_role="spatial_intervention",
        project_package_ref="pkg-culture",
        suggested_category="facility",
        suggested_output_kind="point",
        asset_kind="facility",
        facility_parameters={"facility_type": "文化设施", "action": "new"},
        spatial_requirements={
            "relations": [
                {
                    "relation_template": "co_locate",
                    "subject_ref": "pkg-culture",
                    "object_ref": "pending-facility",
                    "object_ref_kind": "entity",
                    "parameters": {"max_distance_m": 100},
                }
            ]
        },
    )

    graph = intent_graph_with_pending_claims(PlanningIntentGraph(), [claim])

    assert [node.target_id for node in graph.nodes] == ["pending-facility"]
    assert len(graph.relations) == 1
    relation = graph.relations[0]
    assert relation.source == "pending_grounding_claim"
    assert relation.subject_ref == "pending-facility"
    assert relation.object_ref == "pending-facility"
    assert relation.object_ref_kind == "target"
