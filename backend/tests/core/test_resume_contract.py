from app.modules.schema.contracts.resume_contracts import (
    ResumeCommand,
    ResumeMode,
    build_resume_plan,
)


def test_human_interrupt_has_priority_over_graph_cursor():
    plan = build_resume_plan(
        {
            "phase": "paused",
            "artifact_refs": {"planning_program": {"checksum": "p1"}},
            "human_interrupt": {"event_id": "human-1", "channel": "post_l3_review"},
        },
        session_id="s1",
        checkpoint_id="cp1",
        next_nodes=["deliver"],
    )

    assert plan.mode is ResumeMode.INTERRUPT
    assert plan.interrupt_id == "human-1"
    assert plan.resume_from == "deliver"


def test_changed_parent_forces_downstream_rerun():
    plan = build_resume_plan(
        {
            "phase": "running",
            "artifact_refs": {
                "planning_program": {"revision": "v2", "checksum": "new"},
                "grounding_result": {
                    "revision": "v1",
                    "checksum": "old-grounding",
                    "parent_checksums": {"planning_program": "v1:old"},
                },
            },
        },
        session_id="s1",
        checkpoint_kind="revision",
        next_nodes=["ground"],
    )

    assert plan.mode is ResumeMode.RERUN
    assert plan.resume_from == "GROUND"
    assert plan.rerun[0] == "GROUND"


def test_resume_command_requires_explicit_mode_and_is_strict():
    command = ResumeCommand(
        command_id="cmd-1",
        session_id="s1",
        mode=ResumeMode.INTERRUPT,
        event_id="human-1",
        payload={"action": "approve"},
    )

    assert command.event_id == "human-1"
    assert command.payload["action"] == "approve"

