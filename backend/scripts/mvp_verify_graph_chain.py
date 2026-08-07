"""Verify the refactored main graph (L1/L2/L3 -> post-L3 nodes) advances end to end.

Uses fake LLMs (no API cost) + disabled RAG to confirm the NEW main-graph
topology: after L3 gate PASS, advance_phase routes to parse -> ground ->
select -> execute -> validate -> reconcile -> deliver, instead of the old
gis_agent black box.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import os

# MVP 验证环境：禁用外部地图 POI/WFS 实时注入（设计文档：MVP 不承诺生产级外部地图实时搜索）。
os.environ.setdefault("AMAP_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("BAIDU_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("TECENT_MAP_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("TIANDITU_WFS_ANCHOR_ENABLED", "false")

from scripts.run_mvp_real_chain import _build_uploads, _load_report_md, _load_session_config


class _FakeChunk:
    def __init__(self, text):
        self.content = text


class _FakeLLM:
    def __init__(self, *a, **k):
        self.content = (
            "## 建设项目规划\n"
            "- 新建金田村文化活动中心，位于村中心，用地约 0.5 公顷。\n"
            "## 公共服务设施规划\n"
            "- 新建卫生站 1 处，位于园寨村。\n"
            "## 道路交通规划\n"
            "- 新建村内道路，连接文化活动中心与卫生站。\n"
            "## 用地布局\n"
            "- 居住用地约 30 公顷，产业用地约 20 公顷。\n"
            "【INSTRUCTION】\n"
            "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
            "|---|---|---|---|---|\n"
            "| 项目 | 文化活动中心 | 北部 | 新建文化活动中心 | 0.5 公顷 |\n"
            "| 设施 | 卫生站 | 南部 | 新建卫生站 | 200 平方米 |\n"
            "| 道路 | 连接道路 | 东部 | 新建村内道路 | 500 米 |\n"
            "| 功能分区 | 居住用地 | 西部 | 居住用地 | 30 公顷 |\n"
        )

    async def astream(self, prompt):
        for i in range(0, len(self.content), 20):
            yield _FakeChunk(self.content[i:i + 20])

    async def ainvoke(self, prompt):
        return self

    async def bind_tools(self, tools):
        return self


async def main() -> int:
    import shutil

    shutil.rmtree(".run-tmp", ignore_errors=True)

    # Clean global checkpoint DB (SqliteSaver persists across runs for fixed session_id)
    import sqlite3

    try:
        from app.database.engine import get_db_path as _cp_db_path
        _cp_conn = sqlite3.connect(str(_cp_db_path()))
        _cp_cur = _cp_conn.cursor()
        _cp_cur.execute("DELETE FROM checkpoints WHERE thread_id LIKE '%mvp%'")
        _cp_cur.execute("DELETE FROM writes WHERE thread_id LIKE '%mvp%'")
        _cp_conn.commit()
        _cp_conn.close()
        print("[verify] cleaned checkpoint DB", flush=True)
    except Exception as e:
        print(f"[verify] checkpoint clean skipped: {e}", flush=True)

    import app.database.models  # noqa: F401
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    cfg = _load_session_config()
    db_path = Path(tempfile.mkdtemp()) / "mvp-graph.db"
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

    # Fake LLMs for L1/L2/L3 workers + conversation + flash.
    import app.agent.l1_observe.analysis_node as l1_node
    import app.agent.l2_strategize.worker as l2_worker
    import app.agent.l3_plan.worker as l3_worker
    import app.core.llm as llm_factory
    import app.modules.rag.service as rag_service_mod

    l1_node._get_llm = lambda: _FakeLLM()
    l2_worker._get_llm = lambda: _FakeLLM()
    l3_worker._get_llm = lambda: _FakeLLM()
    llm_factory.create_llm = lambda *a, **k: _FakeLLM()
    llm_factory.create_flash_llm = lambda *a, **k: _FakeLLM()

    # Patch route_compilation to skip llm_patch route (fake LLM can't generate patches)
    import app.agent.parse.aggregate as parse_agg

    parse_agg.route_compilation = lambda result, diags: "merge"

    # RAG: disable to avoid flash-LLM singleon + vector store waits.
    async def _fake_generate_queries(self, *a, **k):
        return ["测试查询"]

    async def _fake_search(self, *a, **k):
        return []

    rag_service_mod.RagService.generate_queries = _fake_generate_queries
    rag_service_mod.RagService.search = _fake_search

    session_id = "mvp-jintiancun"
    from tests.fixtures.db import make_session_with_uploads

    await make_session_with_uploads(session_id=session_id, village_name=cfg["village_name"], uploads=_build_uploads())
    print(f"[verify] session {session_id} created", flush=True)

    from app.services.runtime import PlanningRuntimeService
    from app.agent.plan_state.state_factory import StateFactory

    await PlanningRuntimeService.ensure_initialized()
    initial_state = StateFactory.create(
        project_name=cfg["project_name"],
        village_data=_load_report_md(),
        village_name=cfg["village_name"],
        province=cfg["province"], city=cfg["city"], county=cfg["county"],
        township=cfg["township"], planning_period=cfg["planning_period"],
        task_description=cfg["task_description"], constraints=cfg["constraints"],
        session_id=session_id, stream_mode=False, step_mode=False,
        rag_enabled=False, rag_layer_config={1: False, 2: False, 3: False},
    )
    try:
        await asyncio.wait_for(
            PlanningRuntimeService._trigger_planning_execution(session_id, initial_state),
            timeout=300,
        )
    except asyncio.TimeoutError:
        print("[verify] TIMEOUT after 300s - printing state snapshot", flush=True)
        snap = await PlanningRuntimeService.aget_state_values(session_id)
        print(f"[verify] TIMEOUT phase={snap.get('phase')}", flush=True)
        print(f"[verify] TIMEOUT completed={snap.get('completed_dimensions')}", flush=True)
        _lg = snap.get('l1_gate_decision')
        print(f"[verify] TIMEOUT l1_gate={_lg.get('feedback_route') if isinstance(_lg, dict) else None}", flush=True)
        _lg2 = snap.get('l2_gate_decision')
        print(f"[verify] TIMEOUT l2_gate={_lg2.get('feedback_route') if isinstance(_lg2, dict) else None}", flush=True)
        _lg3 = snap.get('l3_gate_decision')
        print(f"[verify] TIMEOUT l3_gate={_lg3.get('feedback_route') if isinstance(_lg3, dict) else None}", flush=True)
        _pg = snap.get('parse_gate')
        print(f"[verify] TIMEOUT parse_gate={_pg.get('feedback_route') if isinstance(_pg, dict) else None}", flush=True)
    state = await PlanningRuntimeService.aget_state_values(session_id)
    print(f"[verify] phase={state.get('phase')}", flush=True)
    print(f"[verify] completed layer1={state.get('completed_dimensions', {}).get('layer1')}", flush=True)
    print(f"[verify] completed layer2={state.get('completed_dimensions', {}).get('layer2')}", flush=True)
    print(f"[verify] completed layer3={state.get('completed_dimensions', {}).get('layer3')}", flush=True)
    print(f"[verify] l3_gate_decision={state.get('l3_gate_decision')}", flush=True)

    # post-L3 chain state
    from app.services.artifact_store import FilesystemArtifactStore

    store = FilesystemArtifactStore(base_dir=str(Path(__file__).resolve().parent.parent / ".run-tmp"))
    refs = store.list_by_run(session_id)
    print(f"[verify] artifacts={[r.artifact_type for r in refs]}", flush=True)
    print(f"[verify] delivery_manifest present={state.get('delivery_manifest') is not None}", flush=True)
    print(f"[verify] validation_report present={state.get('validation_report') is not None}", flush=True)
    print(f"[verify] reconciliation_report present={state.get('reconciliation_report') is not None}", flush=True)
    print(f"[verify] human_review_status={state.get('post_l3_status')} pending={len(state.get('post_l3_pending_review') or [])}", flush=True)

    await engine.dispose()
    import os as _os
    _os._exit(0)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
