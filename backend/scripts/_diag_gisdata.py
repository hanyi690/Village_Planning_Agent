"""Temp: inspect gis_data keys + export_result exported_files for DELIVER gap."""
import asyncio
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "tests")


async def main():
    import scripts._diag_postl3 as d
    import app.database.engine as eng
    import app.database.models  # noqa: F401
    import tempfile
    from pathlib import Path
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import event
    from sqlmodel import SQLModel

    cfg = d._load_session_config()
    db_path = Path(tempfile.mkdtemp()) / "diag-export.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    eng.async_engine = engine
    eng.AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    import app.modules.data.connections.base as conn_base
    import app.modules.kg.manager as kg_man
    import app.services.bundle_store as bs
    import app.services.session_bundle as sb

    sb._bundle_cache.clear()
    kg_man.KGManager._instance = None
    bs.BundleStore._instance = None
    conn_base.ConnectionRegistry._connections.clear()

    import app.agent.l1_observe.analysis_node as l1_node
    import app.agent.l2_strategize.worker as l2_worker
    import app.agent.l3_plan.worker as l3_worker
    import app.core.llm as llm_factory
    import app.modules.rag.service as rag_service_mod

    l1_node._get_llm = lambda: d._FakeLLM()
    l2_worker._get_llm = lambda: d._FakeLLM()
    l3_worker._get_llm = lambda: d._FakeLLM()
    llm_factory.create_llm = lambda *a, **k: d._FakeLLM()
    llm_factory.create_flash_llm = lambda *a, **k: d._FakeLLM()

    import app.agent.parse.aggregate as parse_agg
    parse_agg.route_compilation = lambda result, diags: "merge"

    async def _fake_generate_queries(self, *a, **k):
        return ["测试查询"]

    async def _fake_search(self, *a, **k):
        return []

    rag_service_mod.RagService.generate_queries = _fake_generate_queries
    rag_service_mod.RagService.search = _fake_search

    session_id = "mvp-jintiancun"
    from tests.fixtures.db import make_session_with_uploads
    await make_session_with_uploads(session_id=session_id, village_name=cfg["village_name"], uploads=d._build_uploads())

    from app.services.context.planning_context import build_planning_context
    ctx = await build_planning_context(session_id, refresh=True)
    bundle = ctx.bundle

    print("== bundle polygon keys ==")
    print(sorted(bundle.polygons._layers.keys()))
    for k in sorted(bundle.polygons._layers.keys()):
        print(f"  {k}: {len(bundle.polygons.get(k))} feats")
    print("== boundary property ==")
    print("  boundary:", bundle.boundary is not None)

    gis_data = bundle.to_geojson_dict()
    print("== gis_data keys ==")
    for k in sorted(gis_data.keys()):
        if k.startswith("_"):
            continue
        fc = gis_data[k]
        n = len(fc.get("features", [])) if isinstance(fc, dict) else "?"
        print(f"  {k}: {n} feats")

    import os
    os._exit(0)


asyncio.run(main())
