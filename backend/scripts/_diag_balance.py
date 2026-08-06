"""Temp: verify land_balance closure with real current + planned parcels."""
import asyncio
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")


async def main():
    import scripts._diag_postl3 as d
    from scripts.run_mvp_real_chain import _build_uploads, _load_session_config
    from tests.fixtures.db import make_session_with_uploads
    import app.database.engine as eng
    import app.database.models  # noqa: F401
    import tempfile
    from pathlib import Path
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import event
    from sqlmodel import SQLModel

    cfg = _load_session_config()
    dbp = Path(tempfile.mkdtemp()) / "t.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{dbp}")
    event.listens_for(engine.sync_engine, "connect")(
        lambda c, r: (c.cursor().execute("PRAGMA foreign_keys=ON"), c.cursor().close())
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    eng.async_engine = engine
    eng.AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    import app.modules.data.connections.base as cb
    import app.modules.kg.manager as km
    import app.services.bundle_store as bs
    import app.services.session_bundle as sb

    sb._bundle_cache.clear()
    km.KGManager._instance = None
    bs.BundleStore._instance = None
    cb.ConnectionRegistry._connections.clear()

    import app.agent.l1_observe.analysis_node as l1
    import app.agent.l2_strategize.worker as l2
    import app.agent.l3_plan.worker as l3
    import app.core.llm as llmf
    import app.modules.rag.service as rs

    l1._get_llm = lambda: d._FakeLLM()
    l2._get_llm = lambda: d._FakeLLM()
    l3._get_llm = lambda: d._FakeLLM()
    llmf.create_llm = lambda *a, **k: d._FakeLLM()
    llmf.create_flash_llm = lambda *a, **k: d._FakeLLM()

    import app.agent.parse.aggregate as pa
    pa.route_compilation = lambda r, di: "merge"
    rs.RagService.generate_queries = lambda self, *a, **k: ["x"]
    rs.RagService.search = lambda self, *a, **k: []

    await make_session_with_uploads(
        session_id="mvp-jintiancun", village_name=cfg["village_name"], uploads=_build_uploads()
    )
    from app.services.context.planning_context import build_planning_context

    ctx = await build_planning_context("mvp-jintiancun", refresh=True)
    current = list(ctx.bundle.polygons.get("landuse_current") or [])
    print("current count:", len(current))

    from app.modules.spatial_ops.land_balance import compute_land_balance
    from app.agent.deliver.aggregate import _build_planned_view

    planned_view = _build_planned_view(current, None)
    print("planned_view count:", len(planned_view))
    bal = compute_land_balance(current, planned_view)
    print("current_total:", bal.total_current_area_ha)
    print("planned_total:", bal.total_planned_area_ha)
    print("dev:", bal.closure_deviation_pct)
    print("is_closed:", bal.is_closed)
    import os
    os._exit(0)


asyncio.run(main())
