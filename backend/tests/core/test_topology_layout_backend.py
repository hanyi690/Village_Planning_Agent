"""Focused deterministic acceptance for the independent topology backend."""

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import CoLocateParameters
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import (
    GroundedCandidateDomain,
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.domain.allocation.scenario_optimizer import optimize_scenarios
from app.domain.allocation.master_coordinator import build_master_candidates
from app.domain.allocation.solver_portfolio import (
    TopologyLayoutBackend,
    build_solver_problem_view,
    default_solver_registry,
)
from app.domain.allocation.subproblem_compiler import compile_solver_subproblems
from app.domain.allocation.subproblem_optimizer import optimize_solver_subproblems
from app.domain.relations.service import RelationEvaluationContext


def _problem() -> GroundedPlanningProblem:
    geometries = [
        CandidateGeometry(
            candidate_id="a-candidate", target_id="a", kind="point", role="execution_geometry",
            wkt="POINT (0 0)", crs="EPSG:3857", source_ref="source:a",
            evidence_refs=["evidence:a"], identity_confidence=0.9, geometry_confidence=0.9,
            hard_constraint_status="passed", suitability_components={"suitability": 0.8},
        ),
        CandidateGeometry(
            candidate_id="b-candidate", target_id="b", kind="point", role="execution_geometry",
            wkt="POINT (1 0)", crs="EPSG:3857", source_ref="source:b",
            evidence_refs=["evidence:b"], identity_confidence=0.9, geometry_confidence=0.9,
            hard_constraint_status="passed", suitability_components={"suitability": 0.7},
        ),
    ]
    return GroundedPlanningProblem(
        target_domains=[
            GroundedTargetDomain(target_id="a", target_kind="facility", expected_output_kind="point", candidate_site_refs=["a-candidate"], geometry_roles=["execution_geometry"], status="resolved"),
            GroundedTargetDomain(target_id="b", target_kind="facility", expected_output_kind="point", candidate_site_refs=["b-candidate"], geometry_roles=["execution_geometry"], status="resolved"),
        ],
        candidate_domains=[
            GroundedCandidateDomain(target_id="a", candidate_ids=["a-candidate"], candidate_geometry_refs=["a-candidate"], selection_mode="choose_one", status="resolved"),
            GroundedCandidateDomain(target_id="b", candidate_ids=["b-candidate"], candidate_geometry_refs=["b-candidate"], selection_mode="choose_one", status="resolved"),
        ],
        candidate_geometries=geometries,
        constraint_factors=[ConstraintFactor(
            factor_id="factor:adjacent-ab", kind="co_locate", evaluator_key="co_locate",
            subject_ref="a", object_ref="b", hard=True,
            parameters=CoLocateParameters(max_distance_m=2),
            evidence_refs=["evidence:adjacent-ab"], solver_supported=True,
        )],
        solver_kind="topology_layout",
        solver_kind_reasons=["typed_topology_factor"],
    )


def test_topology_has_typed_readiness_backend_and_deterministic_e2e() -> None:
    problem = _problem()
    context = RelationEvaluationContext(scenario_id="topology-e2e")
    view = build_solver_problem_view(problem, evaluator_context=context)
    assert view.problem_kind == "topology_layout"
    assert view.input_complete is True
    resolution = default_solver_registry().resolve(problem, view)
    assert isinstance(resolution.backend, TopologyLayoutBackend)
    assert resolution.support.supported is True

    first = optimize_scenarios(problem, set_id="topology-e2e", evaluator_context=context, search_limit=10)
    second = optimize_scenarios(problem, set_id="topology-e2e", evaluator_context=context, search_limit=10)
    assert first.solver_certificate.backend_id == "topology_layout_bounded"
    assert first.solver_certificate.status == "feasible"
    assert first.recommended_scenario_id
    assert first.fingerprint == second.fingerprint


def test_topology_subproblem_is_not_returned_as_diagnostic_blocker() -> None:
    problem = _problem()
    plan = compile_solver_subproblems(problem)
    topology = [item for item in plan.subproblems if item.problem_kind == "topology_layout"]
    assert len(topology) == 1
    assert topology[0].status == "ready"
    result = optimize_solver_subproblems(
        problem,
        set_id="topology-subproblem-e2e",
        evaluator_context=RelationEvaluationContext(scenario_id="topology-subproblem-e2e"),
        search_limit=10,
    )
    assert result.solver_certificate.backend_id == "topology_layout_bounded"
    assert result.solver_certificate.status == "feasible"
    master_candidates = build_master_candidates(problem, plan)
    assert {item.target_id for item in master_candidates} == {"a", "b"}
    assert {item.candidate_id for item in master_candidates} == {
        "a-candidate",
        "b-candidate",
    }
