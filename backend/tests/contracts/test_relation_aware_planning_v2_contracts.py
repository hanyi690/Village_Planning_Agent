from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts.planning.constraint_factor import (
    ConstraintFactor,
    RelationMeasurement,
    RelationSatisfaction,
)
from app.contracts.planning.intent_graph import PlanRelationIntent, PlanningIntentGraph
from app.contracts.planning.relation_parameters import (
    ConnectParameters,
    DistanceParameters,
    ServiceParameters,
)
from app.contracts.planning.scenario import PlanningScenario, ScenarioFeature
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundingBinding,
    GroundedPlanningProblem,
)
from app.contracts.workflow.parse_contracts import SpatialPlanningIntent
from app.contracts.workflow.parse_result_contracts import IntentCompilationResult


def test_relation_parameters_are_typed_and_template_specific() -> None:
    relation = PlanRelationIntent(
        relation_id="near-1",
        relation_template="near",
        subject_ref="facility-1",
        object_ref="settlement-1",
        parameters=DistanceParameters(max_distance_m=500, metric="euclidean"),
    )

    assert relation.parameter_status == "provided"
    assert relation.parameters is not None
    assert relation.parameters.parameter_type == "distance"

    with pytest.raises(ValidationError):
        PlanRelationIntent(
            relation_id="near-invalid",
            relation_template="near",
            subject_ref="facility-1",
            object_ref="settlement-1",
            parameters=ServiceParameters(
                demand_ref="demand-1",
                facility_type="clinic",
                max_travel_time_min=20,
                min_coverage_ratio=0.8,
                capacity=100,
                capacity_unit="person/day",
                network_ref="road-network-1",
            ),
        )


def test_network_parameters_require_a_network_reference() -> None:
    with pytest.raises(ValidationError):
        ConnectParameters(
            network_kind="road",
            endpoint_tolerance_m=10,
            network_ref="",
        )


def test_required_relation_parameter_fields_are_not_optional() -> None:
    with pytest.raises(ValidationError):
        DistanceParameters(metric="euclidean")

    with pytest.raises(ValidationError):
        ServiceParameters(
            facility_type="clinic",
            max_travel_time_min=20,
            min_coverage_ratio=0.8,
            capacity=100,
            capacity_unit="person/day",
            network_ref="road-network-1",
        )

    with pytest.raises(ValidationError):
        ConnectParameters(
            network_kind="road",
            network_ref="network:road:1",
        )


def test_relation_measurement_requires_operator_and_method() -> None:
    with pytest.raises(ValidationError):
        RelationMeasurement(value=100, threshold=200)

    measurement = RelationMeasurement(
        value=100,
        unit="m",
        threshold=200,
        operator="lte",
        method="network_shortest_path",
        network_ref="network:road:1",
    )
    assert measurement.operator == "lte"


def test_candidate_id_is_stable_and_target_source_geometry_changes_it() -> None:
    first = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="execution_geometry",
        wkt="POINT (116 23)",
        source_bsms=["P-2", "P-1"],
        source_refs=["artifact:facility"],
    )
    same = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="execution_geometry",
        wkt="POINT (116 23)",
        source_bsms=["P-1", "P-2"],
        source_refs=["artifact:facility"],
    )
    changed_geometry = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="execution_geometry",
        wkt="POINT (116.01 23)",
        source_bsms=["P-1", "P-2"],
        source_refs=["artifact:facility"],
    )
    changed_target = CandidateGeometry(
        target_id="facility-2",
        kind="point",
        role="execution_geometry",
        wkt="POINT (116 23)",
        source_bsms=["P-1", "P-2"],
        source_refs=["artifact:facility"],
    )
    changed_source = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="execution_geometry",
        wkt="POINT (116 23)",
        source_bsms=["P-1", "P-2"],
        source_refs=["artifact:facility:2"],
    )

    assert first.candidate_id == same.candidate_id
    assert first.candidate_id != changed_geometry.candidate_id
    assert first.candidate_id != changed_target.candidate_id
    assert first.candidate_id != changed_source.candidate_id
    assert first.candidate_id.startswith("candidate:")


def test_grounded_problem_exposes_typed_candidate_domains_and_fingerprint() -> None:
    geometry = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="execution_geometry",
        wkt="POINT (116 23)",
    )
    problem = GroundedPlanningProblem(
        baseline_ref="baseline:1",
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility-1",
                candidate_ids=[geometry.candidate_id],
                candidate_geometry_refs=[geometry.candidate_id],
                status="resolved",
            )
        ],
        candidate_geometries=[geometry],
    )

    assert problem.schema_version == "2.0"
    assert problem.fingerprint
    assert problem.candidate_domains[0].candidate_ids == [geometry.candidate_id]


