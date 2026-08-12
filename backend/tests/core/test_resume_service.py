from types import SimpleNamespace

import pytest

from app.services.resume_service import ResumeConflictError, ResumeService
from app.modules.schema.contracts.resume_contracts import ResumePlan, ResumeMode


def test_plan_for_snapshot_is_shared_checkpoint_policy():
    snapshot = SimpleNamespace(
        values={"phase": "completed"},
        next=(),
        config={"configurable": {"checkpoint_id": "cp-1"}},
        tasks=(),
    )

    stable, kind, plan = ResumeService.plan_for_snapshot("s1", snapshot)

    assert stable is True
    assert kind == "completed"
    assert plan.checkpoint_id == "cp-1"


def test_interrupt_token_is_compare_and_set():
    state = {"human_interrupt": {"event_id": "new"}}
    with pytest.raises(ResumeConflictError):
        ResumeService.validate_interrupt(state, "old")

    with pytest.raises(ResumeConflictError):
        ResumeService.validate_interrupt(
            {"human_review_resume_consumed": True, "human_interrupt": {"event_id": "new"}},
            "new",
        )


def test_reusable_artifact_integrity_is_recorded(monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda state, key: {"key": key},
    )
    plan = ResumePlan(
        session_id="s1",
        mode=ResumeMode.CHECKPOINT,
        resume_from="SELECT",
        checkpoint_kind="layer",
        reuse=["planning_program"],
        reason="test",
    )

    checked = ResumeService.verify_reusable_artifacts({}, plan)

    assert checked.artifact_integrity == {"planning_program": "valid"}


def test_select_replay_snapshot_uses_safe_artifact_prefix():
    def snapshot(checkpoint_id, refs):
        return SimpleNamespace(
            values={
                "artifact_refs": refs,
                "previous_layer": 1,
                "layer_just_completed": 1,
            },
            config={"configurable": {"checkpoint_id": checkpoint_id}},
            tasks=(),
        )

    plan = ResumePlan(
        session_id="s1",
        mode=ResumeMode.RERUN,
        resume_from="GROUND",
        checkpoint_kind="layer",
        reuse=["planning_program"],
        rerun=["GROUND", "SELECT"],
        reason="repair",
    )
    selected = ResumeService.select_replay_snapshot(
        [
            snapshot("late", {"planning_program": {"checksum": "p"}, "grounding_result": {}}),
            snapshot("safe", {"planning_program": {"checksum": "p"}}),
        ],
        plan,
    )

    assert selected.config["configurable"]["checkpoint_id"] == "safe"


def test_checkpoint_resume_script_requires_a_new_branch_for_historical_continuation():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "resume_graph_checkpoint.py").read_text(
        encoding="utf-8"
    )
    assert "--branch-id" in source
    assert "branch_id=args.branch_id or" in source


def test_historical_resume_branch_replaces_checkpoint_namespace():
    from app.agent.plan_state.state import _replace_branch_id

    assert _replace_branch_id("historical", "resume-1") == "resume-1"
    assert _replace_branch_id("historical", "") == "historical"
