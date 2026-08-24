from app.contracts.planning.relation_parameters import ConnectParameters
from app.contracts.planning.intent_graph import PlanRelationIntent, PlanningIntentGraph
from app.contracts.planning.scenario import ScenarioFeature
from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
from app.contracts.domain.planning_semantics import RoadPlanningParameters
from app.contracts.program import PlanningClaim
from app.contracts.spatial.grounding_contracts import CandidateSite
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.domain.ground.constraint_factors import compile_constraint_factors
from app.domain.ground.aggregate import _build_grounded_problem
from app.domain.relations.service import RelationEvaluationContext
from app.domain.relations.network_evaluators import evaluate_connectivity
from app.domain.allocation.scenario_optimizer import optimize_scenarios
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.spatial.network.network_graph import build_network_graph


def _point(feature_id: str, point: str) -> ScenarioFeature:
    return ScenarioFeature(
        feature_id=feature_id,
        scenario_id="scenario-1",
        target_id=feature_id,
        candidate_id=f"candidate:{feature_id}",
        geometry_kind="point",
        geometry_wkt=point,
        crs="EPSG:4326",
        generation_operation="test",
        source_refs=[f"candidate:{feature_id}"],
        relation_ids=[f"selection:{feature_id}:{feature_id}"],
    )


def test_straight_line_close_but_disconnected_is_not_connected() -> None:
    network = build_network_graph(
        [
            {"geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]}},
            {"geometry": {"type": "LineString", "coordinates": [[0.0101, 0], [0.02, 0]]}},
        ],
        impedance="travel_time_min",
        network_ref="network:road:test",
        snap_tolerance_m=1,
    )
    result = evaluate_connectivity(
        _point("a", "POINT (0 0)"),
        _point("b", "POINT (0.02 0)"),
        network,
        ConnectParameters(
            network_kind="road",
            endpoint_tolerance_m=100,
            network_ref="network:road:test",
        ),
    )

    assert result.status == "not_reachable"
    assert result.connected is False


def test_typed_road_endpoint_binds_only_with_authoritative_network_ref() -> None:
    relation = PlanRelationIntent(
        relation_id="relation:road-1:connect:0",
        relation_template="connect_network",
        subject_ref="road-1",
        object_ref="entity:existing-road",
        object_ref_kind="place_hint",
        criticality="hard",
        source="typed_road_endpoint",
        geometry_scope="network",
    )
    graph = PlanningIntentGraph(relations=[relation])

    missing = compile_constraint_factors(graph)
    bound = compile_constraint_factors(
        graph,
        default_network_ref="network:road:current",
        default_endpoint_tolerance_m=7.5,
    )

    assert missing[0].parameters is None
    assert missing[0].status == "deferred"
    assert bound[0].parameters is not None
    assert bound[0].parameters.network_ref == "network:road:current"
    assert bound[0].parameters.endpoint_tolerance_m == 7.5
    assert bound[0].status == "unknown"


def test_typed_road_claim_reaches_network_backend_without_choice_fallback() -> None:
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
        location_hints=["村北"],
        evidence_refs=["e:road"],
        road_parameters=road.road_parameters,
    )
    result, _, _ = compile_program_deterministic(
        PlanningProgram(interventions=[road], claims=[claim])
    )
    graph = result.intent_graph
    relation = next(
        item
        for item in graph.relations
        if item.relation_template == "connect_network"
    )
    factors = compile_constraint_factors(
        graph,
        default_network_ref="network:road:test",
        default_endpoint_tolerance_m=1000.0,
    )
    factor = next(item for item in factors if item.kind == "connect_network")
    assert relation.source == "typed_road_endpoint"
    assert factor.parameters is not None
    assert factor.parameters.network_ref == "network:road:test"

    candidate = CandidateGeometry(
        target_id="road-1",
        kind="line",
        role="execution_geometry",
        materialization_role="road_corridor",
        wkt="LINESTRING (0 0, 0.01 0)",
        crs="EPSG:4326",
        granularity="corridor",
        spatial_domain_kind="corridor",
        hard_constraint_status="passed",
        availability_status="fully_available",
        source_refs=["candidate:road-1"],
    )
    problem = _build_grounded_problem(
        [
            CandidateSite(
                site_id="site-road-1",
                target_ref="road-1",
                target_kind="linear",
                expected_output_kind="line",
                geometry=candidate,
            )
        ],
        [],
        factors,
        [],
        graph,
    )
    assert problem.solver_kind == "network_path"
    assert problem.network_refs == ["network:road:test"]

    network = build_network_graph(
        [
            {"geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]}},
            {"geometry": {"type": "LineString", "coordinates": [[0.01, 0], [0.02, 0]]}},
        ],
        impedance="travel_time_min",
        network_ref="network:road:test",
        snap_tolerance_m=1000,
    )
    existing = _point("existing-road", "LINESTRING (0.01 0, 0.02 0)").model_copy(
        update={
            "feature_id": "feature:existing-road",
            "scenario_id": "scenario-set:typed-road",
            "target_id": "entity:existing-road",
            "candidate_id": "reference:existing-road",
            "entity_refs": ["entity:existing-road"],
            "geometry_kind": "line",
            "geometry_wkt": "LINESTRING (0.01 0, 0.02 0)",
        }
    )
    scenario_set = optimize_scenarios(
        problem,
        set_id="scenario-set:typed-road",
        evaluator_context=RelationEvaluationContext(
            scenario_id="scenario-set:typed-road",
            networks={"network:road:test": network},
            reference_features={"entity:existing-road": existing},
        ),
    )
    certificate = scenario_set.solver_certificate.backend_certificate
    assert certificate is not None
    assert certificate.backend_id == "network_relation_bounded"
    assert scenario_set.recommended is not None, [
        (
            item.status,
            [
                (row.status, row.detail)
                for row in item.relation_satisfactions
            ],
            [finding.code for finding in item.findings],
        )
        for item in scenario_set.scenarios
    ]
    assert any(
        item.status == "satisfied"
        for item in scenario_set.recommended.relation_satisfactions
    )
