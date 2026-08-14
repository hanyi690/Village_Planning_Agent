"""HITL resume routing (A2) - L3 approve must forward to target_projection.

Design: approving a layer gate continues processing; unresolved spatial
facts are handled by projection/GROUND, never looped back to HUMAN.
"""
from __future__ import annotations


def _state(paused_stage="l3", action="approve", **extra):
    state = {
        "paused_stage": paused_stage,
        "human_review_decisions": {"action": action, "feedback": "ok"},
    }
    state.update(extra)
    return state


def test_l3_approve_forwards_to_target_projection():
    from app.workflow.root_graph import route_after_human_review

    route = route_after_human_review(_state(paused_stage="l3"))
    assert route == "target_projection"


def test_l3_approve_with_defer_still_forwards():
    from app.workflow.root_graph import route_after_human_review

    state = _state(paused_stage="l3")
    state["human_review_decisions"].update(
        {
            "acknowledge_unresolved_spatial_references": True,
            "defer_unresolved_spatial_references": True,
            "deferred_target_ids": [],
        }
    )
    assert route_after_human_review(state) == "target_projection"


def test_l1_l2_approve_forwards_to_advance_phase():
    from app.workflow.root_graph import route_after_human_review

    assert route_after_human_review(_state(paused_stage="l1")) == "advance_phase"
    assert route_after_human_review(_state(paused_stage="l2")) == "advance_phase"


def test_reject_routes_to_conversation():
    from app.workflow.root_graph import route_after_human_review

    assert route_after_human_review(_state(action="reject")) == "conversation"


def test_hitl_cross_map_has_l3_forward_target():
    from app.workflow.segments import _HITL_CROSS

    assert _HITL_CROSS["target_projection"] == ("spatial_chain", None)


def test_stage_forward_target_l3():
    from app.workflow.stages.support import STAGE_FORWARD_TARGET

    assert STAGE_FORWARD_TARGET["l3"] == "target_projection"



def _gate_state(paused_stage, **extra):
    state = _state(paused_stage=paused_stage, action="approve")
    state["human_review_decisions"].update(
        {
            "acknowledge_unresolved_spatial_references": True,
            "defer_unresolved_spatial_references": True,
            "deferred_target_ids": ["ecological:claim:EG-005"],
        }
    )
    state.update(extra)
    return state


def test_ground_approve_with_defer_forwards_to_select():
    """Operator defer is the authoritative decision; the stale HUMAN gate
    must not loop the session back into HUMAN forever."""
    from app.workflow.root_graph import _approve_ground

    state = _gate_state("ground")
    assert _approve_ground(state, "ground") == "select"


def test_select_approve_with_defer_forwards_to_execute():
    from app.workflow.root_graph import _approve_select

    state = _gate_state("select")
    assert _approve_select(state, "select") == "execute"

