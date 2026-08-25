import hashlib
from types import SimpleNamespace

import pytest

from app.contracts.workflow.workflow_contracts import GateDecision, PendingRequest
from app.contracts.workflow.human_interrupt_contracts import (
    HumanInterruptChannel,
    build_human_interrupt,
    stable_human_interrupt_id,
)
from app.domain.allocation.select_gate import evaluate_scenario_select_gate
from app.domain.common.gate_progress import canonical_input_checksum


def _artifact_ref(name: str) -> dict[str, object]:
    digest = "sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest()
    descriptor = "sha256:" + hashlib.sha256(f"descriptor:{name}".encode("utf-8")).hexdigest()
    semantic = "sha256:" + hashlib.sha256(f"semantic:{name}".encode("utf-8")).hexdigest()
    return {
        "digest": digest,
        "descriptor_digest": descriptor,
        "media_type": "application/json",
        "size_bytes": 1,
        "schema_id": name,
        "schema_version": "1.0",
        "semantic_digest": semantic,
        "parent_digests": {},
        "producer_stage": "select",
        "run_id": "run:test",
        "branch_id": "main",
        "provenance": {},
    }


def _select_review_state(
    *,
    session_id: str,
    request: PendingRequest,
    artifact_refs: dict[str, object],
) -> dict[str, object]:
    items = [request.model_dump(mode="json")]
    event_id = stable_human_interrupt_id(
        session_id,
        HumanInterruptChannel.POST_L3_REVIEW,
        paused_stage="select",
        items=items,
        generation=0,
    )
    return {
        "session_id": session_id,
        "context_version": "ctx:1",
        "paused_stage": "select",
        "human_review_event_id": event_id,
        "human_review_generation": 0,
        "human_review_items": items,
        "human_interrupt": build_human_interrupt(
            event_id=event_id,
            channel=HumanInterruptChannel.POST_L3_REVIEW,
            items=items,
            paused_stage="select",
        ),
        "artifact_refs": artifact_refs,
    }


def test_select_gate_blocks_missing_scenario_authority() -> None:
    gate = evaluate_scenario_select_gate(None, None, None)

    assert gate.passed is False
    assert gate.feedback_route == "HUMAN"


def test_select_gate_keeps_incomplete_scenario_human_pending() -> None:
    scenario = SimpleNamespace(scenario_id="scenario-1", status="partial")
    scenario_set = SimpleNamespace(
        recommended_scenario_id="scenario-1",
        feasible_scenario_ids=["scenario-1"],
        solver_certificate=SimpleNamespace(status="feasible"),
    )
    gate = evaluate_scenario_select_gate(
        scenario_set,
        scenario,
        SimpleNamespace(can_solve=True),
    )

    assert gate.passed is False
    assert gate.feedback_route == "HUMAN"


def test_select_gate_passes_only_executable_approved_complete_member() -> None:
    scenario = SimpleNamespace(scenario_id="scenario-1", status="complete")
    scenario_set = SimpleNamespace(
        recommended_scenario_id="scenario-1",
        feasible_scenario_ids=["scenario-1"],
        solver_certificate=SimpleNamespace(status="feasible"),
    )
    gate = evaluate_scenario_select_gate(
        scenario_set,
        scenario,
        SimpleNamespace(can_solve=True),
        approved_input=SimpleNamespace(can_execute=True),
    )

    assert gate.passed is True
    assert gate.feedback_route is None


def test_select_gate_exposes_typed_solver_blockers_for_deferral() -> None:
    problem = SimpleNamespace(
        candidate_completeness=SimpleNamespace(),
        unresolved=[],
        deferred=[],
        target_domains=[SimpleNamespace(target_id="hard-target", status="resolved")],
        candidate_domains=[SimpleNamespace(target_id="coverage-target", status="resolved")],
        constraint_factors=[SimpleNamespace(
            hard=True,
            status="deferred",
            subject_ref="hard-target",
            object_ref="",
            object_ref_kind="entity",
        )],
    )
    solver_plan = SimpleNamespace(subproblems=[SimpleNamespace(
        status="blocked",
        target_refs=("coverage-target",),
    )])
    gate = evaluate_scenario_select_gate(
        SimpleNamespace(
            recommended_scenario_id="",
            feasible_scenario_ids=[],
            solver_certificate=SimpleNamespace(status="infeasible"),
        ),
        None,
        problem,
        solver_subproblem_plan=solver_plan,
    )

    target_ids = gate.pending_requests[0].context["target_ids"]
    assert target_ids == ["coverage-target", "hard-target"]


def test_select_gate_blocks_a_source_blocked_task_target() -> None:
    task_graph = SimpleNamespace(tasks=[SimpleNamespace(
        status="blocked",
        target_refs=["task-blocked-target"],
    )])
    gate = evaluate_scenario_select_gate(
        None,
        None,
        SimpleNamespace(can_solve=False, candidate_completeness=SimpleNamespace(), unresolved=[], deferred=[], target_domains=[], candidate_domains=[], constraint_factors=[]),
        planning_task_graph=task_graph,
    )

    assert "planning_task_prerequisites_incomplete" in gate.pending_requests[0].context["reasons"]
    assert gate.pending_requests[0].context["target_ids"] == ["task-blocked-target"]


