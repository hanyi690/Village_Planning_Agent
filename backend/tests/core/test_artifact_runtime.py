import pytest

from app.infrastructure.artifacts import ContentAddressedArtifactRepository
from app.infrastructure.artifacts.runtime import (
    ArtifactReplayError,
    load_artifact,
    store_artifact,
)


def test_store_artifact_adopts_identical_named_ref_after_interrupted_stage(tmp_path):
    state = {
        "run_id": "run-1",
        "session_id": "run-1",
        "branch_id": "branch-1",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "run-1", "version": "1"},
        "artifact_refs": {},
    }

    first = store_artifact(
        state,
        "execution_diagnostics",
        "execute",
        "ExecutionDiagnostics",
        {"status": "partial"},
        base_dir=tmp_path,
    )
    retry = store_artifact(
        state,
        "execution_diagnostics",
        "execute",
        "ExecutionDiagnostics",
        {"status": "partial"},
        base_dir=tmp_path,
    )

    assert retry["descriptor_digest"] == first["descriptor_digest"]


def test_store_artifact_rejects_null_payload(tmp_path):
    state = {
        "run_id": "run-null",
        "session_id": "run-null",
        "branch_id": "main",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "run-null", "version": "1"},
        "artifact_refs": {},
    }

    with pytest.raises(ArtifactReplayError, match="null payload"):
        store_artifact(
            state,
            "delivery_spatial_snapshot",
            "deliver",
            "DeliverySpatialSnapshot",
            None,
            base_dir=tmp_path,
        )


def test_load_artifact_rejects_a_persisted_null_payload(tmp_path):
    repository = ContentAddressedArtifactRepository(tmp_path)
    descriptor = repository.put_json(
        None,
        schema_id="DeliverySpatialSnapshot",
        schema_version="3",
        producer_stage="deliver",
        run_id="run-null-load",
        branch_id="main",
    )
    state = {
        "run_id": "run-null-load",
        "session_id": "run-null-load",
        "branch_id": "main",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "run-null-load", "version": "1"},
        "artifact_refs": {"delivery_spatial_snapshot": descriptor.model_dump(mode="json")},
    }

    with pytest.raises(ArtifactReplayError, match="null payload"):
        load_artifact(state, "delivery_spatial_snapshot", base_dir=tmp_path)
