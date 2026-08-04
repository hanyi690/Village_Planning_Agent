import json

import pytest

from app.modules.ports.artifact_store import ArtifactRef
from app.services.artifact_store import FilesystemArtifactStore


def _ref(run_id, module, aid, atype="L1Snapshot", rev="v1"):
    return ArtifactRef(
        context_version="cv-1",
        artifact_id=aid,
        module=module,
        run_id=run_id,
        artifact_type=atype,
        revision=rev,
    )


def test_store_and_retrieve(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    ref = _ref("run-1", "l1_observe", "l1-001")
    payload = {"facts": [], "artifact_id": "l1-001"}
    store.store(ref, payload)
    assert store.retrieve(ref) == payload


def test_retrieve_missing_raises(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        store.retrieve(_ref("run-1", "l1_observe", "nope"))


def test_list_by_run(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    for mod in ["l1_observe", "explore"]:
        store.store(_ref("run-1", mod, f"{mod}-001"), {"data": mod})
    refs = store.list_by_run("run-1")
    assert len(refs) == 2


def test_list_by_module(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    for rid in ["run-1", "run-2"]:
        store.store(_ref(rid, "l1_observe", f"l1-{rid}"), {})
    assert len(store.list_by_module("l1_observe")) == 2


def test_metadata_fidelity_roundtrip(tmp_path):
    """context_version / artifact_type / revision must survive list."""
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    store.store(_ref("run-1", "explore", "ev-1", atype="EvidenceBundle", rev="v3"), {})
    refs = store.list_by_run("run-1")
    assert len(refs) == 1
    r = refs[0]
    assert r.context_version == "cv-1"
    assert r.artifact_type == "EvidenceBundle"
    assert r.revision == "v3"


def test_revision_isolation(tmp_path):
    """Different revisions of the same artifact coexist and latest is listed."""
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    store.store(_ref("run-1", "l1_observe", "l1-001", rev="v1"), {"v": 1})
    store.store(_ref("run-1", "l1_observe", "l1-001", rev="v2"), {"v": 2})
    # retrieve specific revision
    assert store.retrieve(_ref("run-1", "l1_observe", "l1-001", rev="v1"))["v"] == 1
    assert store.retrieve(_ref("run-1", "l1_observe", "l1-001", rev="v2"))["v"] == 2
    # list returns latest
    refs = store.list_by_run("run-1")
    assert len(refs) == 1
    assert refs[0].revision == "v2"


def test_manifest_written(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    store.store(_ref("run-1", "l1_observe", "l1-001"), {"facts": []})
    manifest = store.read_manifest(_ref("run-1", "l1_observe", "l1-001"))
    assert manifest["artifact_type"] == "L1Snapshot"
    assert manifest["revision"] == "v1"
    assert "checksum" in manifest
    assert "payload_bytes" in manifest


def test_path_boundary_rejects_traversal(tmp_path):
    """Unsafe identifiers must be rejected, not silently escaped."""
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        store.store(_ref("run-1", "..", "evil"), {})
    with pytest.raises(ValueError):
        store.store(_ref("run-1", "l1_observe", "../evil"), {})
    with pytest.raises(ValueError):
        store.store(_ref("../../etc", "l1_observe", "x"), {})


def test_artifact_and_review_dirs_isolated(tmp_path):
    """Artifacts live under artifacts/; a review dir must not be listed as an artifact."""
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    store.store(_ref("run-1", "l1_observe", "l1-001"), {})
    # simulate a review package dir under the same run
    review_dir = tmp_path / "run-1" / "reviews" / "l1_observe" / "rev-1"
    review_dir.mkdir(parents=True)
    (review_dir / "manifest.json").write_text("{}", encoding="utf-8")
    refs = store.list_by_run("run-1")
    assert len(refs) == 1
    assert refs[0].artifact_id == "l1-001"
