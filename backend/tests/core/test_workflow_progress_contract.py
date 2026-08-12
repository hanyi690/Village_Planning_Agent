"""Contract tests for the bounded stage-local workflow carrier."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.schema.contracts.workflow_progress_contracts import WorkflowProgress
from app.workflow.runtime_adapter import materialize_workflow_state, pack_workflow_patch


def test_workflow_progress_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ValidationError):
        WorkflowProgress.model_validate({"unexpected_stage_field": "value"})


def test_workflow_progress_requires_explicit_stage_payload_for_dynamic_fields() -> None:
    progress = WorkflowProgress.model_validate(
        {"stage_payload": {"legacy_stage_field": {"value": 1}}}
    )

    assert progress.stage_payload == {"legacy_stage_field": {"value": 1}}
    assert "legacy_stage_field" not in progress.model_dump(mode="python")


def test_adapter_round_trip_keeps_dynamic_fields_in_carrier_and_restores_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    descriptor = {"descriptor_digest": "descriptor:workflow-progress"}

    def fake_store_artifact(
        state: dict[str, object],
        key: str,
        module: str,
        artifact_type: str,
        payload: object,
    ) -> dict[str, str]:
        captured["payload"] = payload
        return descriptor

    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.store_artifact",
        fake_store_artifact,
    )

    source_ref = {"descriptor_digest": "descriptor:source"}
    state = {
        "runtime": {
            "session_id": "run-1",
            "run_id": "run-1",
            "branch_id": "main",
            "artifact_refs": {"source": source_ref},
            "stage_local_value": {"count": 1},
        },
        "session_id": "run-1",
        "run_id": "run-1",
        "branch_id": "main",
        "artifact_refs": {"source": source_ref},
    }

    packed = pack_workflow_patch(state, {"stage_local_value": {"count": 2}})
    payload = WorkflowProgress.model_validate(captured["payload"])

    assert payload.stage_payload["stage_local_value"] == {"count": 2}
    assert "stage_local_value" not in payload.model_dump(mode="python")
    assert payload.artifact_refs == {"source": source_ref}
    assert packed["artifact_refs"]["workflow_progress"] == descriptor

    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda state, key, model: payload,
    )
    restored = materialize_workflow_state(
        {
            "session_id": "run-1",
            "run_id": "run-1",
            "branch_id": "main",
            "artifact_refs": {
                "source": source_ref,
                "workflow_progress": descriptor,
            },
        }
    )

    assert restored["stage_local_value"] == {"count": 2}
    assert restored["artifact_refs"]["workflow_progress"] == descriptor

