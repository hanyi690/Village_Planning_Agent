from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedCandidateDomain, GroundedPlanningProblem
from app.contracts.planning.scenario import PlanningScenario, ScenarioTargetSelection
from app.domain.allocation.network_subproblem import derive_network_cuts


def test_network_failure_produces_stable_replacement_cut():
    factor = ConstraintFactor(
        factor_id="factor:connect-1",
        kind="connect_network",
        evaluator_key="connect",
        subject_ref="road-a",
        object_ref="facility-b",
        hard=True,
    )
    problem = GroundedPlanningProblem(
        constraint_factors=[factor],
        candidate_domains=[
            GroundedCandidateDomain(target_id="road-a", candidate_ids=["road-candidate"]),
            GroundedCandidateDomain(target_id="facility-b", candidate_ids=["facility-candidate"]),
        ],
        candidate_geometries=[
            CandidateGeometry(candidate_id="road-candidate", target_id="road-a", source_ref="road", evidence_refs=["road"], wkt="POINT (0 0)", kind="point", role="execution_geometry"),
            CandidateGeometry(candidate_id="facility-candidate", target_id="facility-b", source_ref="facility", evidence_refs=["facility"], wkt="POINT (1 1)", kind="point", role="execution_geometry"),
        ],
    )
    scenario = PlanningScenario(
        scenario_id="scenario-cut",
        baseline_ref="baseline:1",
        problem_fingerprint=problem.fingerprint,
        target_selections=[
            ScenarioTargetSelection(
                target_id="road-a",
                selection_mode="choose_one",
                candidate_ids=["road-candidate"],
            ),
            ScenarioTargetSelection(
                target_id="facility-b",
                selection_mode="choose_one",
                candidate_ids=["facility-candidate"],
            ),
        ],
        relation_satisfactions=[RelationSatisfaction(
            relation_id="connect-1",
            scenario_id="scenario-cut",
            subject_ref="road-a",
            object_ref="facility-b",
            status="not_evaluable",
            criticality="hard",
            detail="network_unavailable:network:road",
        )],
    )
    cuts = derive_network_cuts(scenario, problem)
    assert len(cuts) == 1
    assert cuts[0].candidate_ids == ["facility-candidate", "road-candidate"]
    assert cuts[0].cut_id == derive_network_cuts(scenario, problem)[0].cut_id
