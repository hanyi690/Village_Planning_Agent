from app.agent.plan_state.state import state_to_ui_status


def test_interrupted_post_l3_not_reported_completed():
    state = {"phase": "completed", "deliver_gate": None, "metadata": {}}
    out = state_to_ui_status(state, is_interrupted=True)
    assert out["status"] != "completed", \
        "interrupted post-L3 must not report completed even if phase=completed"
    assert out["status"] == "paused"


def test_completed_only_when_deliver_gate_pass():
    state = {"phase": "completed", "metadata": {}}
    assert state_to_ui_status(state)["status"] != "completed"
    state["deliver_gate"] = {"feedback_route": "PASS"}
    assert state_to_ui_status(state)["status"] == "completed"


def test_completed_phase_running_without_deliver_pass():
    state = {"phase": "completed", "deliver_gate": {"feedback_route": "RETRY_VALIDATE"}, "metadata": {}}
    out = state_to_ui_status(state)
    assert out["status"] == "running"
