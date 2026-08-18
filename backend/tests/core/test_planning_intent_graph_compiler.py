from __future__ import annotations

from app.contracts.domain.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
)
from app.contracts.domain.planning_semantics import (
    FacilityPlanningParameters,
    LinearAssetPlanningParameters,
)
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.contracts.domain.selection_contracts import SiteSelectionDecision, TargetAssignment
from app.contracts.workflow.parse_contracts import FacilityTarget, RoadTarget, SpatialPlanningIntent
from app.domain.materialization.plan_builder import build_execution_plan
from types import SimpleNamespace


def test_projection_preserves_typed_nodes_dependencies_and_relations():
    facility = PlanningIntervention(
        intervention_id="clinic-1",
        name="卫生室",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
        asset_kind="facility",
        evidence_refs=["e:clinic"],
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
        spatial_requirements={
            "relations": [
                {
                    "relation_template": "serve",
                    "object_ref": "settlement:社前村",
                    "object_ref_kind": "entity",
                    "criticality": "hard",
                    "evidence_refs": ["e:settlement"],
                }
            ]
        },
    )
    sewer = PlanningIntervention(
        intervention_id="sewer-1",
        name="污水管网",
        execution_mode="spatial",
        expected_output_kind="line",
        category="road",
        asset_kind="sewer",
        linear_parameters=LinearAssetPlanningParameters(action="upgrade"),
    )
    program = PlanningProgram(
        interventions=[facility, sewer],
        dependencies=[
            InterventionDependency(
                from_intervention_id="sewer-1",
                to_intervention_id="clinic-1",
                dependency_type="utility_before_facility",
            )
        ],
    )

    result, _, _ = compile_program_deterministic(program, program_ref="program-1")
    graph = result.intent_graph

    assert graph is not None
    assert {node.target_id for node in graph.nodes} == {"clinic-1", "sewer-1"}
    assert {node.target_kind for node in graph.nodes} == {"facility", "linear"}
    assert any(item.relation_template == "serve" for item in graph.relations)
    assert any(
        item.relation_template == "precedes"
        and item.subject_ref == "sewer-1"
        and item.object_ref == "clinic-1"
        for item in graph.relations
    )
    assert graph.fingerprint


def test_unstructured_relation_is_not_freely_classified():
    intervention = PlanningIntervention(
        intervention_id="project-1",
        name="公共空间",
        execution_mode="spatial",
        expected_output_kind="polygon",
        category="site_area",
        asset_kind="none",
        spatial_requirements={
            "relations": [
                {"relation_template": "invented_relation", "object_ref": "x"}
            ]
        },
    )

    result, _, _ = compile_program_deterministic(
        PlanningProgram(interventions=[intervention])
    )

    assert result.intent_graph.relations == []
    assert any("unsupported_relation_template" in item for item in result.intent_graph.diagnostics)


def test_execution_plan_uses_explicit_precedes_relation_not_list_order():
    intent = SpatialPlanningIntent(
        facilities=[FacilityTarget(target_id="facility-1", type="卫生站")],
        road_targets=[RoadTarget(target_id="road-1", connects=["facility-1"])],
    )
    from app.contracts.planning.intent_graph import PlanRelationIntent, PlanningIntentGraph

    graph = PlanningIntentGraph(
        nodes=[],
        relations=[
            PlanRelationIntent(
                relation_id="pre-1",
                relation_template="precedes",
                subject_ref="facility-1",
                object_ref="road-1",
                criticality="hard",
            )
        ],
    )
    decision = SiteSelectionDecision(
        target_assignments=[
            TargetAssignment(
                target_id="facility-1",
                target_type="facility",
                status="ready",
                expected_output_kind="point",
                anchor_point=(116.0, 23.0),
            ),
            TargetAssignment(
                target_id="road-1",
                target_type="road",
                status="ready",
                expected_output_kind="line",
            ),
        ]
    )
    plan = build_execution_plan(
        SimpleNamespace(typed_intent=intent, intent_graph=graph),
        decision,
        [],
        run_id="run-1",
    )
    road = next(task for task in plan.worker_tasks if task.target_id == "road-1")
    facility = next(task for task in plan.worker_tasks if task.target_id == "facility-1")
    assert road.depends_on == [facility.task_id]
