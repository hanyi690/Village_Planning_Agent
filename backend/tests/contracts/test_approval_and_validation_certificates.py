import pytest
from types import SimpleNamespace

from app.contracts.artifacts.validation_certificate_contracts import ValidationCertificate
from app.contracts.artifacts.execution_staging_contracts import ExecutionStaging
from app.domain.allocation.approval_input import build_approved_execution_input
from app.contracts.planning.approval import ApprovedExecutionInput
from app.contracts.planning.scenario import (
    BackendCertificatePayload,
    PlanningScenario,
    ScenarioSet,
    ScenarioTargetSelection,
    SolverCertificate,
    derive_backend_selection_digest,
    derive_solver_model_digest,
)
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan
from app.domain.materialization.plan_digest import execution_plan_semantic_digest


def test_approved_execution_input_is_bound_and_provisional_is_not_executable() -> None:
    item = ApprovedExecutionInput(
        approval_id="approval:1",
        scenario_set_ref="scenario-set:1",
        scenario_id="scenario:1",
        scenario_ref="scenario-ref:1",
        scenario_fingerprint="scenario-fp",
        problem_fingerprint="problem-fp",
        target_ids=["b", "a", "a"],
        candidate_ids=["c2", "c1"],
    )

    assert item.target_ids == ["a", "b"]
    assert item.candidate_ids == ["c1", "c2"]
    assert item.can_execute is False
    assert item.fingerprint


def test_executable_approval_requires_execution_plan_digest() -> None:
    with pytest.raises(ValueError, match="execution_plan_digest"):
        ApprovedExecutionInput(
            approval_id="approval:auto-without-plan",
            scenario_set_ref="scenario-set:1",
            scenario_id="scenario:1",
            scenario_ref="scenario-ref:1",
            scenario_fingerprint="scenario-fp",
            problem_fingerprint="problem-fp",
            approval_status="auto",
        )


def test_execution_plan_semantic_digest_changes_with_task_content() -> None:
    plan = ExecutionPlan(plan_id="plan:digest")
    original = execution_plan_semantic_digest(plan)
    changed = plan.model_copy(update={"dependencies": [{"from": "task:a", "to": "task:b"}]})
    assert original != execution_plan_semantic_digest(changed)

    ignored = plan.model_copy(update={"approved_input_fingerprint": "approval:one"})
    assert original == execution_plan_semantic_digest(ignored)

    assert original != execution_plan_semantic_digest(
        plan.model_copy(update={"context_version": "ctx:changed"})
    )
    assert original != execution_plan_semantic_digest(
        plan.model_copy(update={"context_fingerprint": "sha256:changed"})
    )


def test_approval_rejects_execution_plan_context_drift() -> None:
    plan = ExecutionPlan(plan_id="plan:context", context_version="ctx:1")
    approval = ApprovedExecutionInput(
        approval_id="approval:context",
        scenario_set_ref="set:context",
        scenario_id="scenario:context",
        scenario_ref="scenario-ref:context",
        scenario_fingerprint="scenario-fp",
        problem_fingerprint="problem-fp",
        execution_plan_digest=execution_plan_semantic_digest(plan),
        approval_status="auto",
    )
    bound = plan.model_copy(
        update={
            "approved_input_fingerprint": approval.fingerprint,
            "scenario_id": approval.scenario_id,
        }
    )

    with pytest.raises(ValueError, match="digest"):
        approval.assert_execution_plan_matches(
            bound.model_copy(update={"context_version": "ctx:2"})
        )
    with pytest.raises(ValueError, match="digest"):
        approval.assert_execution_plan_matches(
            bound.model_copy(update={"context_fingerprint": "sha256:changed"})
        )


def test_human_approval_requires_actor_and_certificate_binds_atomic_result() -> None:
    with pytest.raises(ValueError, match="approved_by"):
        ApprovedExecutionInput(
            approval_id="approval:2",
            scenario_set_ref="scenario-set:1",
            scenario_id="scenario:1",
            scenario_ref="scenario-ref:1",
            scenario_fingerprint="scenario-fp",
            problem_fingerprint="problem-fp",
            approval_status="human_approved",
        )

    certificate = ValidationCertificate(
        certificate_id="certificate:1",
        execution_result_ref="execution-result:1",
        status="passed",
        check_ids=["b", "a"],
        passed_check_ids=["a"],
        atomic_execution=True,
    )
    assert certificate.check_ids == ["a", "b"]
    assert certificate.can_reconcile is True
    assert certificate.fingerprint


