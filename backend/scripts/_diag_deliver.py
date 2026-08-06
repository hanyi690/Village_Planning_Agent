"""Temp: inspect deliver manifest blocking items."""
import asyncio
import sys

sys.path.insert(0, ".")


async def main():
    import scripts._diag_postl3 as d
    import app.database.engine as eng
    import app.database.models  # noqa: F401
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel
    import tempfile
    from pathlib import Path
    from sqlalchemy import event

    cfg = d._load_session_config()
    db_path = Path(tempfile.mkdtemp()) / "diag-graph.db"
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

    from app.modules.schema.contracts.l3_contracts import PlanningProgram
    program = PlanningProgram.model_validate_json(
        Path(d._BACKEND_DIR / ".run-tmp/mvp-jintiancun/artifacts/l3_plan/l3-mvp-jintiancun-v1/v1/payload.json").read_text(encoding="utf-8")
    )

    from app.agent.bootstrap import post_l3_main_nodes as n
    from app.services.artifact_store import FilesystemArtifactStore
    from app.services.runtime import PlanningRuntimeService
    await PlanningRuntimeService.ensure_initialized()
    FilesystemArtifactStore._instance = None

    base_state = {
        "session_id": session_id,
        "run_id": session_id,
        "context_version": "",
        "config": {"village_name": cfg["village_name"]},
        "planning_program": program,
        "retry_counts": {},
        "error_feedback": {},
        "upstream_gates": [],
        "layout_configs": [],
        "messages": [],
    }
    state = dict(base_state)
    out = await n.parse_node(state)
    state.update(out)
    out = await n.ground_node(state)
    state.update(out)
    out = await n.select_node(state)
    state.update(out)
    out = await n.execute_node(state)
    state.update(out)
    out = await n.validate_node(state)
    state.update(out)
    out = await n.reconcile_node(state)
    state.update(out)
    out = await n.deliver_node(state)
    man = out.get("delivery_manifest") or {}
    gate = out.get("deliver_gate") or {}
    print("deliver_gate route:", gate.get("feedback_route") if isinstance(gate, dict) else getattr(gate, "feedback_route", None))
    items = man.get("pending_human_items") or []
    print("pending_human_items:", len(items))
    for it in items:
        if isinstance(it, dict):
            print("  ", it.get("item_id"), "blocking=", it.get("blocking"), "reason=", it.get("reason"), "desc=", it.get("description"))
        else:
            print("  ", getattr(it, "item_id", "?"), "blocking=", getattr(it, "blocking", None), "reason=", getattr(it, "reason", None))
    print("delivery_gate dict:", json.dumps(gate, ensure_ascii=False)[:400] if isinstance(gate, dict) else "obj")
    man = out.get("delivery_manifest") or {}
    print("statutory_complete:", man.get("statutory_complete"))
    print("breakdown:", man.get("statutory_complete_breakdown"))
    dg = man.get("delivery_gate") or {}
    print("land_balance_closed:", dg.get("land_balance_closed"))
    print("three_line_violations:", dg.get("three_line_violations"))
    print("protected_intrusions:", dg.get("protected_intrusions"))
    print("zones_complete:", dg.get("zones_complete"))
    print("deliverables:", man.get("deliverables"))
    await engine.dispose()
    import os
    os._exit(0)


import json  # noqa: E402

asyncio.run(main())
