from __future__ import annotations

import pytest

from app.infrastructure.artifacts.runtime import (
    ArtifactReplayError,
    fork_artifact_refs,
    store_artifact,
    validate_artifact_refs_branch,
)


def _state(branch_id: str = "main", refs: dict | None = None) -> dict:
    return {
        "run_id": "replay-hygiene-run",
        "session_id": "replay-hygiene-session",
        "branch_id": branch_id,
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "replay-hygiene-session", "version": "1"},
        "artifact_refs": refs or {},
    }


def test_mixed_checkpoint_refs_fail_before_store_or_fork(tmp_path):
    main_ref = store_artifact(
        _state(),
        "scenario_set",
        "select",
        "ScenarioSet",
        {"branch": "main"},
        base_dir=tmp_path,
    )
    fork_ref = store_artifact(
        _state("resume-fork-1"),
        "execution_plan",
        "execute",
        "ExecutionPlan",
        {"branch": "resume-fork-1"},
        base_dir=tmp_path,
    )
    mixed = _state(refs={"scenario_set": main_ref, "execution_plan": fork_ref})

    with pytest.raises(ArtifactReplayError, match="span branches"):
        validate_artifact_refs_branch(mixed)
    with pytest.raises(ArtifactReplayError, match="span branches"):
        store_artifact(
            mixed,
            "execution_result",
            "execute",
            "ExecutionResult",
            {"status": "blocked"},
            base_dir=tmp_path,
        )
    with pytest.raises(ArtifactReplayError, match="span branches"):
        fork_artifact_refs(mixed, "resume-fork-2", base_dir=tmp_path)

    assert not (tmp_path / "runs" / "replay-hygiene-run" / "branches" / "main" / "refs" / "execution_result.json").exists()


def test_checkpoint_refs_from_one_branch_are_accepted(tmp_path):
    state = _state()
    ref = store_artifact(
        state,
        "scenario_set",
        "select",
        "ScenarioSet",
        {"branch": "main"},
        base_dir=tmp_path,
    )
    assert validate_artifact_refs_branch(_state(refs={"scenario_set": ref})) == "main"
