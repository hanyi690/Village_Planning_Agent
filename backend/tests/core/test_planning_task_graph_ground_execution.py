"""Focused GROUND execution tests for the typed planning task graph."""

from __future__ import annotations

import pytest

from app.contracts.planning.intent_graph import PlanRelationIntent, PlanTargetNode, PlanningIntentGraph
from app.contracts.planning.relation_parameters import (
    AccessParameters,
    AllowedAreaParameters,
    AvoidConstraintParameters,
    ConnectParameters,
    DistanceParameters,
    ExistingAssetParameters,
    FollowAlignmentParameters,
    MutuallyExclusiveParameters,
    PartOfParameters,
    PrecedesParameters,
    ServiceParameters,
)
from app.contracts.planning.task_graph import PlanningTask, PlanningTaskGraph
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
    GroundingBinding,
)
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.domain.ground.task_graph_executor import execute_planning_task_graph
from app.domain.program.target_projection.planning_task_graph_compiler import (
    compile_planning_task_graph,
)
from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository


def _artifact_refs(tmp_path) -> dict[str, dict[str, object]]:
    repository = ContentAddressedArtifactRepository(tmp_path)
    common = {
        "schema_version": "3",
        "producer_stage": "ground",
        "run_id": "task-graph-test",
        "branch_id": "main",
    }
    grounding = repository.put_json({"problem": {}}, schema_id="GroundingResult", **common)
    projection = repository.put_json({"intent_graph": {}}, schema_id="IntentCompilationResult", **common)
    return {
        "grounding_result": grounding.model_dump(mode="json"),
        "target_projection": projection.model_dump(mode="json"),
    }


def test_task_lifecycle_records_deterministic_artifact_lineage() -> None:
    task = PlanningTask(task_id="task:a", task_kind="evidence")
    ready = task.transition_to("ready", reason="dependencies_satisfied")
    running = ready.transition_to("running", reason="ground_inputs_bound")
    resolved = running.transition_to(
        "resolved",
        reason="ground_binding_complete",
        input_artifact_refs=["cas:grounding_result:abc"],
        output_artifact_refs=["ground-task-output:task:a:evidence:a"],
        lineage_refs=["projection-fingerprint"],
    )

    assert resolved.status == "resolved"
    assert [event.to_status for event in resolved.transitions] == ["ready", "running", "resolved"]
    assert resolved.output_artifact_refs == ["ground-task-output:task:a:evidence:a"]
    with pytest.raises(ValueError, match="invalid planning task transition"):
        resolved.transition_to("ready", reason="not_retriable")


def test_compiler_includes_each_supported_relation_template() -> None:
    subject = PlanTargetNode(target_id="road", target_kind="road", endpoint_refs=["a", "b"])
    object_ = PlanTargetNode(target_id="zone", target_kind="zone", evidence_refs=["source:zone"])
    parameters = {
        "within_allowed_area": AllowedAreaParameters(area_refs=["area:1"]),
        "avoid_constraint": AvoidConstraintParameters(constraint_refs=["constraint:1"]),
        "near": DistanceParameters(max_distance_m=100, metric="euclidean"),
        "serve": ServiceParameters(demand_ref="demand:1", facility_type="clinic", max_travel_time_min=15, min_coverage_ratio=0.8, capacity=10, capacity_unit="beds", network_ref="network:road"),
        "provide_access": AccessParameters(max_travel_time_min=15, network_ref="network:road"),
        "connect_network": ConnectParameters(network_kind="road", endpoint_tolerance_m=5, network_ref="network:road"),
        "follow_alignment": FollowAlignmentParameters(alignment_ref="alignment:1", max_deviation_m=5),
        "preserve_existing": ExistingAssetParameters(existing_ref="entity:road"),
        "upgrade_existing": ExistingAssetParameters(existing_ref="entity:road"),
        "part_of": PartOfParameters(parent_ref="zone"),
        "co_locate": DistanceParameters(max_distance_m=20, metric="euclidean"),
        "mutually_exclusive": MutuallyExclusiveParameters(),
        "precedes": PrecedesParameters(required_event="complete"),
        "contains": None,
        "located_in": None,
        "adjacent_to": None,
        "intersects": None,
        "overlaps": None,
    }
    graph = PlanningIntentGraph(
        nodes=[subject, object_],
        relations=[
            PlanRelationIntent(
                relation_id=f"relation:{template}",
                relation_template=template,
                subject_ref="road",
                object_ref="zone",
                parameters=value,
            )
            for template, value in parameters.items()
        ],
    )

    task_graph = compile_planning_task_graph(graph)
    relation_tasks = {task.relation_refs[0]: task for task in task_graph.tasks if task.relation_refs}

    assert set(relation_tasks) == {f"relation:{template}" for template in parameters}
    assert "demand:demand:1" in relation_tasks["relation:serve"].required_inputs
    assert "network:network:road" in relation_tasks["relation:connect_network"].required_inputs
    assert "alignment:alignment:1" in relation_tasks["relation:follow_alignment"].required_inputs
    assert "existing_entity:entity:road" in relation_tasks["relation:upgrade_existing"].required_inputs
    assert "relation_parameters:relation:contains" not in relation_tasks["relation:contains"].required_inputs


