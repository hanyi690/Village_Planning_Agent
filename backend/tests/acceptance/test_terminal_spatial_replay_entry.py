from app.infrastructure.runtime.planning_runtime_service import _spatial_replay_goto
from app.application.recovery.resume_service import ResumeService
from backend.scripts.resume_graph_checkpoint import _continuation_branch
from app.workflow.state import _replace_branch_id


def test_terminal_spatial_replay_enters_the_spatial_segment() -> None:
    assert _spatial_replay_goto(
        {"subgraph_entry": "ground"},
        "ground",
    ) == "spatial_chain"


def test_non_explicit_replay_keeps_the_historical_cursor() -> None:
    assert _spatial_replay_goto(
        {"subgraph_entry": "ground"},
        None,
    ) is None


def test_stale_cursor_accepts_only_explicit_spatial_entry() -> None:
    state = {
        "diagnostic_terminal": {
            "code": "STALE_CHECKPOINT_NO_EXECUTABLE_CURSOR",
        }
    }
    assert _spatial_replay_goto(state, "ground") == "spatial_chain"
    assert _spatial_replay_goto(state, "conversation") is None


def test_unauthorized_stage_terminal_accepts_explicit_spatial_entry() -> None:
    state = {
        "diagnostic_terminal": {
            "code": "UNAUTHORIZED_STAGE",
        }
    }
    assert _spatial_replay_goto(state, "target_projection") == "spatial_chain"


def test_resume_branch_replaces_source_and_ignores_stale_nested_writer() -> None:
    assert _replace_branch_id("fresh-ground-1", "resume-wave3-1") == "resume-wave3-1"
    assert _replace_branch_id("resume-wave3-1", "fresh-ground-1") == "resume-wave3-1"
    assert _spatial_replay_goto(
        {"subgraph_entry": "conversation"},
        "ground",
    ) is None


def test_resume_fork_branch_replaces_existing_resume_source_safely() -> None:
    assert _replace_branch_id(
        "resume-source-1",
        "resume-fork-child-1",
    ) == "resume-fork-child-1"
    assert _replace_branch_id(
        "resume-fork-child-1",
        "resume-source-1",
    ) == "resume-fork-child-1"


def test_continuation_branch_names_nested_resume_forks_explicitly() -> None:
    assert _continuation_branch("main", "child") == "resume-child"
    assert _continuation_branch("resume-source", "child") == "resume-fork-child"
    assert _continuation_branch("resume-source", "resume-child") == "resume-fork-child"
    assert _continuation_branch("resume-source", "resume-fork-child") == "resume-fork-child"


def test_nested_spatial_interrupt_ref_is_resumable_by_exact_event() -> None:
    ResumeService.validate_interrupt(
        {"interrupt_ref": {"event_id": "nested-event"}},
        "nested-event",
    )
