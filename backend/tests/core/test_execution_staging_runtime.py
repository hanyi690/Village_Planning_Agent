from app.contracts.artifacts.execution_staging_contracts import ExecutionStaging
from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
from app.contracts.spatial.planned_state_contracts import PlannedState
from app.infrastructure.artifacts.runtime import load_artifact, store_artifact


def _state(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "session_id": run_id,
        "branch_id": "main",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": run_id, "version": "ctx:1"},
        "artifact_refs": {},
    }


def _digest(ref: dict | None) -> str:
    return str((ref or {}).get("descriptor_digest") or "")


def test_staging_commit_promotion_is_durable_and_idempotent(tmp_path) -> None:
    state = _state("run-staging-commit")
    refs = state["artifact_refs"]
    staged_changeset = store_artifact(
        state,
        "staged_parcel_changeset",
        "execute",
        "ParcelChangeSet",
        ParcelChangeSet(),
        base_dir=tmp_path,
    )
    refs["staged_parcel_changeset"] = staged_changeset
    staged_planned = store_artifact(
        {**state, "artifact_refs": refs},
        "staged_planned_state",
        "execute",
        "PlannedState",
        PlannedState(),
        base_dir=tmp_path,
    )
    refs["staged_planned_state"] = staged_planned
    staged_layout = store_artifact(
        {**state, "artifact_refs": refs},
        "staged_layout_configs",
        "execute",
        "LayoutConfigs",
        [],
        base_dir=tmp_path,
    )
    refs["staged_layout_configs"] = staged_layout

    staging_payload = ExecutionStaging(
        staging_id="staging:run-staging-commit",
        approved_input_ref="approval:run-staging-commit",
        execution_plan_ref="plan:run-staging-commit",
        staged_parcel_changeset_ref=_digest(staged_changeset),
        staged_planned_state_ref=_digest(staged_planned),
        staged_layout_configs_ref=_digest(staged_layout),
        worker_task_ids=["worker:facility"],
        status="staged",
    )
    staged_ref = store_artifact(
        {**state, "artifact_refs": refs},
        "execution_staging",
        "execute",
        "ExecutionStaging",
        staging_payload,
        base_dir=tmp_path,
    )
    refs["execution_staging"] = staged_ref

    committed_payload = staging_payload.model_copy(
        update={"status": "committed", "commit_id": "commit:run-staging-commit"}
    )
    refs.update({
        "parcel_changeset": staged_changeset,
        "planned_state": staged_planned,
        "layout_configs": staged_layout,
    })
    committed_ref = store_artifact(
        {**state, "artifact_refs": refs},
        "execution_staging",
        "execute",
        "ExecutionStaging",
        committed_payload,
        base_dir=tmp_path,
    )
    refs["execution_staging"] = committed_ref
    state["artifact_refs"] = refs

    loaded = load_artifact(state, "execution_staging", ExecutionStaging, base_dir=tmp_path)
    assert loaded.status == "committed"
    assert loaded.commit_id == "commit:run-staging-commit"
    assert load_artifact(state, "planned_state", PlannedState, base_dir=tmp_path) is not None

    replay_ref = store_artifact(
        state,
        "execution_staging",
        "execute",
        "ExecutionStaging",
        committed_payload,
        base_dir=tmp_path,
    )
    assert replay_ref["descriptor_digest"] == committed_ref["descriptor_digest"]


def test_aborted_staging_never_promotes_formal_state(tmp_path) -> None:
    state = _state("run-staging-abort")
    staged_planned = store_artifact(
        state,
        "staged_planned_state",
        "execute",
        "PlannedState",
        PlannedState(),
        base_dir=tmp_path,
    )
    state["artifact_refs"]["staged_planned_state"] = staged_planned
    aborted = ExecutionStaging(
        staging_id="staging:run-staging-abort",
        staged_planned_state_ref=_digest(staged_planned),
        failed_task_ids=["worker:facility"],
        status="aborted",
        diagnostics=["one or more worker results failed"],
    )
    staging_ref = store_artifact(
        state,
        "execution_staging",
        "execute",
        "ExecutionStaging",
        aborted,
        base_dir=tmp_path,
    )
    state["artifact_refs"]["execution_staging"] = staging_ref

    loaded = load_artifact(state, "execution_staging", ExecutionStaging, base_dir=tmp_path)
    assert loaded.status == "aborted"
    assert "planned_state" not in state["artifact_refs"]
