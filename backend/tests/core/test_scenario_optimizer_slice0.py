from itertools import combinations

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.planning.scenario import ObjectiveDefinition
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.domain.allocation.scenario_optimizer import optimize_scenarios
from app.domain.allocation import scenario_solver
from app.domain.relations.service import RelationEvaluationContext


def _candidate(candidate_id: str, target_id: str, x: float, score: float) -> CandidateGeometry:
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
        identity_confidence=0.9,
        geometry_confidence=0.9,
        hard_constraint_status="passed",
        suitability_components={"suitability": score},
    )


def _subset_problem(*, max_selected: int | None = 2) -> GroundedPlanningProblem:
    geometries = [
        _candidate("a-1", "a", 0, 0.1),
        _candidate("a-2", "a", 10, 0.5),
        _candidate("a-3", "a", 20, 0.9),
    ]
    return GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="a",
                candidate_site_refs=[item.candidate_id for item in geometries],
                geometry_roles=["execution_geometry"],
                status="resolved",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="a",
                candidate_ids=[item.candidate_id for item in geometries],
                candidate_geometry_refs=[item.candidate_id for item in geometries],
                selection_mode="choose_subset",
                min_selected=2,
                max_selected=max_selected,
                status="resolved",
            )
        ],
        candidate_geometries=geometries,
    )


def test_choose_subset_enumerates_exact_cardinality_range() -> None:
    result = optimize_scenarios(
        _subset_problem(),
        set_id="set:subset",
        evaluator_context=RelationEvaluationContext(scenario_id="set:subset"),
    )

    assert result.solver_certificate.status == "feasible"
    selected = {
        tuple(selection.candidate_ids)
        for scenario in result.scenarios
        for selection in scenario.target_selections
    }
    assert selected == {
        tuple(item)
        for item in combinations(("a-1", "a-2", "a-3"), 2)
    }
    assert all(
        len(selection.candidate_ids) == 2
        for scenario in result.scenarios
        for selection in scenario.target_selections
    )


def test_choose_subset_unbounded_domain_fails_closed_with_typed_reason() -> None:
    result = optimize_scenarios(
        _subset_problem(max_selected=None),
        set_id="set:unbounded-subset",
        evaluator_context=RelationEvaluationContext(scenario_id="set:unbounded-subset"),
    )

    assert result.solver_certificate.status == "infeasible"
    assert result.feasible_scenario_ids == []
    assert "invalid candidate selection domain" in result.solver_certificate.termination_reason
    assert any("unbounded choose_subset" in item for item in result.solver_certificate.conflict_explanations)


def test_choose_subset_search_bound_is_visible_and_deterministic() -> None:
    first = optimize_scenarios(
        _subset_problem(),
        set_id="set:subset-bound",
        evaluator_context=RelationEvaluationContext(scenario_id="set:subset-bound"),
        search_limit=2,
    )
    second = optimize_scenarios(
        _subset_problem(),
        set_id="set:subset-bound",
        evaluator_context=RelationEvaluationContext(scenario_id="set:subset-bound"),
        search_limit=2,
    )

    assert first.solver_certificate.status == "bounded"
    assert first.solver_certificate.combinations_inspected == 2
    assert any("search bound reached" in item for item in first.solver_certificate.conflict_explanations)
    assert first.solver_certificate.model_digest == second.solver_certificate.model_digest
    assert [item.scenario_id for item in first.scenarios] == [item.scenario_id for item in second.scenarios]


def test_large_subset_consumes_only_the_global_search_budget(monkeypatch) -> None:
    geometries = [
        _candidate(f"a-{index:03d}", "a", float(index), index / 100)
        for index in range(100)
    ]
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id="a",
                candidate_site_refs=[item.candidate_id for item in geometries],
                geometry_roles=["execution_geometry"],
                status="resolved",
            )
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id="a",
                candidate_ids=[item.candidate_id for item in geometries],
                candidate_geometry_refs=[item.candidate_id for item in geometries],
                selection_mode="choose_subset",
                min_selected=50,
                max_selected=50,
                status="resolved",
            )
        ],
        candidate_geometries=geometries,
    )
    real_combinations = combinations
    consumed = 0

    def guarded_combinations(items, size):
        nonlocal consumed
        for members in real_combinations(items, size):
            consumed += 1
            if consumed > 1:
                raise AssertionError("subset options were consumed beyond search_limit")
            yield members

    monkeypatch.setattr(scenario_solver, "combinations", guarded_combinations)
    result = optimize_scenarios(
        problem,
        set_id="set:large-subset",
        evaluator_context=RelationEvaluationContext(scenario_id="set:large-subset"),
        search_limit=1,
    )

    assert consumed == 1
    assert result.solver_certificate.combinations_inspected == 1
    assert result.solver_certificate.status == "bounded"