def test_passed_validation_certificate_rejects_wrong_target_coverage() -> None:
    with pytest.raises(ValueError, match="blocking findings"):
        ValidationCertificate(
            certificate_id="certificate:coverage",
            execution_result_ref="execution-result:coverage",
            status="passed",
            atomic_execution=True,
            selected_target_count=1,
            materialized_target_count=1,
            selected_target_ids=["target:approved"],
            materialized_target_ids=["target:other"],
        )


def test_approved_input_rejects_stale_scenario_binding() -> None:
    scenario = PlanningScenario(
        scenario_id="scenario:1",
        baseline_ref="baseline:1",
        problem_fingerprint="problem-fp",
        status="complete",
    )
    proof = BackendCertificatePayload(
        backend_id="test-backend",
        backend_version="1",
        problem_kind="single_choice",
        problem_fingerprint="problem-fp",
        input_digest="input:assert-matches",
        solver_config={
            "deterministic_seed": 0,
            "search_limit": 0,
            "time_limit_seconds": None,
            "max_scenarios": 8,
            "objective_definitions": [],
            "backend_version": "1",
            "replay_settings": {},
        },
        selection_digest=derive_backend_selection_digest({}, []),
        status="feasible",
    )
    scenario_set = ScenarioSet(
        set_id="scenario-set:1",
        problem_fingerprint="problem-fp",
        scenarios=[scenario],
        feasible_scenario_ids=[scenario.scenario_id],
        recommended_scenario_id=scenario.scenario_id,
        solver_certificate=SolverCertificate(
            problem_fingerprint="problem-fp",
            model_digest=derive_solver_model_digest(
                proof,
                deterministic_seed=0,
                search_limit=0,
            ),
            solver_version="test-backend:1",
            status="feasible",
            feasible_scenario_count=1,
            problem_kind="single_choice",
            backend_id="test-backend",
            backend_version="1",
            backend_certificate=proof,
        ),
    )
    item = ApprovedExecutionInput(
        approval_id="approval:3",
        scenario_set_ref="scenario-set-ref",
        scenario_id="scenario:1",
        scenario_ref="scenario-ref:1",
        scenario_fingerprint=scenario.fingerprint,
        problem_fingerprint="problem-fp",
        execution_plan_digest="plan:digest",
        approval_status="auto",
    )
    item.assert_matches(scenario_set, scenario, scenario_set_ref="scenario-set-ref")
    stale = PlanningScenario(**{
        **scenario.model_dump(mode="python", exclude={"fingerprint"}),
        "baseline_ref": "baseline:stale",
    })
    with pytest.raises(ValueError, match="formal ScenarioSet member"):
        item.assert_matches(
            scenario_set,
            stale,
            scenario_set_ref="scenario-set-ref",
        )


def test_execution_staging_requires_commit_id_only_for_committed_status() -> None:
    staged = ExecutionStaging(
        staging_id="staging:1",
        worker_task_ids=["worker-b", "worker-a", "worker-a"],
        failed_task_ids=["worker-b"],
        status="staged",
    )
    assert staged.worker_task_ids == ["worker-a", "worker-b"]
    assert staged.fingerprint

    with pytest.raises(ValueError, match="commit_id"):
        ExecutionStaging(
            staging_id="staging:staged-with-commit",
            status="staged",
            commit_id="commit:invalid",
        )

    with pytest.raises(ValueError, match="commit_id"):
        ExecutionStaging(
            staging_id="staging:aborted-with-commit",
            status="aborted",
            commit_id="commit:invalid",
        )

    with pytest.raises(ValueError, match="commit_id"):
        ExecutionStaging(staging_id="staging:2", status="committed")

    with pytest.raises(ValueError, match="approved_input_ref"):
        ExecutionStaging(
            staging_id="staging:3",
            status="committed",
            commit_id="commit:3",
        )


def test_partial_validation_certificate_cannot_reconcile() -> None:
    certificate = ValidationCertificate(
        certificate_id="certificate:partial",
        execution_result_ref="execution-result:partial",
        status="partial",
        atomic_execution=True,
    )
    assert certificate.can_reconcile is False


