from pathlib import Path

from app.modules.schema.contracts.execution_plan_contracts import (
    ExecutionResult,
    TaskExecutionResult,
)
from app.workflow.stage_adapter import _KEY_BY_TYPE
from app.infrastructure.artifacts.runtime import ARTIFACT_KEYS


ROOT = Path(__file__).resolve().parents[2] / "app"


def test_execute_has_one_root_artifact_contract() -> None:
    result = ExecutionResult(
        execution_plan_ref={"descriptor_digest": "plan"},
        parcel_changeset_ref={"descriptor_digest": "changes"},
        planned_state_ref={"descriptor_digest": "planned"},
        task_results=[TaskExecutionResult(task_id="task-1", status="succeeded")],
    )

    assert result.parcel_changeset_ref["descriptor_digest"] == "changes"
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
