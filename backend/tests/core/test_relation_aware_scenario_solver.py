from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedCandidateDomain, GroundedPlanningProblem
from app.domain.allocation.scenario_solver import solve_scenario
from app.domain.relations.service import RelationEvaluationContext


def _problem(factors, geometries, domains):
    return GroundedPlanningProblem(
        candidate_domains=domains,
        candidate_geometries=geometries,
        constraint_factors=factors,
    )


def _geometry(candidate_id, target_id, point, score=0.5):
    return CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="point",
        role="execution_geometry",
        wkt=f"POINT ({point} 0)",
        source_ref=f"source:{candidate_id}",
        evidence_refs=[f"evidence:{candidate_id}"],
        suitability_components={"suitability": score},
    )


def test_hard_relation_changes_feasible_set_and_soft_relation_changes_objective():
    geometries = [
        _geometry("a-near", "a", 0.0, 0.1),
        _geometry("a-far", "a", 1.0, 0.9),
        _geometry("b", "b", 0.0001, 0.5),
    ]
    hard_near = ConstraintFactor(
        factor_id="factor:near-hard",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=True,
        parameters=DistanceParameters(max_distance_m=100, metric="euclidean"),
    )
    problem = _problem(
        [hard_near],
        geometries,
        [
            GroundedCandidateDomain(target_id="a", candidate_ids=["a-near", "a-far"]),
            GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
        ],
    )
    result = solve_scenario(
        problem,
        scenario_id="scenario-hard",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-hard"),
    )
    assert result.status == "complete"
    assert result.selected_candidate_ids == {"a": "a-near", "b": "b"}
    assert result.relation_satisfactions[0].status == "satisfied"


def test_no_hard_feasible_combination_fails_closed():
    geometries = [_geometry("a", "a", 0.0), _geometry("b", "b", 1.0)]
    factor = ConstraintFactor(
        factor_id="factor:near-hard",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=True,
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
    )
    result = solve_scenario(
        _problem(
            [factor],
            geometries,
            [
                GroundedCandidateDomain(target_id="a", candidate_ids=["a"]),
                GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
            ],
        ),
        scenario_id="scenario-failed",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-failed"),
    )
    assert result.status == "failed"
    assert result.selected_candidate_ids == {}
    assert result.findings[0].code == "NO_HARD_FEASIBLE_SCENARIO"


def test_soft_relation_is_scored_without_blocking_the_scenario():
    geometries = [
        _geometry("a-near", "a", 0.0, 0.5),
        _geometry("a-far", "a", 1.0, 0.9),
        _geometry("b", "b", 0.0001, 0.5),
    ]
    soft_near = ConstraintFactor(
        factor_id="factor:near-soft",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=False,
        weight=10,
        parameters=DistanceParameters(max_distance_m=100, metric="euclidean"),
    )
    result = solve_scenario(
        _problem(
            [soft_near],
            geometries,
            [
                GroundedCandidateDomain(target_id="a", candidate_ids=["a-near", "a-far"]),
                GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
            ],
        ),
        scenario_id="scenario-soft",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-soft"),
    )
    assert result.status == "complete"
    assert result.selected_candidate_ids["a"] == "a-near"
    assert result.metrics["relation_objective"] == 10
