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


def test_consumed_without_live_interrupt_is_filtered():
    # A genuinely consumed checkpoint (resume cleared human_interrupt) must not
    # be re-presented - resubmitting the same event_id would 409.
    state = {
        "human_review_resume_consumed": True,
        "human_interrupt": None,
    }
    assert _project(state) is None


def test_stale_consumed_flag_does_not_hide_live_interrupt():
    # human_review_resume_consumed is only reset by prepare_human_review inside
    # the hitl subgraph; the parent checkpoint view can still carry True when a
    # NEW pause is created.  A live interrupt must always be presented.
    state = {
        "human_review_resume_consumed": True,
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
    assert len(proj.get("items") or []) == 1


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


def test_pending_interrupt_projection_reads_nested_checkpoint_task():
    from app.application.queries.workflow_state import _pending_interrupt_projection

    class Pending:
        value = {
            "event_id": "nested-event",
            "channel": "step_mode",
            "reason": "human_review_required",
            "paused_stage": "layer3",
            "items": [{
                "request_id": "layer-3-completion-review",
                "stage": "layer3",
                "request_type": "layer_completion_review",
            }],
        }

    class Task:
        interrupts = (Pending(),)

    class Snapshot:
        tasks = (Task(),)

    projected = _pending_interrupt_projection(Snapshot())
    assert projected is not None
    assert projected["event_id"] == "nested-event"
    assert projected["paused_stage"] == "layer3"
    assert projected["items"] == [{
        "request_id": "layer-3-completion-review",
        "stage": "layer3",
        "request_type": "layer_completion_review",
        "context": {},
    }]
