from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedCandidateDomain, GroundedPlanningProblem
from app.domain.allocation.scenario_solver import solve_scenario
from app.domain.relations.service import RelationEvaluationContext


def test_same_problem_and_inputs_have_same_scenario_fingerprint():
    problem = GroundedPlanningProblem(
        baseline_ref="baseline:deterministic",
        candidate_domains=[GroundedCandidateDomain(target_id="facility", candidate_ids=["candidate:facility"])],
        candidate_geometries=[CandidateGeometry(
            candidate_id="candidate:facility",
            target_id="facility",
            kind="point",
            role="execution_geometry",
            wkt="POINT (116 24)",
            source_ref="bundle:facility",
            evidence_refs=["evidence:facility"],
        )],
    )
    context = RelationEvaluationContext(scenario_id="scenario-deterministic")
    first = solve_scenario(problem, scenario_id="scenario-deterministic", evaluator_context=context)
    second = solve_scenario(problem, scenario_id="scenario-deterministic", evaluator_context=context)
    assert first.target_selections == second.target_selections
    assert first.fingerprint == second.fingerprint
