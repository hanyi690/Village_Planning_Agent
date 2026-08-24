from types import SimpleNamespace

import pytest

from app.contracts.planning.scenario import (
    BackendCertificatePayload,
    PlanningScenario,
    ScenarioSet,
    SolverCertificate,
    derive_backend_selection_digest,
    derive_solver_model_digest,
)
from app.contracts.planning.approval import ApprovedExecutionInput
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan
from app.domain.materialization.execute_agent import build_execute_agent_graph
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.plan_digest import execution_plan_semantic_digest
from app.workflow.stages import execute as execute_stage


def _formal_scenario_set() -> ScenarioSet:
    scenario = PlanningScenario(
        scenario_id="scenario:approval-boundary:recommended",
        baseline_ref="",
        problem_fingerprint="problem:approval-boundary",
        status="complete",
    )
    proof = BackendCertificatePayload(
        backend_id="test-backend",
        backend_version="1",
        problem_kind="single_choice",
        problem_fingerprint="problem:approval-boundary",
        input_digest="input:approval-boundary",
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
    return ScenarioSet(
        set_id="scenario-set:approval-boundary",
        problem_fingerprint="problem:approval-boundary",
        scenarios=[scenario],
        feasible_scenario_ids=[scenario.scenario_id],
        pareto_scenario_ids=[scenario.scenario_id],
        recommended_scenario_id=scenario.scenario_id,
        solver_certificate=SolverCertificate(
            problem_fingerprint="problem:approval-boundary",
            model_digest=derive_solver_model_digest(proof, deterministic_seed=0, search_limit=0),
            solver_version="scenario-optimizer-test",
            status="feasible",
            feasible_scenario_count=1,
            problem_kind="single_choice",
            backend_id="test-backend",
            backend_version="1",
            backend_certificate=proof,
        ),
    )


@pytest.mark.asyncio
async def test_formal_scenario_without_approved_input_stops_before_workers(monkeypatch):
    loaded = {"scenario_set": _formal_scenario_set()}
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )

    async def context_loaded(state):
        return SimpleNamespace()

    monkeypatch.setattr(execute_stage, "_require_context", context_loaded)
    result = await execute_stage.execute_node(
        {"run_id": "run-approval-boundary", "session_id": "run-approval-boundary"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_APPROVED_INPUT_REQUIRED"


@pytest.mark.asyncio
async def test_no_scenario_set_without_approval_stops_before_compatibility_plan(monkeypatch):
    loaded = {"execution_plan": SimpleNamespace(worker_tasks=[SimpleNamespace(task_id="task:1")])}
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )
    monkeypatch.setattr(
        execute_stage,
        "_get_execute_subgraph",
        lambda: pytest.fail("unapproved compatibility plan must not build graph"),
    )

    result = await execute_stage.execute_node(
        {"run_id": "run-no-scenario", "session_id": "run-no-scenario"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_APPROVED_INPUT_REQUIRED"
    assert result["delivery_status"] == "diagnostic_only"


@pytest.mark.asyncio
async def test_non_recommended_scenario_without_approval_stops_before_workers(monkeypatch):
    scenario_set = _formal_scenario_set().model_copy(
        update={
            "recommended_scenario_id": "",
            "solver_certificate": SolverCertificate(
                problem_fingerprint="problem:approval-boundary",
                model_digest="model:approval-boundary",
                solver_version="scenario-optimizer-test",
                status="unknown",
            ),
        }
    )
    loaded = {"scenario_set": scenario_set}
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )
    monkeypatch.setattr(
        execute_stage,
        "_get_execute_subgraph",
        lambda: pytest.fail("unapproved non-recommended scenario must not build graph"),
    )

    result = await execute_stage.execute_node(
        {"run_id": "run-no-recommendation", "session_id": "run-no-recommendation"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_APPROVED_INPUT_REQUIRED"


@pytest.mark.asyncio
async def test_direct_execute_graph_rejects_plan_without_approval(monkeypatch):
    graph = build_execute_agent_graph(checkpointer=None)
    monkeypatch.setattr(
        "app.domain.materialization.nodes.route_prepare._route_tasks_node",
        lambda state: pytest.fail("route_tasks must not run without approval"),
    )

    with pytest.raises(ValueError, match="ApprovedExecutionInput"):
        await graph.ainvoke(
            ExecuteAgentState(execution_plan=ExecutionPlan()),
            config={"configurable": {"thread_id": "run-direct-unapproved"}},
        )


def test_execute_graph_registers_only_reachable_task_boundary_nodes():
    graph = build_execute_agent_graph(checkpointer=None)

    assert set(graph.get_graph().nodes) == {
        "__start__",
        "__end__",
        "approval_boundary",
        "route_tasks",
        "prepare_inputs",
        "task_scheduler",
        "merge_worker_results",
        "geometry_materialize",
        "planned_state_builder",
        "execution_review",
    }


@pytest.mark.asyncio
async def test_direct_execute_graph_rejects_tampered_plan_with_old_digest():
    from app.domain.materialization.execute_agent import _approval_boundary_node

    plan = ExecutionPlan(plan_id="plan:bound", dependencies=[{"from": "a", "to": "b"}])
    approval = ApprovedExecutionInput(
        approval_id="approval:bound",
        scenario_set_ref="set:bound",
        scenario_id="scenario:bound",
        scenario_ref="scenario-ref:bound",
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
    tampered = bound.model_copy(update={"dependencies": [{"from": "a", "to": "tampered"}]})

    with pytest.raises(ValueError, match="digest"):
        await _approval_boundary_node(
            ExecuteAgentState(
                execution_plan=tampered,
                approved_execution_input=approval,
                approved_input_fingerprint=approval.fingerprint,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [("context_version", "ctx:2"), ("context_fingerprint", "sha256:changed")],
)
async def test_direct_execute_graph_rejects_context_drift_before_workers(
    monkeypatch, field, value
):
    plan = ExecutionPlan(
        plan_id="plan:context-boundary",
        context_version="ctx:1",
        context_fingerprint="sha256:original",
    )
    approval = ApprovedExecutionInput(
        approval_id="approval:context-boundary",
        scenario_set_ref="set:context-boundary",
        scenario_id="scenario:context-boundary",
        scenario_ref="scenario-ref:context-boundary",
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
    tampered = bound.model_copy(update={field: value})
    graph = build_execute_agent_graph(checkpointer=None)
    monkeypatch.setattr(
        "app.domain.materialization.nodes.route_prepare._route_tasks_node",
        lambda state: pytest.fail("context-drifted plan must not reach workers"),
    )

    with pytest.raises(ValueError, match="digest"):
        await graph.ainvoke(
            ExecuteAgentState(
                execution_plan=tampered,
                approved_execution_input=approval,
                approved_input_fingerprint=approval.fingerprint,
            ),
            config={"configurable": {"thread_id": f"run-direct-context-{field}"}},
        )


@pytest.mark.asyncio
async def test_missing_plan_stops_before_context(monkeypatch):
    scenario_set = _formal_scenario_set()
    scenario = scenario_set.scenarios[0]
    loaded = {
        "scenario_set": scenario_set,
        "planning_scenario": scenario,
        "approved_execution_input": ApprovedExecutionInput(
            approval_id="approval:missing-plan",
            scenario_set_ref=scenario_set.set_id,
            scenario_id=scenario.scenario_id,
            scenario_ref="scenario-ref:missing-plan",
            scenario_fingerprint=scenario.fingerprint,
            problem_fingerprint=scenario_set.problem_fingerprint,
            execution_plan_digest="sha256:" + "0" * 64,
            approval_status="auto",
        ),
    }
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    calls = {"context": 0}

    async def context_loaded(state):
        calls["context"] += 1
        raise AssertionError("context must not load for a missing plan")

    monkeypatch.setattr(execute_stage, "_require_context", context_loaded)
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )

    result = await execute_stage.execute_node(
        {"run_id": "run-missing-plan", "session_id": "run-missing-plan"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_EXECUTION_PLAN_MISMATCH"
    assert calls["context"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [("context_version", "ctx:2"), ("context_fingerprint", "sha256:changed")],
)
async def test_context_drift_stops_execute_before_context_or_graph(monkeypatch, field, value):
    scenario_set = _formal_scenario_set()
    scenario = scenario_set.scenarios[0]
    plan = ExecutionPlan(
        plan_id="plan:execute-context-boundary",
        context_version="ctx:1",
        context_fingerprint="sha256:original",
    )
    approval = ApprovedExecutionInput(
        approval_id="approval:execute-context-boundary",
        scenario_set_ref=scenario_set.set_id,
        scenario_id=scenario.scenario_id,
        scenario_ref="scenario-ref:execute-context-boundary",
        scenario_fingerprint=scenario.fingerprint,
        problem_fingerprint=scenario_set.problem_fingerprint,
        execution_plan_digest=execution_plan_semantic_digest(plan),
        approval_status="auto",
    )
    bound = plan.model_copy(
        update={
            "approved_input_fingerprint": approval.fingerprint,
            "scenario_id": approval.scenario_id,
        }
    )
    loaded = {
        "scenario_set": scenario_set,
        "planning_scenario": scenario,
        "approved_execution_input": approval,
        "execution_plan": bound.model_copy(update={field: value}),
    }
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )
    calls = {"context": 0}

    async def context_loaded(state):
        calls["context"] += 1
        raise AssertionError("context must not load for a stale plan")

    monkeypatch.setattr(execute_stage, "_require_context", context_loaded)
    monkeypatch.setattr(
        execute_stage,
        "_get_execute_subgraph",
        lambda: pytest.fail("context-drifted plan must not build graph"),
    )

    result = await execute_stage.execute_node(
        {"run_id": f"run-execute-context-{field}", "session_id": f"run-execute-context-{field}"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_EXECUTION_PLAN_MISMATCH"
    assert calls["context"] == 0


@pytest.mark.asyncio
async def test_blank_plan_binding_stops_before_graph(monkeypatch):
    scenario_set = _formal_scenario_set()
    scenario = scenario_set.scenarios[0]
    plan = ExecutionPlan()
    approval = ApprovedExecutionInput(
        approval_id="approval:blank-plan",
        scenario_set_ref=scenario_set.set_id,
        scenario_id=scenario.scenario_id,
        scenario_ref="scenario-ref:blank-plan",
        scenario_fingerprint=scenario.fingerprint,
        problem_fingerprint=scenario_set.problem_fingerprint,
        execution_plan_digest=execution_plan_semantic_digest(plan),
        approval_status="auto",
    )
    loaded = {
        "scenario_set": scenario_set,
        "planning_scenario": scenario,
        "approved_execution_input": approval,
        "execution_plan": plan,
    }
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )
    monkeypatch.setattr(
        execute_stage,
        "_get_execute_subgraph",
        lambda: pytest.fail("blank plan must not reach graph"),
    )

    result = await execute_stage.execute_node(
        {"run_id": "run-blank-plan", "session_id": "run-blank-plan"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_EXECUTION_PLAN_MISMATCH"


@pytest.mark.asyncio
async def test_provisional_approval_stops_before_context_or_graph(monkeypatch):
    scenario_set = _formal_scenario_set()
    scenario = scenario_set.scenarios[0]
    loaded = {
        "scenario_set": scenario_set,
        "planning_scenario": scenario,
        "approved_execution_input": ApprovedExecutionInput(
            approval_id="approval:provisional",
            scenario_set_ref=scenario_set.set_id,
            scenario_id=scenario.scenario_id,
            scenario_ref="scenario-ref:provisional",
            scenario_fingerprint=scenario.fingerprint,
            problem_fingerprint=scenario_set.problem_fingerprint,
            approval_status="provisional",
        ),
    }
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )
    monkeypatch.setattr(
        execute_stage,
        "_require_context",
        lambda state: pytest.fail("provisional approval must stop before context fallback"),
    )
    monkeypatch.setattr(
        execute_stage,
        "_get_execute_subgraph",
        lambda: pytest.fail("provisional approval must not build graph"),
    )

    result = await execute_stage.execute_node(
        {"run_id": "run-provisional", "session_id": "run-provisional"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_APPROVAL_NOT_EXECUTABLE"
@pytest.mark.asyncio
async def test_formal_scenario_without_approval_does_not_derive_or_repair_plan(monkeypatch):
    loaded = {"scenario_set": _formal_scenario_set()}
    monkeypatch.setattr(
        execute_stage,
        "_load_ref_artifact",
        lambda state, key, cls: loaded.get(key),
    )
    monkeypatch.setattr(
        execute_stage,
        "persist_stage_artifact",
        lambda state, stage, schema_id, payload: {"digest": "diagnostic"},
    )
    monkeypatch.setattr(
        execute_stage,
        "_defer_unclassified_targets",
        lambda *args, **kwargs: pytest.fail("approval gate must precede repair/deferral"),
    )

    async def context_loaded(state):
        return SimpleNamespace()

    monkeypatch.setattr(execute_stage, "_require_context", context_loaded)
    result = await execute_stage.execute_node(
        {"run_id": "run-approval-order", "session_id": "run-approval-order"}
    )

    assert result["fatal_error"]["code"] == "EXECUTE_APPROVED_INPUT_REQUIRED"