@pytest.mark.asyncio
async def test_real_gate_partial_approval_defers_only_typed_problem_targets(monkeypatch):
    from app.workflow import root_graph

    problem = SimpleNamespace(
        candidate_completeness=SimpleNamespace(
            unresolved_target_ids=("target-unresolved",),
        ),
        unresolved=[],
        deferred=[],
        target_domains=[],
        fingerprint="problem-1",
    )
    scenario = SimpleNamespace(findings=[], problem_fingerprint="problem-1")
    scenario_set = SimpleNamespace(problem_fingerprint="problem-1")
    refs = {
        "scenario_set": _artifact_ref("ScenarioSet"),
        "planning_scenario": _artifact_ref("PlanningScenario"),
        "scoped_grounding_problem": _artifact_ref("GroundedPlanningProblem"),
    }
    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        context_version="ctx:1",
        input_artifact_refs=refs,
        input_checksum=canonical_input_checksum(refs),
        issue_fingerprint="scenario_not_complete",
        pending_requests=[PendingRequest(
            request_id="select-pending",
            stage="select",
            request_type="scenario_approval_required",
            context={
                "reasons": ["scenario_not_complete"],
                "target_ids": ["target-unresolved"],
            },
        )],
    )
    persisted = {}

    def fake_load(state, key, cls=None):
        if key == "scoped_grounding_problem":
            return problem
        if key == "planning_scenario":
            return scenario
        if key == "scenario_set":
            return scenario_set
        return None

    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: gate)
    monkeypatch.setattr("app.infrastructure.artifacts.runtime.load_artifact", fake_load)
    def fake_persist(state, stage, schema_id, payload):
        persisted[schema_id] = payload
        return {"ref": schema_id}

    monkeypatch.setattr(root_graph, "persist_stage_artifact", fake_persist)

    result = await root_graph._apply_select_auto_deferral(
        _select_review_state(
            session_id="s1",
            request=gate.pending_requests[0],
            artifact_refs=refs,
        )
    )

    assert result["human_deferred_targets"] == ["target-unresolved"]
    assert result["scoped_replan_required"] is True
    assert result["artifact_refs"]["execution_plan"] is None
    assert result["artifact_refs"]["approved_execution_input"] is None
    assert persisted["DeferralLedger"].entries[0].target_id == "target-unresolved"


@pytest.mark.asyncio
async def test_select_deferral_rejects_artifact_id_only_refs(monkeypatch):
    from app.workflow import root_graph

    refs = {
        "scenario_set": {"artifact_id": "scenario-set-only"},
        "planning_scenario": {"artifact_id": "scenario-only"},
        "scoped_grounding_problem": {"artifact_id": "problem-only"},
    }
    request = PendingRequest(
        request_id="select-pending",
        stage="select",
        request_type="scenario_approval_required",
        context={"target_ids": ["target-unresolved"]},
    )
    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        context_version="ctx:1",
        input_artifact_refs=refs,
        input_checksum=canonical_input_checksum(refs),
        issue_fingerprint="scenario_not_complete",
        pending_requests=[request],
    )
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: gate)
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda state, key, cls=None: None,
    )
    persisted = []
    monkeypatch.setattr(
        root_graph,
        "persist_stage_artifact",
        lambda *args, **kwargs: persisted.append(args) or {"ref": "unexpected"},
    )

    result = await root_graph._apply_select_auto_deferral(
        _select_review_state(
            session_id="s1",
            request=request,
            artifact_refs=refs,
        )
    )

    assert result["human_approval_diagnostic"]["code"] == "SELECT_DEFERRAL_SCOPE_STALE"
    assert (
        "input_artifact_ref_missing:scenario_set"
        in result["human_approval_diagnostic"]["reasons"]
    )
    assert persisted == []


@pytest.mark.asyncio
async def test_select_deferral_rejects_request_payload_drift(monkeypatch):
    from app.workflow import root_graph

    problem = SimpleNamespace(
        candidate_completeness=SimpleNamespace(
            unresolved_target_ids=("target-unresolved",),
        ),
        unresolved=[],
        deferred=[],
        target_domains=[],
        fingerprint="problem-1",
    )
    scenario = SimpleNamespace(findings=[], problem_fingerprint="problem-1")
    scenario_set = SimpleNamespace(problem_fingerprint="problem-1")
    refs = {
        "scenario_set": _artifact_ref("ScenarioSet-drift"),
        "planning_scenario": _artifact_ref("PlanningScenario-drift"),
        "scoped_grounding_problem": _artifact_ref("GroundedPlanningProblem-drift"),
    }
    request = PendingRequest(
        request_id="select-pending",
        stage="select",
        request_type="scenario_approval_required",
        context={"target_ids": ["target-unresolved"]},
    )
    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        context_version="ctx:1",
        input_artifact_refs=refs,
        input_checksum=canonical_input_checksum(refs),
        issue_fingerprint="scenario_not_complete",
        pending_requests=[request],
    )
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: gate)
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda state, key, cls=None: {
            "scoped_grounding_problem": problem,
            "planning_scenario": scenario,
            "scenario_set": scenario_set,
        }.get(key),
    )
    state = _select_review_state(
        session_id="s1",
        request=request,
        artifact_refs=refs,
    )
    state["human_review_items"][0]["context"] = {
        "target_ids": ["target-unresolved"],
        "forged_scope": "different-request",
    }

    result = await root_graph._apply_select_auto_deferral(state)

    assert result["human_approval_diagnostic"]["code"] == "SELECT_DEFERRAL_SCOPE_STALE"
    assert "human_interrupt_request_binding_changed" in result["human_approval_diagnostic"]["reasons"]


