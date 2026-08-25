from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedCandidateDomain, GroundedPlanningProblem
from app.domain.allocation.scenario_optimizer import optimize_scenarios
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
    scenario_set = optimize_scenarios(
        problem,
        set_id="scenario-scope",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-scope"),
        max_scenarios=1,
    )
    assert scenario_set.recommended is None
    assert scenario_set.feasible_scenario_ids == []
    assert scenario_set.solver_certificate.status == "unknown"


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
    scenario_set = optimize_scenarios(
        GroundedPlanningProblem(
            candidate_domains=[
                GroundedCandidateDomain(
                    target_id="a",
                    candidate_ids=["a"],
                    candidate_geometry_refs=["a"],
                    status="resolved",
                ),
                GroundedCandidateDomain(
                    target_id="b",
                    candidate_ids=["b"],
                    candidate_geometry_refs=["b"],
                    status="resolved",
                ),
            ],
            candidate_geometries=geometries,
            constraint_factors=[factor],
        ),
        set_id="scenario-avoid",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario-avoid"),
        max_scenarios=1,
    )
    assert scenario_set.recommended is None
    assert scenario_set.feasible_scenario_ids == []
    assert scenario_set.solver_certificate.status == "infeasible"
    proof = scenario_set.solver_certificate.backend_certificate
    assert proof is not None
    assert proof.proof_kind == "infeasibility_core"
    assert proof.infeasibility_core_refs
    assert proof.conflict_groups


def test_hard_unsupported_relation_is_unknown_not_infeasible():
    geometries = [
        CandidateGeometry(
            candidate_id="a",
            target_id="a",
            kind="point",
            role="execution_geometry",
            wkt="POINT (0 0)",
            source_ref="a",
            evidence_refs=["a"],
        ),
        CandidateGeometry(
            candidate_id="b",
            target_id="b",
            kind="point",
            role="execution_geometry",
            wkt="POINT (1 1)",
            source_ref="b",
            evidence_refs=["b"],
        ),
    ]
    factor = ConstraintFactor(
        factor_id="factor:unsupported",
        kind="near",
        evaluator_key="unsupported_relation",
        subject_ref="a",
        object_ref="b",
        hard=True,
    )
    scenario_set = optimize_scenarios(
        GroundedPlanningProblem(
            candidate_domains=[
                GroundedCandidateDomain(
                    target_id="a",
                    candidate_ids=["a"],
                    candidate_geometry_refs=["a"],
                    status="resolved",
                ),
                GroundedCandidateDomain(
                    target_id="b",
                    candidate_ids=["b"],
                    candidate_geometry_refs=["b"],
                    status="resolved",
                ),
            ],
            candidate_geometries=geometries,
            constraint_factors=[factor],
        ),
        set_id="scenario-unsupported-relation",
        evaluator_context=RelationEvaluationContext(
            scenario_id="scenario-unsupported-relation"
        ),
        max_scenarios=1,
    )
    assert scenario_set.recommended is None
    assert scenario_set.feasible_scenario_ids == []
    assert scenario_set.solver_certificate.status == "unknown"
