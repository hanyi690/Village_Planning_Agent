from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.contracts.planning.scenario import ObjectiveDefinition
from app.domain.allocation.scenario_optimizer import optimize_scenarios
from app.domain.relations.service import RelationEvaluationContext


def _geometry(candidate_id: str, target_id: str, x: float, score: float) -> CandidateGeometry:
    return CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="point",
        role="execution_geometry",
        wkt=f"POINT ({x} 0)",
        crs="EPSG:3857",
        source_ref=f"source:{candidate_id}",
        source_refs=[f"source:{candidate_id}"],
        evidence_refs=[f"evidence:{candidate_id}"],
        hard_constraint_status="passed",
        suitability_components={"suitability": score},
    )


def _problem() -> GroundedPlanningProblem:
    geometries = [
        _geometry("a-1", "a", 0, 0.2),
        _geometry("a-2", "a", 10, 0.9),
        _geometry("b-1", "b", 20, 0.5),
    ]
    return GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="a",
                candidate_site_refs=["a-1", "a-2"],
                geometry_roles=["execution_geometry"],
                status="resolved",
            ),
            GroundedTargetDomain(
                target_id="b",
                candidate_site_refs=["b-1"],
                geometry_roles=["execution_geometry"],
                status="resolved",
            ),
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="a",
                candidate_ids=["a-1", "a-2"],
                candidate_geometry_refs=["a-1", "a-2"],
                status="resolved",
            ),
            GroundedCandidateDomain(
                target_id="b",
                candidate_ids=["b-1"],
                candidate_geometry_refs=["b-1"],
                status="resolved",
            ),
        ],
        candidate_geometries=geometries,
    )


def test_optimizer_preserves_alternatives_pareto_and_recommendation() -> None:
    problem = _problem()
    result = optimize_scenarios(
        problem,
        set_id="set-1",
        evaluator_context=RelationEvaluationContext(scenario_id="set-1"),
        max_scenarios=8,
    )

    assert result.solver_certificate.status == "feasible"
    assert len(result.scenarios) == 2
    assert len(result.feasible_scenario_ids) == 2
    assert result.pareto_scenario_ids
    assert result.recommended_scenario_id in result.feasible_scenario_ids
    assert result.recommended is not None
    assert result.problem_fingerprint == problem.fingerprint
    assert all(scenario.objective_vector for scenario in result.scenarios)


def test_optimizer_fails_closed_when_grounding_gate_is_incomplete() -> None:
    problem = GroundedPlanningProblem()
    result = optimize_scenarios(
        problem,
        set_id="set-incomplete",
        evaluator_context=RelationEvaluationContext(scenario_id="set-incomplete"),
    )

    assert result.solver_certificate.status == "infeasible"
    assert result.recommended_scenario_id == ""
    assert result.feasible_scenario_ids == []
    assert result.infeasibility_explanations


def test_optimizer_keeps_degraded_geometry_as_diagnostic_only() -> None:
    base = _problem()
    problem_data = base.model_dump(exclude={"fingerprint", "candidate_completeness"})
    problem_data["candidate_domains"] = [
        GroundedCandidateDomain(
            target_id="a",
            candidate_ids=["a-1", "a-2"],
            candidate_geometry_refs=["a-1", "a-2"],
            geometry_uncertainty_reasons=["grounded_anchor"],
            status="resolved",
        ),
        base.candidate_domains[1],
    ]
    problem = GroundedPlanningProblem(
        **problem_data,
    )

    result = optimize_scenarios(
        problem,
        set_id="set-degraded",
        evaluator_context=RelationEvaluationContext(scenario_id="set-degraded"),
    )

    assert problem.can_solve is False
    assert problem.candidate_completeness.status == "human_required"
    assert result.scenarios
    assert all(item.status == "partial" for item in result.scenarios)
    assert result.feasible_scenario_ids == []
    assert result.pareto_scenario_ids == []
    assert result.recommended_scenario_id == ""
    assert result.recommended is None
    assert result.solver_certificate.status == "infeasible"
    assert any(item.code == "GROUNDING_INCOMPLETE" for item in result.scenarios[0].findings)


