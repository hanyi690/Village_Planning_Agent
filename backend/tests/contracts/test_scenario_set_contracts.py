import pytest
from pydantic import ValidationError

from app.contracts.planning.scenario import (
    BackendCertificatePayload,
    ObjectiveDefinition,
    PlanningScenario,
    ScenarioSet,
    SolverConflictGroup,
    SolverCertificate,
    derive_backend_selection_digest,
    derive_solver_model_digest,
)


def _scenario(status: str, *, objective_vector: dict[str, float] | None = None) -> PlanningScenario:
    return PlanningScenario(
        scenario_id=f"scenario:{status}",
        baseline_ref="",
        problem_fingerprint="problem:test",
        objective_vector=objective_vector or {},
        status=status,
    )


def _certificate(status: str = "infeasible", count: int = 0) -> SolverCertificate:
    proof = BackendCertificatePayload(
        backend_id="test_backend",
        backend_version="1.0",
        problem_kind="single_choice",
        problem_fingerprint="problem:test",
        input_digest="input:test",
        solver_config={
            "deterministic_seed": 0,
            "search_limit": 0,
            "time_limit_seconds": None,
            "max_scenarios": 8,
            "objective_definitions": [],
            "backend_version": "1.0",
            "replay_settings": {},
        },
        selection_digest=derive_backend_selection_digest({}, []),
        status=status,
        proof_kind="infeasibility_core" if status == "infeasible" else "unknown",
        solver_invoked=status == "infeasible",
        input_closed=status == "infeasible",
        enumeration_complete=status == "infeasible",
        assumption_refs=["model:test"] if status == "infeasible" else [],
        infeasibility_core_refs=["model:test"] if status == "infeasible" else [],
        conflict_groups=(
            [SolverConflictGroup(
                group_id="complete_model",
                assumption_refs=["model:test"],
                explanation="test complete model conflict",
            )]
            if status == "infeasible"
            else []
        ),
    )
    return SolverCertificate(
        problem_fingerprint="problem:test",
        model_digest=derive_solver_model_digest(
            proof,
            deterministic_seed=0,
            search_limit=0,
        ),
        solver_version="test_backend:1.0",
        status=status,
        feasible_scenario_count=count,
        problem_kind="single_choice",
        backend_id="test_backend",
        backend_version="1.0",
        solver_invoked=status == "infeasible",
        input_closed=status == "infeasible",
        enumeration_complete=status == "infeasible",
        proof_kind="infeasibility_core" if status == "infeasible" else "unknown",
        backend_certificate=proof,
    )


def test_partial_scenario_cannot_be_feasible_or_recommended() -> None:
    partial = _scenario("partial")

    with pytest.raises(ValidationError, match="status complete"):
        ScenarioSet(
            set_id="set:test",
            problem_fingerprint="problem:test",
            scenarios=[partial],
            feasible_scenario_ids=[partial.scenario_id],
            solver_certificate=_certificate(),
        )

    with pytest.raises(ValidationError, match="recommended"):
        ScenarioSet(
            set_id="set:test-recommended",
            problem_fingerprint="problem:test",
            scenarios=[partial],
            recommended_scenario_id=partial.scenario_id,
            solver_certificate=_certificate(),
        )


def test_infeasible_certificate_cannot_be_constructed_without_a_closed_proof() -> None:
    with pytest.raises(ValidationError, match="typed backend proof"):
        SolverCertificate(
            problem_fingerprint="problem:test",
            model_digest="model:test",
            solver_version="test",
            status="infeasible",
        )

def test_formal_scenario_requires_every_declared_objective_result() -> None:
    complete = _scenario("complete")
    objective = ObjectiveDefinition(objective_id="benefit")

    with pytest.raises(ValidationError, match="missing declared objective"):
        ScenarioSet(
            set_id="set:objective",
            problem_fingerprint="problem:test",
            scenarios=[complete],
            feasible_scenario_ids=[complete.scenario_id],
            objective_definitions=[objective],
            objective_vectors={complete.scenario_id: {}},
            solver_certificate=_certificate("feasible", 1),
        )


def test_certificate_status_and_count_match_formal_membership() -> None:
    complete = _scenario("complete", objective_vector={"benefit": 1})
    common = dict(
        set_id="set:certificate",
        problem_fingerprint="problem:test",
        scenarios=[complete],
        feasible_scenario_ids=[complete.scenario_id],
        objective_definitions=[ObjectiveDefinition(objective_id="benefit")],
        objective_vectors={complete.scenario_id: {"benefit": 1}},
    )

    with pytest.raises(ValidationError, match="feasible certificate"):
        ScenarioSet(**common, solver_certificate=_certificate("infeasible", 1))

    with pytest.raises(ValidationError, match="feasible_scenario_count"):
        ScenarioSet(**common, solver_certificate=_certificate("feasible", 0))

    with pytest.raises(ValidationError, match="feasible_scenario_count"):
        ScenarioSet(**common, solver_certificate=_certificate("bounded", 0))

    valid = ScenarioSet(
        **common,
        solver_certificate=_certificate("bounded", 1),
    )
    assert valid.solver_certificate.status == "bounded"


def test_certificate_problem_fingerprint_must_match_scenario_set() -> None:
    complete = _scenario("complete", objective_vector={"benefit": 1})

    with pytest.raises(ValidationError, match="problem_fingerprint"):
        ScenarioSet(
            set_id="set:fingerprint",
            problem_fingerprint="problem:test",
            scenarios=[complete],
            feasible_scenario_ids=[complete.scenario_id],
            objective_definitions=[ObjectiveDefinition(objective_id="benefit")],
            objective_vectors={complete.scenario_id: {"benefit": 1}},
            solver_certificate=SolverCertificate(
                problem_fingerprint="problem:other",
                model_digest="model:test",
                solver_version="test",
                status="feasible",
                feasible_scenario_count=1,
            ),
        )
