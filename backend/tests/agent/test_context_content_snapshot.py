"""P0-3: PlanningContext must be a content-addressed, capability-declared snapshot."""
import pytest

from app.modules.context.planning_context import PlanningContext


def test_context_has_content_hash_and_capabilities():
    ctx = PlanningContext(
        session_id="s1",
        village_name="v1",
        version=1,
        kg_session_ref="s1",
        kg_version=1,
    )
    assert isinstance(ctx.content_hash, str)
    assert len(ctx.content_hash) == 64
    assert ctx.capabilities == {
        "bundle": False,
        "kg": False,
        "gazetteer": False,
        "constraint_index": False,
        "reports": False,
    }


def test_contexts_with_different_content_have_different_hashes():
    ctx_a = PlanningContext(session_id="s1", village_name="v1", version=1, kg_session_ref="s1", kg_version=1)
    ctx_a._content_inputs = {"parcel_count": 10, "kg_version": 1}
    ctx_a._recompute_hash()
    ctx_b = PlanningContext(session_id="s1", village_name="v1", version=1, kg_session_ref="s1", kg_version=1)
    ctx_b._content_inputs = {"parcel_count": 20, "kg_version": 1}
    ctx_b._recompute_hash()
    assert ctx_a.content_hash != ctx_b.content_hash


@pytest.mark.asyncio
async def test_build_raises_when_bundle_missing(monkeypatch):
    from app.services.context import planning_context as factory

    async def boom_bundle(session_id, village_name=None):
        raise RuntimeError("bundle unavailable")

    monkeypatch.setattr("app.services.session_bundle.build_session_bundle", boom_bundle)
    with pytest.raises(factory.ContextBuildError, match="bundle"):
        await factory.build_planning_context("s1", "v1", include_reports=False)


@pytest.mark.asyncio
async def test_build_succeeds_without_kg_but_declares_it(monkeypatch):
    """KG is optional; when missing, capabilities must declare it."""
    from app.services.context import planning_context as factory
    from app.modules.schema.types.canonical import VillageBundle

    async def fake_bundle(session_id, village_name=None):
        b = VillageBundle(village_name=village_name or "v1")
        b.metadata.session_id = session_id
        return b

    async def fake_ensure(session_id, village_name):
        return None

    monkeypatch.setattr("app.services.session_bundle.build_session_bundle", fake_bundle)
    monkeypatch.setattr("app.services.session_kg.ensure_session_kg", fake_ensure)
    factory._context_cache.clear()
    factory._build_counter.clear()

    ctx = await factory.build_planning_context("s1-kgless", "v1", include_reports=False)
    assert ctx.capabilities["kg"] is False
    assert ctx.capabilities["bundle"] is True
    assert "kg" in ctx.required_capabilities_missing
