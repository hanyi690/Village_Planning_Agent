"""Consumed HUMAN interrupts are never re-presented (idempotency).

A resume marks human_review_resume_consumed=True; presenting that interrupt
again makes the operator/test resubmit the same event_id and hit a 409
conflict.  A fresh interrupt resets consumed=False, so only pending checkpoints
are shown (exa: consumed checkpoints are never re-shown).
"""
from __future__ import annotations


def _project(state):
    from app.workflow.state import _interrupt_projection

    return _interrupt_projection(state)


def test_consumed_interrupt_is_filtered():
    state = {
        "human_review_resume_consumed": True,
        "human_interrupt": {
            "event_id": "abc",
            "paused_stage": "select",
            "items": [{"request_id": "r1"}],
        },
    }
    assert _project(state) is None


def test_pending_interrupt_is_presented():
    state = {
        "human_review_resume_consumed": False,
        "human_interrupt": {
            "event_id": "abc",
            "paused_stage": "select",
            "items": [{"request_id": "r1"}],
        },
        "human_review_items": [{"request_id": "r1"}],
        "human_review_event_id": "abc",
        "paused_stage": "select",
    }
    proj = _project(state)
    assert proj is not None
    assert proj.get("event_id") == "abc"
    assert proj.get("paused_stage") == "select"


def test_consumed_false_with_clean_state_is_none():
    assert _project({"human_review_resume_consumed": False}) is None
