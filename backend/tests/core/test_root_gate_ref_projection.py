from __future__ import annotations

from app.modules.schema.contracts.workflow_contracts import GateDecision
from app.workflow.root_graph import (
    END_DIAGNOSTIC,
    _gate_mutation_patch,
    _retry_exhaustion_patch,
    route_after_ground,
    route_after_target_projection,
)
from app.workflow.stage_adapter import persist_gate_decision
from app.workflow.state import RootGateResolutionError, load_root_gate


def _state(tmp_path, monkeypatch, stage: str, gate: GateDecision) -> dict:
    monkeypatch.setattr("app.services.run_paths.run_tmp_root", lambda: tmp_path)
    monkeypatch.setattr("app.infrastructure.artifacts.runtime.run_tmp_root", lambda: tmp_path)
    state = {
        "run_id": "run-root-gate",
        "session_id": "run-root-gate",
        "branch_id": "main",
        "context_ref": {"session_id": "run-root-gate", "version": "ctx-1"},
    }
    ref = persist_gate_decision(state, stage, gate)
    state["artifact_refs"] = {f"{stage}_gate": ref.model_dump(mode="json")}
    return state


def test_root_route_uses_gate_artifact_ref_over_inline_gate(tmp_path, monkeypatch):
    state = _state(tmp_path, monkeypatch, "ground", GateDecision(stage="ground", passed=True))
    state["ground_gate"] = {
        "stage": "ground",
        "passed": False,
        "feedback_route": "HUMAN",
    }

    assert route_after_ground(state) == "select"


def test_missing_post_l3_gate_ref_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.run_paths.run_tmp_root", lambda: tmp_path)
    monkeypatch.setattr("app.infrastructure.artifacts.runtime.run_tmp_root", lambda: tmp_path)
    state = {
        "run_id": "run-missing-gate",
        "session_id": "run-missing-gate",
        "branch_id": "main",
        "ground_gate": {"stage": "ground", "passed": True, "feedback_route": "PASS"},
        "artifact_refs": {},
    }

    assert route_after_ground(state) == END_DIAGNOSTIC
    try:
        load_root_gate(state, "ground")
    except RootGateResolutionError as exc:
        assert "missing artifact ref" in exc.reason
    else:
        raise AssertionError("missing post-L3 gate ref must not load")


def test_legacy_gate_scope_is_limited_to_l1_l2_l3(tmp_path, monkeypatch):
    legacy = {
        "l1_gate_decision": {
            "stage": "l1",
            "passed": True,
            "feedback_route": "PASS",
        },
        "ground_gate": {"stage": "ground", "passed": True, "feedback_route": "PASS"},
        "artifact_refs": {},
    }

    assert load_root_gate(legacy, "l1").passed is True
    try:
        load_root_gate(legacy, "ground")
    except RootGateResolutionError as exc:
        assert "missing artifact ref" in exc.reason
    else:
        raise AssertionError("post-L3 inline gate must not be accepted")


def test_post_l3_gate_mutations_replace_ref_and_retry_exhaustion_is_persisted(
    tmp_path, monkeypatch
):
    state = _state(
        tmp_path,
        monkeypatch,
        "ground",
        GateDecision(stage="ground", passed=False, feedback_route="EXPLORE"),
    )
    old_ref = state["artifact_refs"]["ground_gate"]

    mutation = _gate_mutation_patch(
        state,
        "ground",
        {"stage": "ground", "passed": False, "feedback_route": "HUMAN"},
    )
    assert mutation["gate_ref"] == mutation["artifact_refs"]["ground_gate"]
    assert mutation["gate_ref"]["descriptor_digest"] != old_ref["descriptor_digest"]
    resumed = {**state, **mutation}
    assert load_root_gate(resumed, "ground").feedback_route == "HUMAN"

    exhausted_state = {**state, "retry_counts": {"ground": 3}, "max_retries": 3}
    exhausted = _retry_exhaustion_patch(exhausted_state)
    assert exhausted["gate_ref"] == exhausted["artifact_refs"]["ground_gate"]
    exhausted_state = {**exhausted_state, **exhausted}
    assert load_root_gate(exhausted_state, "ground").feedback_route == "END_DIAGNOSTIC"
