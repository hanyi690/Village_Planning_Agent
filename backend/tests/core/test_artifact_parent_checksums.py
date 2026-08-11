from pathlib import Path
import shutil

from app.agent.bootstrap.artifact_runtime import store_artifact
from app.modules.ports.artifact_store import ArtifactRef
from app.services.artifact_store import FilesystemArtifactStore


def test_store_artifact_captures_and_persists_parent_checksums(monkeypatch):
    temp_root = Path(".pytest-task3-parent-checksums")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(temp_root))
    state = {
        "run_id": "run-1",
        "session_id": "session-1",
        "context_version": "ctx-1",
        "context_fingerprint": "fp-1",
        "artifact_refs": {
            "l1_snapshot": {
                "artifact_id": "l1-ref",
                "revision": "v1",
                "checksum": "l1-sum",
            },
            "l2_strategy": {
                "artifact_id": "l2-ref",
                "revision": "v2",
                "checksum": "l2-sum",
            },
            "planning_program": {
                "artifact_id": "old-l3-ref",
                "revision": "v7",
                "checksum": "old-l3-sum",
            },
        },
    }

    ref_data = store_artifact(
        state,
        "planning_program",
        "l3_plan",
        "PlanningProgram",
        {"steps": ["draft"]},
    )

    assert ref_data["parent_checksums"] == {
        "l1_snapshot": "v1:l1-sum",
        "l2_strategy": "v2:l2-sum",
    }
    assert "planning_program" not in ref_data["parent_checksums"]

    store = FilesystemArtifactStore(temp_root)
    manifest = store.read_manifest(ArtifactRef(**ref_data))
    assert manifest["parent_checksums"] == ref_data["parent_checksums"]

    listed = {
        ref.artifact_id: ref
        for ref in store.list_by_run("run-1")
    }
    assert listed[ref_data["artifact_id"]].parent_checksums == ref_data["parent_checksums"]
    shutil.rmtree(temp_root)
