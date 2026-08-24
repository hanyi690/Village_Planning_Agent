from __future__ import annotations

from app.contracts.domain.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
)
from app.contracts.domain.planning_semantics import (
    FacilityPlanningParameters,
    LinearAssetPlanningParameters,
    RoadPlanningParameters,
    SiteAreaPlanningParameters,
)
from app.contracts.program import PlanningClaim
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.contracts.workflow.parse_contracts import SpatialPlanningIntent


def test_projection_preserves_typed_nodes_dependencies_and_relations():
    facility = PlanningIntervention(
        intervention_id="clinic-1",
        name="卫生室",
        planning_role="spatial_intervention",
        project_package_ref="pkg-clinic",
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
        asset_kind="facility",
        evidence_refs=["e:clinic"],
        claim_refs=["claim-clinic"],
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
        planning_role="spatial_intervention",
        project_package_ref="pkg-sewer",
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="line",
        category="road",
        asset_kind="sewer",
        linear_parameters=LinearAssetPlanningParameters(action="upgrade", length_m=100),
        claim_refs=["claim-sewer"],
        evidence_refs=["e:sewer"],
    )
    claims = [
        PlanningClaim(
            claim_id="claim-clinic",
            statement=facility.name,
            suggested_category="facility",
            suggested_output_kind="point",
            asset_kind="facility",
            planning_role="spatial_intervention",
            project_package_ref="pkg-clinic",
            location_hints=["社前村"],
            evidence_refs=["e:clinic"],
            facility_parameters=facility.facility_parameters,
        ),
        PlanningClaim(
            claim_id="claim-sewer",
            statement=sewer.name,
            suggested_category="road",
            suggested_output_kind="line",
            asset_kind="sewer",
            planning_role="spatial_intervention",
            project_package_ref="pkg-sewer",
            location_hints=["社前村"],
            evidence_refs=["e:sewer"],
            linear_parameters=LinearAssetPlanningParameters(action="upgrade", length_m=100),
        ),
    ]
    program = PlanningProgram(
        interventions=[facility, sewer],
        claims=claims,
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
        planning_role="spatial_intervention",
        project_package_ref="pkg-project",
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="polygon",
        category="site_area",
        asset_kind="none",
        materialization_role="site_footprint",
        claim_refs=["claim-project"],
        evidence_refs=["e:project"],
        site_area_parameters=SiteAreaPlanningParameters(site_type="公共空间"),
        spatial_requirements={
            "relations": [
                {"relation_template": "invented_relation", "object_ref": "x"}
            ]
        },
    )

    claim = PlanningClaim(
        claim_id="claim-project",
        statement=intervention.name,
        suggested_category="site_area",
        suggested_output_kind="polygon",
        planning_role="spatial_intervention",
        project_package_ref="pkg-project",
        materialization_role="site_footprint",
        location_hints=["社前村"],
        evidence_refs=["e:project"],
        site_area_parameters={"site_type": "公共空间", "action": "new"},
    )
    result, _, _ = compile_program_deterministic(
        PlanningProgram(interventions=[intervention], claims=[claim])
    )

    assert result.intent_graph.relations == []
    assert any("unsupported_relation_template" in item for item in result.intent_graph.diagnostics)


def test_typed_road_connects_becomes_ground_bindable_network_relation():
    road = PlanningIntervention(
        intervention_id="road-1",
        name="村北道路",
        planning_role="spatial_intervention",
        project_package_ref="pkg-road",
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="line",
        category="road",
        asset_kind="road",
        claim_refs=["claim-road"],
        evidence_refs=["e:road"],
        road_parameters=RoadPlanningParameters(
            action="new",
            length_m=100,
            connects=["entity:existing-road"],
        ),
    )
    claim = PlanningClaim(
        claim_id="claim-road",
        statement=road.name,
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        planning_role="spatial_intervention",
        project_package_ref="pkg-road",
        evidence_refs=["e:road"],
        road_parameters=road.road_parameters,
    )

    result, _, _ = compile_program_deterministic(
        PlanningProgram(interventions=[road], claims=[claim])
    )

    endpoint = next(
        relation
        for relation in result.intent_graph.relations
        if relation.relation_template == "connect_network"
    )
    assert endpoint.source == "typed_road_endpoint"
    assert endpoint.object_ref == "entity:existing-road"
    assert endpoint.object_ref_kind == "place_hint"
    assert endpoint.parameters is None
    assert endpoint.parameter_status == "missing"
    assert result.intent_graph.nodes[0].endpoint_refs == ["entity:existing-road"]
