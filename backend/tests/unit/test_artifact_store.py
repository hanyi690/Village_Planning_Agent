from app.services.artifact_store import FilesystemArtifactStore
from app.modules.ports.artifact_store import ArtifactRef


def _ref(run_id, module, aid, atype="L1Snapshot"):
    return ArtifactRef(context_version="v1", artifact_id=aid, module=module, run_id=run_id, artifact_type=atype)


def test_store_and_retrieve(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    ref = _ref("run-1", "l1_observe", "l1-001")
    payload = {"facts": [], "artifact_id": "l1-001"}
    store.store(ref, payload)
    assert store.retrieve(ref) == payload


def test_retrieve_missing_raises(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    try:
        store.retrieve(_ref("run-1", "l1_observe", "nope"))
        assert False, "should raise"
    except FileNotFoundError:
        pass


def test_list_by_run(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    for mod in ["l1_observe", "explore"]:
        store.store(_ref("run-1", mod, f"{mod}-001"), {"data": mod})
    assert len(store.list_by_run("run-1")) == 2


def test_list_by_module(tmp_path):
    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    for rid in ["run-1", "run-2"]:
        store.store(_ref(rid, "l1_observe", f"l1-{rid}"), {})
    assert len(store.list_by_module("l1_observe")) == 2