def test_constraint_factor_derives_stable_id_and_explicit_domain_refs() -> None:
    first = ConstraintFactor(
        kind="connect_network",
        subject_ref="road-1",
        object_ref="facility-1",
        evaluator_key="connect",
        subject_candidate_domain_refs=["candidate:road", "candidate:road"],
        object_candidate_domain_refs=["candidate:facility"],
        parameters=ConnectParameters(
            network_kind="road",
            endpoint_tolerance_m=15,
            network_ref="network:road:1",
        ),
        hard=True,
    )
    second = ConstraintFactor(
        kind="connect_network",
        subject_ref="road-1",
        object_ref="facility-1",
        evaluator_key="connect",
        subject_candidate_domain_refs=["candidate:road"],
        object_candidate_domain_refs=["candidate:facility"],
        parameters=ConnectParameters(
            network_kind="road",
            endpoint_tolerance_m=15,
            network_ref="network:road:1",
        ),
        hard=True,
    )

    assert first.factor_id == second.factor_id
    assert first.subject_candidate_domain_refs == ["candidate:road"]
    assert first.object_candidate_domain_refs == ["candidate:facility"]
    assert first.network_refs == ["network:road:1"]


def test_parse_result_uses_typed_intent_graph() -> None:
    graph = PlanningIntentGraph()
    result = IntentCompilationResult(
        intent_graph=graph,
        typed_intent=SpatialPlanningIntent(),
    )

    assert result.intent_graph is graph
    assert isinstance(result.typed_intent, SpatialPlanningIntent)


@pytest.mark.parametrize(
    "blocking_status",
    ["pending", "not_evaluable", "deferred", "violated"],
)
def test_complete_scenario_rejects_each_non_satisfied_hard_relation_status(
    blocking_status: str,
) -> None:
    relation = RelationSatisfaction(
        relation_id=f"serve-{blocking_status}",
        scenario_id="scenario-1",
        subject_ref="facility-1",
        object_ref="settlement-1",
        criticality="hard",
        status=blocking_status,
    )
    with pytest.raises(ValidationError):
        PlanningScenario(
            scenario_id="scenario-1",
            baseline_ref="baseline:1",
            problem_fingerprint="problem:1",
            relation_satisfactions=[relation],
            status="complete",
        )


def test_scenario_feature_requires_complete_lineage() -> None:
    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="",
            crs="EPSG:4326",
            generation_operation="facility_worker",
        )

    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="POINT (116 23)",
            crs="EPSG:4326",
            generation_operation="facility_worker",
            relation_ids=["serve-1"],
        )

    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="POINT (116 23)",
            crs="EPSG:4326",
            generation_operation="facility_worker",
            source_refs=["candidate:c1"],
        )

    feature = ScenarioFeature(
        feature_id="feature-1",
        scenario_id="scenario-1",
        target_id="facility-1",
        candidate_id="candidate:1",
        geometry_kind="point",
        geometry_wkt="POINT (116 23)",
        crs="EPSG:4326",
        generation_operation="facility_worker",
        source_refs=["candidate:c1"],
        relation_ids=["serve-1"],
    )
    scenario = PlanningScenario(
        scenario_id="scenario-1",
        baseline_ref="baseline:1",
        problem_fingerprint="problem:1",
        feature_intents=[feature],
        status="draft",
    )

    assert scenario.fingerprint


def test_scenario_feature_rejects_blank_source_reference() -> None:
    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="POINT (116 23)",
            crs="EPSG:4326",
            generation_operation="facility_worker",
            source_refs=["  "],
            relation_ids=["serve-1"],
        )


def test_scenario_feature_rejects_omitted_lineage_fields_independently_of_geometry() -> None:
    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="POINT (116 23)",
            crs="EPSG:4326",
            generation_operation="facility_worker",
            relation_ids=["serve-1"],
        )

    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="POINT (116 23)",
            crs="EPSG:4326",
            generation_operation="facility_worker",
            source_refs=["candidate:c1"],
        )


