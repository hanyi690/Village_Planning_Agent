from app.workflow.state import control_state_from_checkpoint


def test_projection_drops_legacy_payloads_and_normalizes_control_fields():
    projected = control_state_from_checkpoint(
        {
            "session_id": "session-1",
            "branch_id": "fork-1",
            "phase": "post_l3",
            "paused_stage": "DELIVER",
            "retry_counts": {"deliver": 1},
            "human_interrupt": {"event_id": "evt-1", "items": [{"id": "x"}]},
            "delivery_manifest": {"should_not": "be in control state"},
            "gis_data": {"type": "FeatureCollection"},
            "messages": [{"content": "report text"}],
        }
    )

    assert projected["active_stage"] == "DELIVER"
    assert projected["status"] == "paused"
    assert projected["retry"] == {"deliver": 1}
    assert projected["interrupt_ref"] == {
        "event_id": "evt-1",
        "items": [{"id": "x"}],
        "paused_stage": "DELIVER",
    }
    assert "gis_data" not in projected
    assert "messages" not in projected
    assert "delivery_manifest" not in projected


def test_projection_prefers_canonical_fields_when_present():
    projected = control_state_from_checkpoint(
        {
            "run_id": "run-1",
            "session_id": "session-1",
            "branch_id": "main",
            "active_stage": "GROUND",
            "status": "running",
            "retry": {"GROUND": 2},
            "context_ref": {"bundle": "ctx-1"},
            "artifact_refs": {"grounding_result": {"digest": "abc"}},
        }
    )

    assert projected["run_id"] == "run-1"
    assert projected["active_stage"] == "GROUND"
    assert projected["status"] == "running"
    assert projected["retry"] == {"GROUND": 2}
    assert projected["artifact_refs"]["grounding_result"]["digest"] == "abc"


def test_projection_keeps_step_mode_items_at_the_interrupt_boundary():
    projected = control_state_from_checkpoint(
        {
            "session_id": "session-1",
            "phase": "layer2",
            "paused_stage": "layer2",
            "human_review_event_id": "step-evt",
            "human_review_items": [{"id": "layer2-review"}],
        }
    )

    assert projected["interrupt_ref"] == {
        "event_id": "step-evt",
        "items": [{"id": "layer2-review"}],
        "paused_stage": "layer2",
    }
