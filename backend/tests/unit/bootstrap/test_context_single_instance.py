"""Post-L3 context single-instance tests.

Verifies the design point that all stages share one authoritative
``PlanningContext`` per session: ``build_planning_context`` with
``refresh=False`` returns the cached instance (identity-stable), a forced
refresh bumps the version, and the post-L3 ``_get_cached_context`` recovers the
cached context when the serialized ``state.context`` is stripped (checkpoint).
"""

import pytest


@pytest.fixture(autouse=True)
def _clear_context_cache():
    import app.services.context.planning_context as pc

    pc._context_cache.clear()
    pc._build_counter.clear()
    yield
    pc._context_cache.clear()
    pc._build_counter.clear()


def _patch_deps(monkeypatch):
    """Stub the heavy factory internals so build runs offline + fast."""
    import app.modules.kg.gazetteer as gazpkg
    import app.modules.kg.manager as km
    import app.modules.kg.queries.sparql as sparql
    import app.services.session_bundle as sb
    import app.services.session_kg as sk
    from app.modules.schema.types.canonical import VillageBundle

    def _fake_bundle(name, session_id):
        bundle = VillageBundle(village_name=name)
        bundle.metadata.session_id = session_id
        return bundle

    async def fake_bundle(_session_id, village_name=None):
        return _fake_bundle(village_name or "金田村", _session_id)

    async def fake_ensure(_session_id, _village_name):
        return {"cache_hit": True, "version": 1}

    class FakeManager:
        def get_session_kg(self, _session_id):
            return None

        def get_session_version(self, _session_id):
            return 1

    monkeypatch.setattr(sb, "build_session_bundle", fake_bundle)
    monkeypatch.setattr(sk, "ensure_session_kg", fake_ensure)
    monkeypatch.setattr(km, "get_kg_manager", lambda: FakeManager())
    monkeypatch.setattr(
        sparql, "query_kg", lambda _kg, _template_name, **_params: []
    )
    monkeypatch.setattr(gazpkg, "load_gazetteer", lambda _village: None)


@pytest.mark.asyncio
async def test_build_returns_same_instance(sqlite_db, pipeline_reset, monkeypatch):
    setup, teardown = sqlite_db
    await setup()
    try:
        _patch_deps(monkeypatch)
        from app.services.context.planning_context import build_planning_context

        a = await build_planning_context(
            "sess-c1", village_name="金田村", include_reports=False
        )
        b = await build_planning_context(
            "sess-c1", village_name="金田村", include_reports=False
        )
        assert a is b
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_refresh_bumps_version(sqlite_db, pipeline_reset, monkeypatch):
    setup, teardown = sqlite_db
    await setup()
    try:
        _patch_deps(monkeypatch)
        from app.services.context.planning_context import build_planning_context

        a = await build_planning_context(
            "sess-c1", village_name="金田村", include_reports=False
        )
        b = await build_planning_context(
            "sess-c1", village_name="金田村", include_reports=False, refresh=True
        )
        assert b.version == a.version + 1
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_resolve_context_rebuilds_from_cache(
    sqlite_db, pipeline_reset, monkeypatch
):
    setup, teardown = sqlite_db
    await setup()
    try:
        _patch_deps(monkeypatch)
        from app.agent.bootstrap.post_l3_main_nodes import _get_cached_context
        from app.services.context.planning_context import build_planning_context

        ctx = await build_planning_context(
            "sess-c1", village_name="金田村", include_reports=False
        )
        state = {"session_id": "sess-c1"}
        resolved = _get_cached_context(state)
        assert resolved is ctx
    finally:
        await teardown()


def test_resolve_context_empty_session_returns_none(pipeline_reset):
    from app.agent.bootstrap.post_l3_main_nodes import _get_cached_context

    resolved = _get_cached_context({"session_id": ""})
    assert resolved is None
