from app.contracts.workflow.resume_contracts import (
    ResumeMode,
    build_resume_plan,
)


def _state():
    l1_digest = "sha256:" + "1" * 64
    l2_digest = "sha256:" + "2" * 64
    l3_digest = "sha256:" + "3" * 64
    return {
        "session_id": "session-1",
        "context_version": "ctx-1",
        "context_fingerprint": "fp-1",
        "artifact_refs": {
            "l1_snapshot": {
                "digest": l1_digest,
                "descriptor_digest": "sha256:" + "a" * 64,
                "provenance": {"context_ref": {"version": "ctx-1"}, "context_fingerprint": "fp-1"},
            },
            "l2_strategy": {
                "digest": l2_digest,
                "descriptor_digest": "sha256:" + "b" * 64,
                "provenance": {"context_ref": {"version": "ctx-1"}, "context_fingerprint": "fp-1"},
                "parent_digests": {
                    "l1_snapshot": l1_digest,
                },
            },
            "planning_program": {
                "digest": l3_digest,
                "descriptor_digest": "sha256:" + "c" * 64,
                "provenance": {"context_ref": {"version": "ctx-1"}, "context_fingerprint": "fp-1"},
                "parent_digests": {
                    "l1_snapshot": l1_digest,
                    "l2_strategy": l2_digest,
                },
            },
        },
    }


def test_pending_interrupt_has_priority_over_graph_next():
    state = _state()
    state["artifact_refs"]["l2_strategy"]["digest"] = "sha256:" + "4" * 64

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
    assert plan.input_checksums["planning_program"] == "sha256:" + "c" * 64


def test_changed_parent_checksum_forces_rerun_from_earliest_invalid_stage():
    state = _state()
    state["artifact_refs"]["l2_strategy"]["digest"] = "sha256:" + "4" * 64

    plan = build_resume_plan(
        state,
        session_id="session-1",
        checkpoint_kind="layer",
        next_nodes=["select"],
    )

    assert plan.mode == ResumeMode.RERUN
    assert plan.resume_from == "L3"
    assert plan.reuse == ["l1_snapshot", "l2_strategy"]
    assert plan.rerun == ["L3", "TARGET_PROJECTION", "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"]
    assert plan.reason == "parent identity changed at L3"


def test_changed_parent_revision_forces_rerun_from_earliest_invalid_stage():
    state = _state()
    state["artifact_refs"]["l2_strategy"]["descriptor_digest"] = "sha256:" + "9" * 64
    state["artifact_refs"]["l2_strategy"]["digest"] = "sha256:" + "4" * 64

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
    state["artifact_refs"]["planning_program"].pop("parent_digests")

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
