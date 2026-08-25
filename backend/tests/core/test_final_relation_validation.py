from app.contracts.planning.constraint_factor import ConstraintFactor, RelationMeasurement, RelationSatisfaction
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.planning.scenario import PlanningScenario, ScenarioFeature
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.contracts.spatial.planned_state_contracts import PlannedFacility, PlannedState, PlannedZone
from app.domain.relations.service import RelationEvaluationContext
from app.domain.validation.relation_validation import validate_final_scenario


def _scenario() -> PlanningScenario:
    feature_a = ScenarioFeature(
        feature_id="feature:zone",
        scenario_id="scenario:test",
        target_id="target:zone",
        candidate_id="candidate:zone",
        geometry_kind="polygon",
        geometry_wkt="POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))",
        crs="EPSG:3857",
        generation_operation="select",
        source_refs=["candidate:candidate:zone"],
        relation_ids=["selection:target:zone:candidate:zone"],
    )
    feature_b = ScenarioFeature(
        feature_id="feature:facility",
        scenario_id="scenario:test",
        target_id="target:facility",
        candidate_id="candidate:facility",
        geometry_kind="point",
        geometry_wkt="POINT (5 5)",
        crs="EPSG:3857",
        generation_operation="select",
        source_refs=["candidate:candidate:facility"],
        relation_ids=["selection:target:facility:candidate:facility"],
    )
    factor = ConstraintFactor(
        factor_id="factor:near-zone-facility",
        kind="near",
        evaluator_key="near",
        subject_ref="target:facility",
        object_ref="target:zone",
        hard=True,
        parameters=DistanceParameters(max_distance_m=2, metric="euclidean"),
    )
    return PlanningScenario(
        scenario_id="scenario:test",
        baseline_ref="baseline:test",
        problem_fingerprint="problem:test",
        feature_intents=[feature_a, feature_b],
        relation_satisfactions=[
            RelationSatisfaction(
                relation_id="near-zone-facility",
                scenario_id="scenario:test",
                subject_ref="target:facility",
                object_ref="target:zone",
                status="satisfied",
                criticality="hard",
                measurement=RelationMeasurement(
                    value=0,
                    threshold=2,
                    operator="lte",
                    method="solver_geometry",
                    unit="m",
                ),
                evaluation_trace=["solver:geometry"],
                evaluator_version="relation-evaluator-v1",
            )
        ],
    )


def _problem() -> GroundedPlanningProblem:
    return GroundedPlanningProblem(
        baseline_ref="baseline:test",
        constraint_factors=[
            ConstraintFactor(
                factor_id="factor:near-zone-facility",
                kind="near",
                evaluator_key="near",
                subject_ref="target:facility",
                object_ref="target:zone",
                hard=True,
                parameters=DistanceParameters(max_distance_m=2, metric="euclidean"),
            )
        ],
    )


def test_final_geometry_recheck_catches_worker_drift() -> None:
    state = PlannedState(
        scenario_id="scenario:test",
        zones=[
            PlannedZone(
                zone_id="candidate:zone",
                target_ref="target:zone",
                geometry="POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))",
            )
        ],
        facilities=[
            PlannedFacility(
                feature_id="feature:facility",
                candidate_id="candidate:facility",
                derived_from_target="target:facility",
                geometry="POINT (100 100)",
                source_refs=["worker:facility"],
            )
        ],
    )
    report = validate_final_scenario(
        _scenario(), state, _problem(), RelationEvaluationContext(metric_crs="EPSG:3857")
    )
    row = report.satisfactions[0]
    assert row.status == "violated"
    assert not report.passed
    assert "near-zone-facility" in report.hard_blockers


def test_final_satisfaction_is_backed_by_independent_measurement() -> None:
    scenario = _scenario().model_copy(update={
        "satisfactions": [
            RelationSatisfaction(
                relation_id="near-zone-facility",
                scenario_id="scenario:test",
                subject_ref="target:facility",
                object_ref="target:zone",
                status="satisfied",
                criticality="hard",
            )
        ]
    })
    state = PlannedState(
        scenario_id="scenario:test",
        zones=[PlannedZone(zone_id="candidate:zone", target_ref="target:zone", geometry="POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))")],
        facilities=[PlannedFacility(feature_id="feature:facility", candidate_id="candidate:facility", derived_from_target="target:facility", geometry="POINT (5 5)")],
    )
    report = validate_final_scenario(scenario, state, _problem(), RelationEvaluationContext(metric_crs="EPSG:3857"))
    assert report.passed
    assert report.satisfactions[0].measurement is not None


def test_missing_planned_state_is_explicit_non_evaluable_block() -> None:
    report = validate_final_scenario(_scenario(), None, _problem())
    assert not report.passed
    assert report.status == "failed"
    assert report.hard_blockers == ["missing_planned_state"]
    assert report.satisfactions[0].status == "not_evaluable"
