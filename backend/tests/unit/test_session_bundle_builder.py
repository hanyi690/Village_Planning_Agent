"""Tests for session-level VillageBundle building + caching."""

import pytest


@pytest.fixture(autouse=True)
def _clear_bundle_cache():
    import app.services.session_bundle as sb

    sb._bundle_cache.clear()
    yield
    sb._bundle_cache.clear()


def _make_bundle(name="金田村", session_id="sess-001"):
    from app.modules.schema.types.canonical import VillageBundle

    bundle = VillageBundle(village_name=name)
    bundle.metadata.session_id = session_id
    bundle.metadata.bundle_version = "1.0"
    return bundle


@pytest.mark.asyncio
async def test_build_with_village_name_override(monkeypatch):
    import app.services.session_bundle as sb

    created = []

    class FakeCatalog:
        def __init__(self):
            pass

        async def load_village_bundle_async(self, village_name, session_id=None, layer_types=None):
            created.append((village_name, session_id))
            return _make_bundle(village_name, session_id)

    monkeypatch.setattr("app.modules.data.catalog.DataCatalog", FakeCatalog)

    bundle = await sb.build_session_bundle("sess-001", village_name="金田村")
    assert bundle.village_name == "金田村"
    assert bundle.metadata.session_id == "sess-001"
    assert created == [("金田村", "sess-001")]


@pytest.mark.asyncio
async def test_build_resolves_village_name_from_session(monkeypatch):
    import app.services.session_bundle as sb

    async def fake_get_session(session_id):
        return {"session_id": session_id, "village_name": "云浮村"}

    monkeypatch.setattr(
        "app.database.operations.get_planning_session_async", fake_get_session
    )

    class FakeCatalog:
        def __init__(self):
            pass

        async def load_village_bundle_async(self, village_name, session_id=None, layer_types=None):
            return _make_bundle(village_name, session_id)

    monkeypatch.setattr("app.modules.data.catalog.DataCatalog", FakeCatalog)

    bundle = await sb.build_session_bundle("sess-001")
    assert bundle.village_name == "云浮村"


@pytest.mark.asyncio
async def test_cached_bundle_returned_on_second_call(monkeypatch):
    import app.services.session_bundle as sb

    calls = []

    class FakeCatalog:
        def __init__(self):
            pass

        async def load_village_bundle_async(self, village_name, session_id=None, layer_types=None):
            calls.append(session_id)
            return _make_bundle(village_name, session_id)

    monkeypatch.setattr("app.modules.data.catalog.DataCatalog", FakeCatalog)

    first = await sb.build_session_bundle("sess-001", village_name="金田村")
    second = await sb.build_session_bundle("sess-001", village_name="金田村")
    assert first is second
    assert len(calls) == 1
    assert sb.get_cached_bundle("sess-001") is first


@pytest.mark.asyncio
async def test_refresh_rebuilds_bundle(monkeypatch):
    import app.services.session_bundle as sb

    calls = []

    class FakeCatalog:
        def __init__(self):
            pass

        async def load_village_bundle_async(self, village_name, session_id=None, layer_types=None):
            calls.append(session_id)
            return _make_bundle(village_name, session_id)

    monkeypatch.setattr("app.modules.data.catalog.DataCatalog", FakeCatalog)

    first = await sb.build_session_bundle("sess-001", village_name="金田村")
    second = await sb.build_session_bundle("sess-001", village_name="金田村", refresh=True)
    assert first is not second
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_invalidate_session_bundle(monkeypatch):
    import app.services.session_bundle as sb

    class FakeCatalog:
        def __init__(self):
            pass

        async def load_village_bundle_async(self, village_name, session_id=None, layer_types=None):
            return _make_bundle(village_name, session_id)

    monkeypatch.setattr("app.modules.data.catalog.DataCatalog", FakeCatalog)

    first = await sb.build_session_bundle("sess-001", village_name="金田村")
    sb.invalidate_session_bundle("sess-001")
    assert sb.get_cached_bundle("sess-001") is None
    second = await sb.build_session_bundle("sess-001", village_name="金田村")
    assert first is not second


@pytest.mark.asyncio
async def test_empty_bundle_when_no_village_resolved(monkeypatch):
    import app.services.session_bundle as sb

    async def fake_get_session(session_id):
        return None

    monkeypatch.setattr(
        "app.database.operations.get_planning_session_async", fake_get_session
    )

    bundle = await sb.build_session_bundle("missing")
    assert bundle.village_name == ""


@pytest.mark.asyncio
async def test_resolve_village_name(monkeypatch):
    from app.services.session_bundle import _resolve_village_name

    async def fake_get_session(session_id):
        return {"session_id": session_id, "village_name": "石村", "project_name": "某项目"}

    monkeypatch.setattr(
        "app.database.operations.get_planning_session_async", fake_get_session
    )

    assert await _resolve_village_name("sess-001") == "石村"

    async def fake_none(session_id):
        return None

    monkeypatch.setattr(
        "app.database.operations.get_planning_session_async", fake_none
    )
    assert await _resolve_village_name("missing") == ""


# ── snapshot_session_bundle ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_builds_and_saves(monkeypatch):
    import app.services.session_bundle as sb

    built = _make_bundle("金田村", "sess-001")
    saved = []

    class FakeStore:
        async def save(self, session_id, bundle, version=None, trigger_reason=None):
            saved.append((session_id, bundle, version, trigger_reason))
            return 1

    async def fake_build(session_id, refresh=False):
        assert refresh is True
        return built

    monkeypatch.setattr(sb, "build_session_bundle", fake_build)
    monkeypatch.setattr("app.services.bundle_store.BundleStore.get_instance", lambda: FakeStore())

    result = await sb.snapshot_session_bundle("sess-001", trigger_reason="layer1")

    assert result is built
    assert saved == [("sess-001", built, None, "layer1")]


@pytest.mark.asyncio
async def test_snapshot_empty_session_returns_none(monkeypatch):
    import app.services.session_bundle as sb

    assert await sb.snapshot_session_bundle("") is None


@pytest.mark.asyncio
async def test_snapshot_build_failure_returns_none(monkeypatch):
    import app.services.session_bundle as sb

    async def fake_build(session_id, refresh=False):
        raise RuntimeError("catalog down")

    monkeypatch.setattr(sb, "build_session_bundle", fake_build)

    result = await sb.snapshot_session_bundle("sess-001", trigger_reason="layer1")
    assert result is None


@pytest.mark.asyncio
async def test_snapshot_save_failure_returns_bundle(monkeypatch):
    import app.services.session_bundle as sb

    built = _make_bundle("金田村", "sess-001")

    class FakeStore:
        async def save(self, session_id, bundle, version=None, trigger_reason=None):
            raise RuntimeError("db down")

    async def fake_build(session_id, refresh=False):
        return built

    monkeypatch.setattr(sb, "build_session_bundle", fake_build)
    monkeypatch.setattr("app.services.bundle_store.BundleStore.get_instance", lambda: FakeStore())

    result = await sb.snapshot_session_bundle("sess-001", trigger_reason="final")

    assert result is built
