"""Tests for build_planning_context port wiring (kg -> gazetteer/spatial_query)."""

import pytest

from app.modules.ports.planning_ports import PlanningPorts


class _FakeKG:
    """Fake KG with a ``.g`` graph so the fresh gazetteer build runs."""

    def __init__(self):
        class _G:
            def subjects(self, *a, **k):
                return []

            def triples(self, *a, **k):
                return []

        self.g = _G()


@pytest.fixture(autouse=True)
def _clear_context_cache():
    import app.services.context.planning_context as pc

    pc._context_cache.clear()
    pc._build_counter.clear()
    yield
    pc._context_cache.clear()
    pc._build_counter.clear()


def _fake_bundle(name="金田村", session_id="sess-test"):
    from app.modules.schema.types.canonical import VillageBundle

    bundle = VillageBundle(village_name=name)
    bundle.metadata.session_id = session_id
    bundle.metadata.bundle_version = "1.0"
    return bundle


def _patch_deps(monkeypatch, kg, session="sess-test", village="金田村"):
    import app.services.session_bundle as sb
    import app.services.session_kg as sk
    import app.modules.kg.manager as km
    import app.modules.kg.queries.sparql as sparql

    async def fake_bundle(_session_id, village_name=None):
        return _fake_bundle(village_name or village, _session_id)

    async def fake_ensure(_session_id, _village_name):
        return {"cache_hit": True, "version": 1}

    class FakeManager:
        def get_session_kg(self, _session_id):
            return kg

        def get_session_version(self, _session_id):
            return 1

    monkeypatch.setattr(sb, "build_session_bundle", fake_bundle)
    monkeypatch.setattr(sk, "ensure_session_kg", fake_ensure)
    monkeypatch.setattr(km, "get_kg_manager", lambda: FakeManager())
    monkeypatch.setattr(
        sparql, "query_kg", lambda _kg, _template_name, **_params: []
    )


@pytest.mark.asyncio
async def test_ports_populated_when_kg_and_gazetteer_present(monkeypatch):
    from app.services.context.planning_context import build_planning_context

    _patch_deps(monkeypatch, kg=_FakeKG())

    context = await build_planning_context(
        "sess-test", village_name="金田村", include_reports=False
    )

    assert context.ports is not None
    assert context.ports.gazetteer is not None
    assert context.ports.spatial_query is not None
    assert callable(context.ports.spatial_query.resolve_candidates)
    assert callable(context.ports.gazetteer.resolve)


@pytest.mark.asyncio
async def test_ports_preserve_existing_fields(monkeypatch):
    from app.services.context.planning_context import build_planning_context

    _patch_deps(monkeypatch, kg=_FakeKG())

    context = await build_planning_context(
        "sess-test", village_name="金田村", include_reports=False
    )

    assert isinstance(context.ports, PlanningPorts)
    assert context.ports.gazetteer is not None
    assert context.ports.spatial_query is not None
    assert context.ports.artifact_store is None
    assert context.ports.context_provider is None
    assert context.ports.semantic_query is not None
    assert context.ports.nomenclature_registry is None


@pytest.mark.asyncio
async def test_ports_spatial_query_none_when_no_kg(monkeypatch):
    from app.services.context.planning_context import build_planning_context

    _patch_deps(monkeypatch, kg=None)

    context = await build_planning_context(
        "sess-test", village_name="金田村", include_reports=False
    )

    assert context.ports is not None
    assert context.ports.gazetteer is None
    assert context.ports.spatial_query is None


@pytest.mark.asyncio
async def test_ports_graceful_when_adapter_build_fails(monkeypatch):
    from app.services.context.planning_context import build_planning_context

    _patch_deps(monkeypatch, kg=_FakeKG())

    import app.modules.kg.adapters.spatial_query_adapter as sqa

    def _boom(_kg):
        raise RuntimeError("adapter build failed")

    monkeypatch.setattr(sqa, "KGSpatialQueryAdapter", _boom)

    context = await build_planning_context(
        "sess-test", village_name="金田村", include_reports=False
    )

    assert context.ports is not None
    assert context.ports.gazetteer is not None
    assert context.ports.spatial_query is None