def test_ground_executor_resolves_bound_evidence_and_defers_select_solver(tmp_path) -> None:
    graph = PlanningTaskGraph(
        tasks=[
            PlanningTask(
                task_id="evidence",
                task_kind="evidence",
                required_inputs=["source_identity:entity:clinic"],
                produced_artifact_refs=["evidence:source_identity:facility"],
            ),
            PlanningTask(
                task_id="candidate",
                task_kind="candidate_producer",
                required_inputs=["evidence:source_identity:facility"],
                produced_artifact_refs=["candidate_domain:facility"],
                dependency_task_ids=["evidence"],
            ),
            PlanningTask(
                task_id="solver",
                task_kind="solver_subproblem",
                required_inputs=["candidate_domain:facility"],
                dependency_task_ids=["candidate"],
            ),
        ]
    )
    problem = GroundedPlanningProblem(
        bindings=[GroundingBinding(binding_id="binding:clinic", target_id="facility", entity_ref="entity:clinic")],
        target_domains=[GroundedTargetDomain(target_id="facility", evidence_refs=["evidence:clinic"], status="resolved")],
        candidate_domains=[GroundedCandidateDomain(target_id="facility", candidate_ids=["candidate:clinic"], candidate_geometry_refs=["geom:clinic"], status="resolved")],
    )

    executed = execute_planning_task_graph(
        graph,
        grounded_problem=problem,
        artifact_refs=_artifact_refs(tmp_path),
    )
    tasks = {task.task_id: task for task in executed.tasks}

    assert tasks["evidence"].status == "resolved"
    assert tasks["candidate"].status == "resolved"
    assert tasks["solver"].status == "deferred"
    assert tasks["solver"].transitions[-1].reason == "solver_owned_by_select"
    assert tasks["candidate"].output_binding_ids
    candidate_binding = next(item for item in executed.bindings if item.binding_id in tasks["candidate"].output_binding_ids)
    assert candidate_binding.artifact_ref.schema_id == "GroundingResult"
    assert candidate_binding.json_pointer == "/problem/candidate_domains/0"
    assert tasks["candidate"].output_artifact_refs[0].startswith("cas:sha256:")


def test_ground_executor_blocks_missing_source_and_defers_dependents() -> None:
    graph = PlanningTaskGraph(
        tasks=[
            PlanningTask(task_id="evidence", task_kind="evidence", required_inputs=["network:missing"]),
            PlanningTask(task_id="candidate", task_kind="candidate_producer", dependency_task_ids=["evidence"]),
        ]
    )

    executed = execute_planning_task_graph(graph, grounded_problem=GroundedPlanningProblem())
    tasks = {task.task_id: task for task in executed.tasks}

    assert tasks["evidence"].status == "blocked"
    assert "missing_ground_prerequisites:network:missing" == tasks["evidence"].transitions[-1].reason
    assert tasks["candidate"].status == "deferred"
    assert tasks["candidate"].transitions[-1].reason == "dependency_not_resolved:evidence"


