"""Regression tests for the declarative gate-route policy (A1/A2/A3).

Pins the exact behavior of the post-L3 gate routers and the HITL resume
router after they were converged onto the policy table.  Any future change
to the table that alters a transition must update this file.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.workflow import root_graph
from app.workflow.root_graph import (
    END,
    END_DIAGNOSTIC,
    route_after_deliver,
    route_after_ground,
    route_after_human_review,
    route_after_reconcile,
    route_after_select,
    route_after_target_projection,
    route_after_validate,
)
from app.workflow.state import GATE_LOAD_FAILED


def _patch_gate_route(monkeypatch, route: str) -> None:
    monkeypatch.setattr(root_graph, "root_gate_route", lambda _state, _stage: route)


def _gate(monkeypatch, **attrs) -> None:
    monkeypatch.setattr(
        root_graph,
        "load_root_gate",
        lambda _state, _stage: SimpleNamespace(**attrs),
    )


def _base_state() -> dict:
    # Default retry budget keeps `_retry_or_human` on the happy path.
    return {"retry_counts": {}, "max_retries": 3}


# ── A1: post-L3 gate routers ─────────────────────────────────────────


def test_target_projection_policy(monkeypatch) -> None:
    cases = {
        "PASS": "ground",
        "REPAIR": "target_projection",
        "REVISE": "target_projection",
        "HUMAN": "human_review",
        "EXPLORE": "human_review",
        GATE_LOAD_FAILED: END_DIAGNOSTIC,
    }
    for route, expected in cases.items():
        _patch_gate_route(monkeypatch, route)
        assert route_after_target_projection(_base_state()) == expected


def test_ground_policy(monkeypatch) -> None:
    cases = {
        "PASS": "select",
        "EXPLORE": "ground",
        "HUMAN": "human_review",
        GATE_LOAD_FAILED: END_DIAGNOSTIC,
    }
    for route, expected in cases.items():
        _patch_gate_route(monkeypatch, route)
        assert route_after_ground(_base_state()) == expected


def test_select_policy(monkeypatch) -> None:
    cases = {
        "PASS": "execute",
        "RETRY_GROUND": "ground",
        "HUMAN": "human_review",
        GATE_LOAD_FAILED: END_DIAGNOSTIC,
    }
    for route, expected in cases.items():
        _patch_gate_route(monkeypatch, route)
        assert route_after_select(_base_state()) == expected


def test_validate_policy(monkeypatch) -> None:
    # _retry_or_human loads the validate gate to compare issue fingerprints.
    _gate(monkeypatch, issue_fingerprint="", passed=True, feedback_route=None)
    cases = {
        "PASS": "reconcile",
        # Literal END_DIAGNOSTIC feedback route is a legitimate table entry.
        "END_DIAGNOSTIC": "reconcile",
        "RETRY_EXECUTE": "execute",
        "RETRY_SELECT": "select",
        "RETRY_GROUND": "ground",
        "RETRY_TARGET_PROJECTION": "target_projection",
        "HUMAN": "human_review",
        GATE_LOAD_FAILED: END_DIAGNOSTIC,
    }
    for route, expected in cases.items():
        _patch_gate_route(monkeypatch, route)
        assert route_after_validate(_base_state()) == expected


def test_validate_retry_l3_needs_revision_dimensions(monkeypatch) -> None:
    _gate(monkeypatch, issue_fingerprint="", passed=True, feedback_route=None)
    _patch_gate_route(monkeypatch, "RETRY_L3")
    assert route_after_validate(_base_state()) == "human_review"
    assert (
        route_after_validate({**_base_state(), "revision_target_dimensions": ["road"]})
        == "revision_dispatch"
    )


def test_reconcile_policy(monkeypatch) -> None:
    cases = {
        "PASS": "deliver",
        "END_DIAGNOSTIC": "deliver",
        "RETRY_EXECUTE": "execute",
        "RETRY_L3": "human_review",
        "HUMAN": "human_review",
        GATE_LOAD_FAILED: END_DIAGNOSTIC,
    }
    for route, expected in cases.items():
        _patch_gate_route(monkeypatch, route)
        assert route_after_reconcile(_base_state()) == expected


def test_deliver_policy(monkeypatch) -> None:
    cases = {
        "PASS": END,
        "END_DIAGNOSTIC": END_DIAGNOSTIC,
        "HUMAN": END_DIAGNOSTIC,
        GATE_LOAD_FAILED: END_DIAGNOSTIC,
    }
    for route, expected in cases.items():
        _patch_gate_route(monkeypatch, route)
        assert route_after_deliver(_base_state()) == expected


def test_gate_retry_budget_exhaustion_fails_closed(monkeypatch) -> None:
    _gate(monkeypatch, issue_fingerprint="", passed=True, feedback_route=None)
    _patch_gate_route(monkeypatch, "EXPLORE")
    exhausted = {**_base_state(), "retry_counts": {"ground": 3}}
    assert route_after_ground(exhausted) == END_DIAGNOSTIC
    _patch_gate_route(monkeypatch, "RETRY_EXECUTE")
    assert route_after_validate({**_base_state(), "retry_counts": {"validate": 3}}) == END_DIAGNOSTIC


# ── A2: HITL resume router ───────────────────────────────────────────


def _resume(state: dict) -> str:
    return route_after_human_review(state)


def test_resume_provider_resume_fanout_takes_priority() -> None:
    assert _resume({"provider_resume_dimensions": ["road"]}) == "provider_resume_dispatch"


def test_resume_post_l3_gate_load_failed_fails_closed(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, GATE_LOAD_FAILED)
    for stage in ("ground", "select", "validate", "reconcile", "deliver", "target_projection"):
        assert _resume({"paused_stage": stage}) == END_DIAGNOSTIC
    # Layer pauses are not post-L3 gate stages.
    assert _resume({"paused_stage": "l3"}) == END


def test_resume_diagnostic_only_forwards_validate_reconcile(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, "PASS")
    state = {
        "delivery_status": "diagnostic_only",
        "paused_stage": "validate",
        "human_review_decisions": {"action": "retry"},
    }
    assert _resume(state) == "reconcile"
    state["paused_stage"] = "reconcile"
    assert _resume(state) == "deliver"
    state["paused_stage"] = "ground"
    assert _resume(state) == END_DIAGNOSTIC


def test_resume_diagnostic_only_accept_on_structural_failure_ends(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, "PASS")
    state = {
        "delivery_status": "diagnostic_only",
        "paused_stage": "validate",
        "human_review_decisions": {"action": "approve"},
    }
    assert _resume(state) == END_DIAGNOSTIC


def test_resume_fatal_error_ends() -> None:
    assert _resume({"fatal_error": {"code": "boom"}}) == END


def test_resume_approve_classification_revision() -> None:
    state = {
        "paused_stage": "l3",
        "classification_revision": True,
        "human_review_decisions": {"action": "approve"},
    }
    assert _resume(state) == "target_projection"


def test_resume_approve_validate_reconcile(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, "PASS")
    state = {"paused_stage": "validate", "human_review_decisions": {"action": "approve"}}
    assert _resume(state) == END_DIAGNOSTIC
    state["structural_deferral_revision"] = True
    assert _resume(state) == "execute"


def test_resume_approve_layer_forwards(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, "PASS")
    assert (
        _resume({"paused_stage": "l1", "human_review_decisions": {"action": "approve"}})
        == "advance_phase"
    )
    assert (
        _resume({"paused_stage": "l3", "human_review_decisions": {"action": "approve"}})
        == "target_projection"
    )


def test_resume_approve_select(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, "PASS")
    state = {"paused_stage": "select", "human_review_decisions": {"action": "approve"}}
    assert _resume(state) == "execute"
    state["human_review_decisions"] = {
        "action": "approve",
        "defer_unresolved_spatial_references": True,
    }
    # Approval is the authoritative operator decision; unplaced targets are
    # deferred to the deferral/diagnostic path, never looped back to HUMAN.
    assert _resume(state) == "execute"
    state["human_deferred_select_revision"] = True
    assert _resume(state) == "execute"


def test_resume_approve_ground_continues_to_select(monkeypatch) -> None:
    # Approving a GROUND review accepts the grounding as-is and must continue
    # to SELECT.  Remaining unresolved references are handled by SELECT/EXECUTE
    # deferral or partial delivery - re-looping to HUMAN here is the deadlock
    # that left real runs parked in post_l3 with no tasks and no terminal.
    _patch_gate_route(monkeypatch, "PASS")
    state = {
        "paused_stage": "ground",
        "remaining_target_ids": ["target-1"],
        "human_review_decisions": {"action": "approve"},
    }
    assert _resume(state) == "select"


def test_resume_approve_ground_defer(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, "PASS")
    state = {
        "paused_stage": "ground",
        "human_review_decisions": {
            "action": "approve",
            "defer_unresolved_spatial_references": True,
        },
    }
    assert _resume(state) == "select"
    _patch_gate_route(monkeypatch, "EXPLORE")
    # Operator defer is authoritative; the stale gate route must not loop
    # the session back into HUMAN.
    assert _resume(state) == "select"


def test_resume_approve_default_ends() -> None:
    assert _resume({"paused_stage": None, "human_review_decisions": {"action": "approve"}}) == END


def test_resume_retry_revision_dispatch() -> None:
    state = {
        "paused_stage": "l3",
        "is_revision": True,
        "revision_target_dimensions": ["road"],
        "human_review_decisions": {"action": "retry"},
    }
    assert _resume(state) == "revision_dispatch"


def test_resume_retry_validate_gate_progress_blocked(monkeypatch) -> None:
    _gate(monkeypatch, progress_made=False, inputs_changed=True)
    state = {
        "paused_stage": "validate",
        "human_review_decisions": {"action": "retry"},
        "retry_counts": {"validate": 0},
        "max_retries": 3,
    }
    assert _resume(state) == END_DIAGNOSTIC


def test_resume_retry_budget_exhausted() -> None:
    state = {
        "paused_stage": "ground",
        "human_review_decisions": {"action": "retry"},
        "retry_counts": {"ground": 3},
        "max_retries": 3,
    }
    assert _resume(state) == END_DIAGNOSTIC


def test_resume_retry_ok_returns_stage(monkeypatch) -> None:
    _patch_gate_route(monkeypatch, "PASS")
    state = {
        "paused_stage": "ground",
        "human_review_decisions": {"action": "retry"},
        "retry_counts": {"ground": 1},
        "max_retries": 3,
    }
    assert _resume(state) == "ground"


def test_resume_reject_goes_to_conversation() -> None:
    assert _resume({"paused_stage": "l3", "human_review_decisions": {"action": "reject"}}) == "conversation"


def test_resume_unknown_action_ends() -> None:
    assert _resume({"paused_stage": "l3", "human_review_decisions": {"action": "ignore"}}) == END
