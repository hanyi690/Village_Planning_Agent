from app.infrastructure.artifacts.runtime import store_artifact


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