def test_candidate_producer_blocks_without_source_backed_candidate_domain(tmp_path) -> None:
    graph = PlanningTaskGraph(tasks=[
        PlanningTask(
            task_id="candidate",
            task_kind="candidate_producer",
            produced_artifact_refs=["candidate_domain:facility"],
        )
    ])

    executed = execute_planning_task_graph(
        graph,
        grounded_problem=GroundedPlanningProblem(),
        artifact_refs=_artifact_refs(tmp_path),
    )

    assert executed.tasks[0].status == "blocked"
    assert executed.tasks[0].transitions[-1].reason == "missing_ground_output_binding"


def test_existing_road_exact_line_uses_source_identity_task_graph(tmp_path) -> None:
    graph = compile_planning_task_graph(PlanningIntentGraph(nodes=[
        PlanTargetNode(
            target_id="road:existing",
            target_kind="road",
            asset_kind="road",
            operation="upgrade",
        ),
    ]))

    assert {
        task.capability
        for task in graph.tasks
    } == {
        "evidence.source_identity",
        "network.candidate",
        "network.solver",
    }
    assert not any(
        task.capability in {"evidence.endpoint_binding", "evidence.network_snapshot"}
        for task in graph.tasks
    )

    geometry = CandidateGeometry(
        candidate_id="candidate:road:existing",
        target_id="road:existing",
        kind="line",
        role="execution_geometry",
        wkt="LINESTRING (113 23, 113.001 23.001)",
        granularity="exact_feature",
        spatial_domain_kind="exact_feature",
        source_feature_ids=["road-feature:existing"],
        identity_confidence=1.0,
        geometry_confidence=1.0,
        hard_constraint_status="passed",
    )
    problem = GroundedPlanningProblem(
        candidate_domains=[GroundedCandidateDomain(
            target_id="road:existing",
            candidate_ids=[geometry.candidate_id],
            candidate_geometry_refs=[geometry.candidate_id],
            status="resolved",
        )],
        candidate_geometries=[geometry],
    )
    executed = execute_planning_task_graph(
        graph,
        grounded_problem=problem,
        artifact_refs=_artifact_refs(tmp_path),
    )
    tasks = {task.task_id: task for task in executed.tasks}
    source_task = next(
        task for task in tasks.values() if task.capability == "evidence.source_identity"
    )
    candidate_task = next(
        task for task in tasks.values() if task.task_kind == "candidate_producer"
    )

    assert source_task.status == "resolved"
    assert candidate_task.status == "resolved"


def test_missing_precedes_event_is_deferred_to_its_owner(tmp_path) -> None:
    graph = PlanningTaskGraph(tasks=[
        PlanningTask(task_id="precedes", task_kind="validation", required_inputs=["event:complete"])
    ])

    executed = execute_planning_task_graph(
        graph,
        grounded_problem=GroundedPlanningProblem(),
        artifact_refs=_artifact_refs(tmp_path),
    )

    assert executed.tasks[0].status == "deferred"
    assert executed.tasks[0].transitions[-1].reason == "select_owned_prerequisites:event:complete"


def test_task_bindings_round_trip_through_cas_with_parent_grounding_ref(tmp_path) -> None:
    graph = PlanningTaskGraph(tasks=[
        PlanningTask(
            task_id="candidate",
            task_kind="candidate_producer",
            produced_artifact_refs=["candidate_domain:facility"],
        )
    ])
    refs = _artifact_refs(tmp_path)
    executed = execute_planning_task_graph(
        graph,
        grounded_problem=GroundedPlanningProblem(candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility",
                candidate_ids=["candidate:facility"],
                candidate_geometry_refs=["geometry:facility"],
                status="resolved",
            )
        ]),
        artifact_refs=refs,
    )
    repository = ContentAddressedArtifactRepository(tmp_path)
    descriptor = repository.put_json(
        executed.model_dump(mode="json"),
        schema_id="PlanningTaskGraph",
        schema_version="3",
        producer_stage="ground",
        run_id="task-graph-test",
        branch_id="main",
        parent_digests={"grounding_result": refs["grounding_result"]["digest"]},
    )
    replayed = PlanningTaskGraph.model_validate(repository.get_json(descriptor))
    binding = replayed.bindings[0]

    assert descriptor.parent_digests == {"grounding_result": refs["grounding_result"]["digest"]}
    assert binding.artifact_ref.digest == refs["grounding_result"]["digest"]
    assert binding.json_pointer == "/problem/candidate_domains/0"
