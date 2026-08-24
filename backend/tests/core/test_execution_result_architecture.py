from pathlib import Path

from app.contracts.artifacts import ArtifactRef
from app.contracts.workflow.execution_plan_contracts import (
    ExecutionResult,
    TaskExecutionResult,
)
from app.workflow.stage_adapter import _KEY_BY_TYPE
from app.infrastructure.artifacts.runtime import ARTIFACT_KEYS


ROOT = Path(__file__).resolve().parents[2] / "app"


def _ref(schema_id: str) -> ArtifactRef:
    return ArtifactRef(
        digest="sha256:" + "a" * 64,
        descriptor_digest="sha256:" + "b" * 64,
        size_bytes=1,
        schema_id=schema_id,
        schema_version="3",
        semantic_digest="sha256:" + "c" * 64,
        producer_stage="execute",
        run_id="run-1",
        branch_id="main",
    )


def test_execute_has_one_root_artifact_contract() -> None:
    result = ExecutionResult(
        approved_input_ref=_ref("ApprovedExecutionInput"),
        execution_plan_ref=_ref("ExecutionPlan"),
        parcel_changeset_ref=_ref("ParcelChangeSet"),
        planned_state_ref=_ref("PlannedState"),
        layout_configs_ref=_ref("LayoutConfigs"),
        atomic_commit_id="commit:execution-result",
        atomic_commit_status="committed",
        task_results=[TaskExecutionResult(task_id="task-1", status="succeeded")],
    )

    assert result.parcel_changeset_ref.descriptor_digest == "sha256:" + "b" * 64
    assert result.task_results[0].task_id == "task-1"
    assert _KEY_BY_TYPE["ExecutionResult"] == "execution_result"
    assert "execution_result" in ARTIFACT_KEYS
    assert "execution_outcome" not in ARTIFACT_KEYS


def test_downstream_stages_load_execution_result_root() -> None:
    source = "\n".join(
        (ROOT / "workflow" / "stages" / name).read_text(encoding="utf-8")
        for name in ("validate.py", "reconcile.py", "deliver.py")
    )

    assert '"execution_result"' in source
    assert '"execution_outcome"' not in source
