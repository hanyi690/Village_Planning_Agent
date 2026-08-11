from app.modules.schema.contracts.resume_contracts import (
    ResumeMode,
    build_resume_plan,
)


def _state():
    return {
        "session_id": "session-1",
        "context_version": "ctx-1",
        "context_fingerprint": "fp-1",
        "artifact_refs": {
            "l1_snapshot": {
                "checksum": "l1-sum",
                "revision": "v1",
                "context_version": "ctx-1",
                "context_fingerprint": "fp-1",
            },
            "l2_strategy": {
                "checksum": "l2-sum",
                "revision": "v2",
                "context_version": "ctx-1",
                "context_fingerprint": "fp-1",
                "parent_checksums": {
                    "l1_snapshot": "v1:l1-sum",
                },
            },
            "planning_program": {
                "checksum": "l3-sum",
                "revision": "v3",
                "context_version": "ctx-1",
                "context_fingerprint": "fp-1",
                "parent_checksums": {
                    "l1_snapshot": "v1:l1-sum",
                    "l2_strategy": "v2:l2-sum",
                },
            },
        },
    }


def test_pending_interrupt_has_priority_over_graph_next():
    state = _state()
    state["artifact_refs"]["l2_strategy"]["checksum"] = "l2-changed"

    plan = build_resume_plan(
        state,
        session_id="session-1",
        checkpoint_id="cp-1",
        next_nodes=["layer_completion_check"],
        pending_interrupt={
            "event_id": "human-1",
            "channel": "step_mode",
        },
    )

    assert plan.mode == ResumeMode.INTERRUPT
    assert plan.resume_from == "layer_completion_check"
    assert plan.interrupt_id == "human-1"
    assert plan.reuse == ["l1_snapshot", "l2_strategy", "planning_program"]


def test_revision_plan_lists_downstream_rerun_boundary_and_checksums_for_unchanged_parents():
    plan = build_resume_plan(
        _state(),
        session_id="session-1",
        checkpoint_id="cp-2",
        checkpoint_kind="revision",
        next_nodes=["select"],
    )

    assert plan.mode == ResumeMode.RERUN
    assert plan.resume_from == "select"
    assert plan.rerun == ["SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"]
    assert plan.reuse == ["l1_snapshot", "l2_strategy", "planning_program"]
    assert plan.input_checksums["planning_program"] == "l3-sum"


def test_changed_parent_checksum_forces_rerun_from_earliest_invalid_stage():
    state = _state()
    state["artifact_refs"]["l2_strategy"]["checksum"] = "l2-changed"

    plan = build_resume_plan(
        state,
        session_id="session-1",
        checkpoint_kind="layer",
        next_nodes=["select"],
    )

    assert plan.mode == ResumeMode.RERUN
    assert plan.resume_from == "L3"
    assert plan.reuse == ["l1_snapshot", "l2_strategy"]
    assert plan.rerun == ["L3", "PARSE", "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"]
    assert plan.reason == "parent identity changed at L3"


def test_changed_parent_revision_forces_rerun_from_earliest_invalid_stage():
    state = _state()
    state["artifact_refs"]["l2_strategy"]["revision"] = "v9"

    plan = build_resume_plan(
        state,
        session_id="session-1",
        checkpoint_kind="revision",
        next_nodes=["select"],
    )

    assert plan.mode == ResumeMode.RERUN
    assert plan.resume_from == "L3"
    assert plan.reuse == ["l1_snapshot", "l2_strategy"]
    assert plan.reason == "parent identity changed at L3"


def test_missing_parent_metadata_is_treated_conservatively():
    state = _state()
    state["artifact_refs"]["planning_program"].pop("parent_checksums")

    plan = build_resume_plan(
        state,
        session_id="session-1",
        checkpoint_kind="revision",
        next_nodes=["select"],
    )

    assert plan.mode == ResumeMode.RERUN
    assert plan.resume_from == "L3"
    assert plan.reuse == ["l1_snapshot", "l2_strategy"]
    assert plan.reason == "parent identity missing at L3"


def test_diagnostic_terminal_is_blocked_and_completed_is_terminal():
    blocked = build_resume_plan(
        {**_state(), "diagnostic_terminal": {"stage": "select"}},
        session_id="session-1",
    )
    completed = build_resume_plan(
        {**_state(), "phase": "completed"},
        session_id="session-1",
    )

    assert blocked.mode == ResumeMode.BLOCKED
    assert completed.mode == ResumeMode.COMPLETED
