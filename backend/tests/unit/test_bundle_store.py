"""Tests for BundleStore persistence + serialization roundtrip (DB mocked)."""

import pytest

from tests.unit.test_bundle_serialization import _build_sample_bundle


def _make_fake_store(monkeypatch, **overrides):
    """Return a BundleStore whose DB ops are replaced with async fakes.

    Also returns a ``state`` dict for asserting on captured calls.
    """
    from app.services import bundle_store

    state = {
        "created": [],
        "latest": overrides.get("latest", {"version": 0}),
        "versions": overrides.get("versions", [{"version": 1}, {"version": 2}]),
    }

    async def fake_create(payload):
        state["created"].append(dict(payload))
        return payload["version"]

    async def fake_get(session_id, version=None):
        rec = state["latest"]
        if not rec:
            return None
        if version is not None and rec.get("version") != version:
            return None
        return dict(rec)

    async def fake_list(session_id, limit=20):
        return list(state["versions"])[:limit]

    monkeypatch.setattr(
        "app.services.bundle_store.create_planning_bundle_async", fake_create
    )
    monkeypatch.setattr(
        "app.services.bundle_store.get_planning_bundle_async", fake_get
    )
    monkeypatch.setattr(
        "app.services.bundle_store.list_planning_bundle_versions_async", fake_list
    )

    return bundle_store.BundleStore(), state


# ── serialization ─────────────────────────────────────────────────────


def test_serialize_deserialize_roundtrip():
    from app.services.bundle_store import BundleStore

    bundle = _build_sample_bundle()
    blob = BundleStore.serialize(bundle)
    restored = BundleStore.deserialize(blob)

    assert restored.village_name == "金田村"
    assert restored.metadata.session_id == "sess-001"
    assert len(restored.polygons.get("landuse_current")) == 1
    assert restored.polygons.get("landuse_current")[0].bsm == "001"
    assert restored.layer_reports == bundle.layer_reports
    assert restored.documents.planning_texts == bundle.documents.planning_texts


# ── writes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_auto_increments_version(monkeypatch):
    store, state = _make_fake_store(monkeypatch, latest={"version": 2})
    bundle = _build_sample_bundle()

    version = await store.save("sess-001", bundle, trigger_reason="layer1")

    assert version == 3
    assert len(state["created"]) == 1
    payload = state["created"][0]
    assert payload["session_id"] == "sess-001"
    assert payload["version"] == 3
    assert payload["trigger_reason"] == "layer1"
    assert payload["bundle_json"]
    assert len(payload["sha256"]) == 64


@pytest.mark.asyncio
async def test_save_explicit_version(monkeypatch):
    store, state = _make_fake_store(monkeypatch, latest={"version": 9})

    version = await store.save("sess-001", _build_sample_bundle(), version=5)

    assert version == 5
    assert state["created"][0]["version"] == 5


@pytest.mark.asyncio
async def test_save_first_version(monkeypatch):
    store, state = _make_fake_store(monkeypatch, latest=None)

    version = await store.save("sess-001", _build_sample_bundle())

    assert version == 1
    assert state["created"][0]["version"] == 1


# ── reads ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_latest_and_version(monkeypatch):
    store, state = _make_fake_store(monkeypatch, latest={"version": 2, "bundle_json": "{}"})

    latest = await store.get_latest("sess-001")
    assert latest["version"] == 2

    v2 = await store.get_version("sess-001", 2)
    assert v2["version"] == 2

    v1 = await store.get_version("sess-001", 1)
    assert v1 is None


@pytest.mark.asyncio
async def test_list_versions(monkeypatch):
    store, _ = _make_fake_store(monkeypatch)

    versions = await store.list_versions("sess-001")
    assert [v["version"] for v in versions] == [1, 2]


@pytest.mark.asyncio
async def test_load_bundle_deserializes(monkeypatch):
    from app.services.bundle_store import BundleStore

    bundle = _build_sample_bundle()
    blob = BundleStore.serialize(bundle)
    store, _ = _make_fake_store(
        monkeypatch, latest={"version": 1, "bundle_json": blob}
    )

    restored = await store.load_bundle("sess-001")
    assert restored is not None
    assert restored.village_name == "金田村"
    assert restored.metadata.session_id == "sess-001"


@pytest.mark.asyncio
async def test_load_bundle_returns_none_when_missing(monkeypatch):
    store, _ = _make_fake_store(monkeypatch, latest=None)

    assert await store.load_bundle("sess-001") is None


@pytest.mark.asyncio
async def test_get_layer_reports_from_bundle(monkeypatch):
    from app.services.bundle_store import BundleStore

    bundle = _build_sample_bundle()
    blob = BundleStore.serialize(bundle)
    store, _ = _make_fake_store(
        monkeypatch, latest={"version": 1, "bundle_json": blob}
    )

    all_reports = await store.get_layer_reports_from_bundle("sess-001")
    assert set(all_reports.keys()) == {1, 3}

    layer1 = await store.get_layer_reports_from_bundle("sess-001", layer=1)
    assert set(layer1.keys()) == {1}
    assert layer1[1]["location"]["report_id"] == "r-1"


@pytest.mark.asyncio
async def test_get_layer_reports_empty_without_snapshot(monkeypatch):
    store, _ = _make_fake_store(monkeypatch, latest=None)

    assert await store.get_layer_reports_from_bundle("sess-001") == {}