def test_unsearched_feasible_row_keeps_certificate_bounded() -> None:
    geometries = [
        _candidate("a-bad", "a", 100, 0.1),
        _candidate("a-good", "a", 0, 0.9),
        _candidate("b", "b", 0, 0.5),
    ]
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id=target_id,
                candidate_site_refs=[
                    item.candidate_id
                    for item in geometries
                    if item.target_id == target_id
                ],
                geometry_roles=["execution_geometry"],
                status="resolved",
            )
            for target_id in ("a", "b")
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id=target_id,
                candidate_ids=[
                    item.candidate_id
                    for item in geometries
                    if item.target_id == target_id
                ],
                candidate_geometry_refs=[
                    item.candidate_id
                    for item in geometries
                    if item.target_id == target_id
                ],
                status="resolved",
            )
            for target_id in ("a", "b")
        ],
        candidate_geometries=geometries,
        constraint_factors=[
            ConstraintFactor(
                factor_id="factor:hard-near-b",
                kind="near",
                evaluator_key="near",
                subject_ref="a",
                object_ref="b",
                hard=True,
                parameters=DistanceParameters(
                    max_distance_m=10,
                    metric="euclidean",
                ),
            )
        ],
    )
    result = optimize_scenarios(
        problem,
        set_id="set:bounded-before-feasible",
        evaluator_context=RelationEvaluationContext(
            scenario_id="set:bounded-before-feasible"
        ),
        search_limit=1,
    )

    assert result.feasible_scenario_ids == []
    assert result.solver_certificate.status == "bounded"
    assert result.solver_certificate.combinations_inspected == 1
    assert "SEARCH_BOUND_REACHED" in result.solver_certificate.termination_reason


def test_pareto_is_computed_before_output_limit() -> None:
    geometries = [
        _candidate("a-near", "a", 0, 0.1),
        _candidate("a-far", "a", 100, 0.9),
        _candidate("a-middle", "a", 50, 0.2),
        _candidate("b", "b", 0, 0.5),
    ]
    problem = GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(
                target_id=target_id,
                candidate_site_refs=[item.candidate_id for item in geometries if item.target_id == target_id],
                geometry_roles=["execution_geometry"],
                status="resolved",
            )
            for target_id in ("a", "b")
        ],
        candidate_domains=[
            GroundedCandidateDomain(
                target_id=target_id,
                candidate_ids=[item.candidate_id for item in geometries if item.target_id == target_id],
                candidate_geometry_refs=[item.candidate_id for item in geometries if item.target_id == target_id],
                status="resolved",
            )
            for target_id in ("a", "b")
        ],
        candidate_geometries=geometries,
        constraint_factors=[
            ConstraintFactor(
                factor_id="factor:near-b",
                kind="near",
                evaluator_key="near",
                subject_ref="a",
                object_ref="b",
                parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
            )
        ],
    )
    result = optimize_scenarios(
        problem,
        set_id="set:pareto-before-limit",
        evaluator_context=RelationEvaluationContext(scenario_id="set:pareto-before-limit"),
        max_scenarios=1,
        objective_definitions=[
            ObjectiveDefinition(
                objective_id="candidate_suitability",
                evaluator_key="candidate_suitability",
            ),
            ObjectiveDefinition(
                objective_id="relation_satisfaction",
                evaluator_key="relation_satisfaction",
            ),
        ],
    )

    assert len(result.pareto_scenario_ids) == 2
    assert set(result.pareto_scenario_ids).issubset(
        {item.scenario_id for item in result.scenarios}
    )
    assert len(result.scenarios) == 2
    assert result.solver_certificate.status == "bounded"
    assert "Pareto frontier exceeds output budget" in result.solver_certificate.termination_reason
    assert any("returned all 2 non-dominated" in item for item in result.solver_certificate.conflict_explanations)