def test_committed_execution_result_requires_approval_and_commit() -> None:
    from app.contracts.workflow.execution_plan_contracts import ExecutionResult

    with pytest.raises(ValueError, match="approved_input_ref"):
        ExecutionResult(atomic_commit_status="committed")


def test_deliver_gate_blocks_scenario_without_validation_certificate() -> None:
    from app.contracts.artifacts.delivery_manifest_contracts import DeliveryManifest
    from app.domain.delivery.gate import deliver_gate_route

    manifest = DeliveryManifest(
        delivery_status="partial",
        diagnostic_summary={"validation_certificate_gate": "blocked"},
    )

    assert deliver_gate_route(manifest) == "END_DIAGNOSTIC"


def test_approval_builder_rejects_partial_scenarios_and_freezes_complete_member() -> None:
    partial = SimpleNamespace(
        scenario_id="scenario:partial",
        status="partial",
        problem_fingerprint="problem:1",
        fingerprint="scenario-fp",
        target_selections=[],
    )
    scenario_set = SimpleNamespace(
        set_id="set:1",
        problem_fingerprint="problem:1",
        scenarios=[partial],
        baseline_ref="baseline:1",
    )
    assert build_approved_execution_input(
        scenario_set=scenario_set,
        scenario=partial,
        scenario_set_ref={"descriptor_digest": "set-ref"},
        scenario_ref={"descriptor_digest": "scenario-ref"},
        approval_id="approval:partial",
        approval_status="human_approved",
        approved_by="reviewer:1",
    ) is None

    complete = PlanningScenario(
        scenario_id="scenario:complete",
        status="complete",
        problem_fingerprint="problem:1",
        baseline_ref="baseline:1",
        target_selections=[
            ScenarioTargetSelection(
                target_id="target:b",
                selection_mode="choose_one",
                candidate_ids=["candidate:2"],
            ),
            ScenarioTargetSelection(
                target_id="target:a",
                selection_mode="choose_one",
                candidate_ids=["candidate:1"],
            ),
        ],
    )
    selected = {
        item.target_id: list(item.candidate_ids)
        for item in complete.target_selections
    }
    proof = BackendCertificatePayload(
        backend_id="test-backend",
        backend_version="1",
        problem_kind="bounded_multiobjective",
        problem_fingerprint="problem:1",
        input_digest="input:approval-builder",
        solver_config={
            "deterministic_seed": 0,
            "search_limit": 0,
            "time_limit_seconds": None,
            "max_scenarios": 8,
            "objective_definitions": [],
            "backend_version": "1",
            "replay_settings": {},
        },
        selected_candidate_ids=selected,
        selection_digest=derive_backend_selection_digest(selected, []),
        status="feasible",
    )
    scenario_set = ScenarioSet(
        set_id="set:1",
        problem_fingerprint="problem:1",
        scenarios=[complete],
        feasible_scenario_ids=[complete.scenario_id],
        pareto_scenario_ids=[complete.scenario_id],
        recommended_scenario_id=complete.scenario_id,
        solver_certificate=SolverCertificate(
            problem_fingerprint="problem:1",
            model_digest=derive_solver_model_digest(
                proof,
                deterministic_seed=0,
                search_limit=0,
            ),
            solver_version="test-backend:1",
            status="feasible",
            feasible_scenario_count=1,
            problem_kind="bounded_multiobjective",
            backend_id="test-backend",
            backend_version="1",
            backend_certificate=proof,
        ),
    )
    approval = build_approved_execution_input(
        scenario_set=scenario_set,
        scenario=complete,
        scenario_set_ref={"descriptor_digest": "set-ref"},
        scenario_ref={"descriptor_digest": "scenario-ref"},
        context_ref={"version": "ctx:1"},
        approval_id="approval:complete",
        approval_status="human_approved",
        execution_plan=ExecutionPlan(plan_id="plan:approval-builder"),
        approved_by="reviewer:1",
    )
    assert approval is not None
    assert approval.can_execute is True
    assert approval.execution_plan_digest == execution_plan_semantic_digest(
        ExecutionPlan(plan_id="plan:approval-builder")
    )
    assert approval.target_ids == ["target:a", "target:b"]
    assert approval.candidate_ids == ["candidate:1", "candidate:2"]
    assert approval.scenario_set_ref == "set-ref"