@pytest.mark.asyncio
async def test_select_deferral_rejects_empty_content_digests(monkeypatch):
    from app.workflow import root_graph

    refs = {
        key: {
            "artifact_id": f"{key}:id-only",
            "digest": "",
            "descriptor_digest": "",
            "semantic_digest": "",
        }
        for key in ("scenario_set", "planning_scenario", "scoped_grounding_problem")
    }
    request = PendingRequest(
        request_id="select-pending",
        stage="select",
        request_type="scenario_approval_required",
        context={"target_ids": ["target-unresolved"]},
    )
    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        context_version="ctx:1",
        input_artifact_refs=refs,
        input_checksum=canonical_input_checksum(refs),
        pending_requests=[request],
    )
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: gate)
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda state, key, cls=None: None,
    )

    result = await root_graph._apply_select_auto_deferral(
        _select_review_state(
            session_id="s1",
            request=request,
            artifact_refs=refs,
        )
    )

    reasons = result["human_approval_diagnostic"]["reasons"]
    assert any(reason.startswith("input_artifact_ref_invalid:") for reason in reasons)


@pytest.mark.asyncio
async def test_select_deferral_same_targets_with_stale_scope_is_diagnostic(monkeypatch):
    from app.workflow import root_graph

    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        context_version="ctx:old",
        pending_requests=[PendingRequest(
            request_id="select-pending",
            stage="select",
            request_type="scenario_approval_required",
            context={"target_ids": ["target-unresolved"]},
        )],
    )
    persisted = []
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: gate)
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda state, key, cls=None: None,
    )
    monkeypatch.setattr(
        root_graph,
        "persist_stage_artifact",
        lambda *args, **kwargs: persisted.append(args) or {"ref": "unexpected"},
    )

    result = await root_graph._apply_select_auto_deferral({
        "session_id": "s1",
        "context_version": "ctx:new",
        "human_review_items": [gate.pending_requests[0]],
        "artifact_refs": {},
    })

    assert result["human_approval_diagnostic"]["code"] == "SELECT_DEFERRAL_SCOPE_STALE"
    assert persisted == []
    assert "scoped_replan_required" not in result


@pytest.mark.asyncio
async def test_select_deferral_ledger_persist_failure_is_fail_closed(monkeypatch):
    from app.workflow import root_graph

    problem = SimpleNamespace(
        candidate_completeness=SimpleNamespace(unresolved_target_ids=("target-unresolved",)),
        unresolved=[], deferred=[], target_domains=[],
        fingerprint="problem-1",
    )
    scenario = SimpleNamespace(problem_fingerprint="problem-1", findings=[])
    scenario_set = SimpleNamespace(problem_fingerprint="problem-1")
    refs = {
        "scenario_set": _artifact_ref("ScenarioSet"),
        "planning_scenario": _artifact_ref("PlanningScenario"),
        "scoped_grounding_problem": _artifact_ref("GroundedPlanningProblem"),
    }
    gate = GateDecision(
        stage="select",
        passed=False,
        feedback_route="HUMAN",
        context_version="ctx:1",
        input_artifact_refs=refs,
        input_checksum=canonical_input_checksum(refs),
        issue_fingerprint="scenario_not_complete",
        pending_requests=[PendingRequest(
            request_id="select-pending",
            stage="select",
            request_type="scenario_approval_required",
            context={"target_ids": ["target-unresolved"]},
        )],
    )
    monkeypatch.setattr(root_graph, "load_root_gate", lambda state, stage: gate)
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda state, key, cls=None: {
            "scoped_grounding_problem": problem,
            "planning_scenario": scenario,
            "scenario_set": scenario_set,
        }.get(key),
    )
    def fail_persist(*args, **kwargs):
        raise RuntimeError("provider body must not enter state")
    monkeypatch.setattr(root_graph, "persist_stage_artifact", fail_persist)

    result = await root_graph._apply_select_auto_deferral(
        _select_review_state(
            session_id="s1",
            request=gate.pending_requests[0],
            artifact_refs=refs,
        )
    )

    assert result["human_approval_diagnostic"]["code"] == "SELECT_DEFERRAL_LEDGER_PERSIST_FAILED"
    assert "artifact_refs" not in result
    assert "scoped_replan_required" not in result
    assert "human_deferred_targets" not in result