def test_objective_directions_drive_pareto_dominance() -> None:
    from app.domain.allocation.scenario_optimizer import _dominates

    definitions = [
        ObjectiveDefinition(objective_id="cost", direction="minimize"),
        ObjectiveDefinition(objective_id="benefit", direction="maximize"),
    ]

    assert _dominates(
        {"cost": 5, "benefit": 10},
        {"cost": 7, "benefit": 9},
        definitions,
    )
    assert not _dominates(
        {"cost": 5, "benefit": 8},
        {"cost": 7, "benefit": 9},
        definitions,
    )
    assert not _dominates({"cost": 5}, {"cost": 7, "benefit": 9}, definitions)


def test_objective_definition_order_is_authoritative_and_missing_results_fail_closed() -> None:
    tradeoff = _problem()
    tradeoff_data = tradeoff.model_dump(
        exclude={"fingerprint", "candidate_geometries", "constraint_factors"}
    )
    tradeoff_data["candidate_geometries"] = [
        _geometry("a-1", "a", 0, 0.9),
        _geometry("a-2", "a", 10, 0.2),
        _geometry("b-1", "b", 20, 0.5),
    ]
    tradeoff_data["constraint_factors"] = [
        ConstraintFactor(
            factor_id="factor:near-tradeoff",
            kind="near",
            evaluator_key="near",
            subject_ref="a",
            object_ref="b",
            hard=False,
            parameters=DistanceParameters(max_distance_m=15, metric="euclidean"),
        )
    ]
    tradeoff = GroundedPlanningProblem(**tradeoff_data)
    definitions = [
        ObjectiveDefinition(
            objective_id="candidate_suitability",
            evaluator_key="candidate_suitability",
        ),
        ObjectiveDefinition(
            objective_id="relation_satisfaction",
            evaluator_key="relation_satisfaction",
        ),
    ]
    reversed_definitions = list(reversed(definitions))
    first = optimize_scenarios(
        tradeoff,
        set_id="set-objective-order",
        evaluator_context=RelationEvaluationContext(scenario_id="set-objective-order"),
        objective_definitions=definitions,
    )
    second = optimize_scenarios(
        tradeoff,
        set_id="set-objective-order",
        evaluator_context=RelationEvaluationContext(scenario_id="set-objective-order"),
        objective_definitions=reversed_definitions,
    )

    assert first.solver_certificate.model_digest != second.solver_certificate.model_digest
    assert [item.objective_id for item in first.objective_definitions] == [
        "candidate_suitability",
        "relation_satisfaction",
    ]
    assert [item.objective_id for item in second.objective_definitions] == [
        "relation_satisfaction",
        "candidate_suitability",
    ]
    assert first.recommended is not None
    assert second.recommended is not None
    assert first.recommended.target_selections[0].candidate_ids == ["a-1"]
    assert second.recommended.target_selections[0].candidate_ids == ["a-2"]

    missing = optimize_scenarios(
        _problem(),
        set_id="set-objective-missing",
        evaluator_context=RelationEvaluationContext(scenario_id="set-objective-missing"),
        objective_definitions=[ObjectiveDefinition(objective_id="cost")],
    )
    assert missing.solver_certificate.status == "infeasible"
    assert missing.feasible_scenario_ids == []
    assert all(item.status == "partial" for item in missing.scenarios)


def test_public_recommendation_honors_minimize_objective_direction() -> None:
    result = optimize_scenarios(
        _problem(),
        set_id="set-minimize-recommendation",
        evaluator_context=RelationEvaluationContext(
            scenario_id="set-minimize-recommendation"
        ),
        objective_definitions=[
            ObjectiveDefinition(
                objective_id="candidate_suitability",
                evaluator_key="candidate_suitability",
                direction="minimize",
            ),
            ObjectiveDefinition(
                objective_id="relation_satisfaction",
                evaluator_key="relation_satisfaction",
                direction="maximize",
            ),
        ],
    )

    assert result.recommended is not None
    assert result.recommended.target_selections[0].candidate_ids == ["a-1"]
    assert result.recommendation_policy == (
        "lexicographic:candidate_suitability:minimize,"
        "relation_satisfaction:maximize"
    )