def test_scenario_feature_rejects_empty_relation_ids() -> None:
    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="POINT (116 23)",
            crs="EPSG:4326",
            generation_operation="facility_worker",
            source_refs=["candidate:c1"],
            relation_ids=[],
        )

    with pytest.raises(ValidationError):
        ScenarioFeature(
            feature_id="feature-1",
            scenario_id="scenario-1",
            target_id="facility-1",
            candidate_id="candidate:1",
            geometry_kind="point",
            geometry_wkt="POINT (116 23)",
            crs="EPSG:4326",
            generation_operation="facility_worker",
            source_refs=["candidate:c1"],
            relation_ids=["  "],
        )


def test_root_contract_fingerprints_ignore_collection_order() -> None:
    relation_a = PlanRelationIntent(
        relation_id="relation-a",
        relation_template="near",
        subject_ref="facility-1",
        object_ref="settlement-1",
        parameters=DistanceParameters(max_distance_m=500, metric="euclidean"),
        evidence_refs=["evidence:2", "evidence:1"],
    )
    relation_b = PlanRelationIntent(
        relation_id="relation-b",
        relation_template="precedes",
        subject_ref="road-1",
        object_ref="facility-1",
    )
    graph_a = PlanningIntentGraph(
        nodes=[],
        relations=[relation_b, relation_a],
        diagnostics=["diag-b", "diag-a"],
    )
    graph_b = PlanningIntentGraph(
        nodes=[],
        relations=[relation_a, relation_b],
        diagnostics=["diag-a", "diag-b"],
    )

    geometry = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="execution_geometry",
        wkt="POINT (116 23)",
        source_ref="bundle:facility",
        source_refs=["bundle:facility"],
        evidence_refs=["evidence:2", "evidence:1"],
    )
    problem_a = GroundedPlanningProblem(
        baseline_ref="baseline:1",
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="facility-1",
                candidate_ids=[geometry.candidate_id],
                candidate_geometry_refs=[geometry.candidate_id],
                status="resolved",
            )
        ],
        candidate_geometries=[geometry],
        bindings=[
            GroundingBinding(
                binding_id="binding-1",
                target_id="facility-1",
                entity_ref="entity:facility",
                evidence_refs=["evidence:2", "evidence:1"],
            )
        ],
        network_refs=["network:b", "network:a"],
    )
    problem_b = GroundedPlanningProblem(
        baseline_ref="baseline:1",
        candidate_domains=list(reversed(problem_a.candidate_domains)),
        candidate_geometries=list(reversed(problem_a.candidate_geometries)),
        bindings=list(reversed(problem_a.bindings)),
        network_refs=["network:a", "network:b"],
    )

    scenario_feature = ScenarioFeature(
        feature_id="feature-1",
        scenario_id="scenario-1",
        target_id="facility-1",
        candidate_id=geometry.candidate_id,
        geometry_kind="point",
        geometry_wkt="POINT (116 23)",
        crs="EPSG:4326",
        generation_operation="facility_worker",
        source_refs=["source:2", "source:1"],
        relation_ids=["relation-b", "relation-a"],
    )
    scenario_relation = RelationSatisfaction(
        relation_id="relation-a",
        scenario_id="scenario-1",
        subject_ref="facility-1",
        object_ref="settlement-1",
        status="satisfied",
        evidence_refs=["evidence:2", "evidence:1"],
        factor_ids=["factor:b", "factor:a"],
        subject_feature_refs=["feature:z", "feature:a"],
        evaluation_trace=["trace-2", "trace-1"],
    )
    scenario_a = PlanningScenario(
        scenario_id="scenario-1",
        baseline_ref="baseline:1",
        problem_fingerprint=problem_a.fingerprint,
        feature_intents=[scenario_feature],
        relation_satisfactions=[scenario_relation],
        metrics={"b": 2.0, "a": 1.0},
        status="partial",
    )
    scenario_b = PlanningScenario(
        scenario_id="scenario-1",
        baseline_ref="baseline:1",
        problem_fingerprint=problem_b.fingerprint,
        feature_intents=[scenario_feature.model_copy(update={"source_refs": ["source:1", "source:2"]})],
        relation_satisfactions=[
            scenario_relation.model_copy(
                update={
                    "evidence_refs": ["evidence:1", "evidence:2"],
                    "factor_ids": ["factor:a", "factor:b"],
                    "subject_feature_refs": ["feature:a", "feature:z"],
                    "evaluation_trace": ["trace-1", "trace-2"],
                }
            )
        ],
        metrics={"a": 1.0, "b": 2.0},
        status="partial",
    )

    assert graph_a.fingerprint == graph_b.fingerprint
    assert problem_a.fingerprint == problem_b.fingerprint
    assert scenario_a.fingerprint == scenario_b.fingerprint
