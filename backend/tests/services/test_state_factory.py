"""Acceptance: single StateFactory for production and tests."""
import pytest
from app.agent.plan_state.state_factory import StateFactory


def test_factory_seeds_all_post_l3_fields():
    state = StateFactory.create(
        session_id="s1", project_name="p", village_data="{}",
        task_description="t", constraints="c",
    )
    required = [
        "specs", "parse_gate", "ground_gate", "select_gate",
        "validate_gate", "reconcile_gate", "deliver_gate",
        "artifact_refs", "context_version", "context_ref", "context_fingerprint",
        "bootstrap_context_done", "human_review_items", "paused_stage",
        "retry_counts", "max_retries", "error_feedback", "pending_requests",
    ]
    missing = [f for f in required if f not in state]
    assert not missing, f"Missing fields: {missing}"


def test_factory_seeds_production_extras():
    state = StateFactory.create(
        session_id="s1", project_name="p", village_data="{}",
        task_description="t", constraints="c",
        province="GD", rag_layer_config={1: True, 2: False, 3: True},
    )
    assert state["config"]["province"] == "GD"
    assert state["config"]["rag_layer_config"] == {1: True, 2: False, 3: True}
    assert "reports" in state
    assert "_streaming_enabled" in state


def test_factory_mutable_defaults_not_shared():
    s1 = StateFactory.create(session_id="s1", project_name="p", village_data="{}",
                              task_description="t", constraints="c")
    s2 = StateFactory.create(session_id="s2", project_name="p", village_data="{}",
                              task_description="t", constraints="c")
    s1["artifact_refs"]["test"] = "x"
    assert "test" not in s2["artifact_refs"], "Mutable defaults must not be shared"


def test_factory_config_no_duplicate_facts():
    """config should not duplicate top-level fact fields."""
    state = StateFactory.create(
        session_id="s1", project_name="p", village_data="{}",
        task_description="t", constraints="c",
    )
    # context_version is a top-level field, not in config
    assert "context_version" not in state["config"]