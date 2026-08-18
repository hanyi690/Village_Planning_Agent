from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedCandidateDomain, GroundedPlanningProblem
from app.domain.allocation.scenario_solver import solve_scenario
from app.domain.relations.service import RelationEvaluationContext


def test_candidate_only_geometry_is_never_materialized_as_execution_feature():
    candidate = CandidateGeometry(
        candidate_id="scope",
        target_id="zone",
        kind="polygon",
        role="scope_geometry",
        wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
        source_ref="scope:1",
        evidence_refs=["evidence:scope"],
    )
    problem = GroundedPlanningProblem(
        candidate_domains=[GroundedCandidateDomain(target_id="zone", candidate_ids=["scope"], status="candidate_only")],
        candidate_geometries=[candidate],
    )
    result = solve_scenario(
        problem,
        scenario_id="scenario-scope",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-scope"),
    )
    assert result.status == "failed"
    assert result.feature_intents == []
    assert result.findings[0].code == "NO_PLANNING_OUTPUT"


def test_hard_avoid_is_not_reinterpreted_as_soft_score():
    geometries = [
        CandidateGeometry(candidate_id="a", target_id="a", kind="point", role="execution_geometry", wkt="POINT (0 0)", source_ref="a", evidence_refs=["a"]),
        CandidateGeometry(candidate_id="b", target_id="b", kind="point", role="execution_geometry", wkt="POINT (0 0)", source_ref="b", evidence_refs=["b"]),
    ]
    factor = ConstraintFactor(
        factor_id="factor:avoid",
        kind="avoid_constraint",
        evaluator_key="avoid",
        subject_ref="a",
        object_ref="b",
        hard=True,
    )
    result = solve_scenario(
        GroundedPlanningProblem(
            candidate_domains=[
                GroundedCandidateDomain(target_id="a", candidate_ids=["a"]),
                GroundedCandidateDomain(target_id="b", candidate_ids=["b"]),
            ],
            candidate_geometries=geometries,
            constraint_factors=[factor],
        ),
        scenario_id="scenario-avoid",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-avoid"),
    )
    assert result.status == "failed"
