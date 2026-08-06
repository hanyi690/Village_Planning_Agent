"""Controlled smoke: run the main-graph mechanical flow with a fake LLM.

Verifies DB init + session creation + graph trigger + layer aggregate
without consuming real API. Does NOT assert LLM output quality.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.run_mvp_real_chain import _build_uploads, _load_report_md, _load_session_config


class _FakeChunk:
    def __init__(self, text):
        self.content = text


class _FakeLLM:
    def __init__(self, *a, **k):
        self.content = "测试报告内容"
        self.tool_calls = []

    async def astream(self, prompt):
        for ch in ["测", "试", "报告"]:
            yield _FakeChunk(ch)

    async def ainvoke(self, prompt):
        return self

    async def bind_tools(self, tools):
        return self


async def main() -> int:
    import app.database.models  # noqa: F401 — register all tables on SQLModel.metadata
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    cfg = _load_session_config()
    db_path = Path(tempfile.mkdtemp()) / "mvp-smoke.db"
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

    # Monkeypatch LLM factory -> fake
    import app.agent.l1_observe.analysis_node as l1_node
    import app.agent.l2_strategize.worker as l2_worker
    import app.agent.l3_plan.worker as l3_worker
    import app.core.llm as llm_factory

    l1_node._get_llm = lambda: _FakeLLM()
    l2_worker._get_llm = lambda: _FakeLLM()
    l3_worker._get_llm = lambda: _FakeLLM()
    llm_factory.create_llm = lambda *a, **k: _FakeLLM()
    llm_factory.create_flash_llm = lambda *a, **k: _FakeLLM()

    session_id = f"mvp-{cfg['village_name']}"
    from tests.fixtures.db import make_session_with_uploads

    await make_session_with_uploads(session_id=session_id, village_name=cfg["village_name"], uploads=_build_uploads())
    print(f"[smoke] session {session_id} created")

    from app.services.runtime import PlanningRuntimeService

    await PlanningRuntimeService.ensure_initialized()
    initial_state = PlanningRuntimeService.build_initial_state(
        project_name=cfg["project_name"],
        village_data=_load_report_md(),
        village_name=cfg["village_name"],
        province=cfg["province"], city=cfg["city"], county=cfg["county"],
        township=cfg["township"], planning_period=cfg["planning_period"],
        task_description=cfg["task_description"], constraints=cfg["constraints"],
        session_id=session_id, stream_mode=False, step_mode=False,
        rag_enabled=True, rag_layer_config={1: True, 2: False, 3: True},
    )
    await PlanningRuntimeService._trigger_planning_execution(session_id, initial_state)
    state = await PlanningRuntimeService.aget_state_values(session_id)
    print(f"[smoke] phase={state.get('phase')}")
    print(f"[smoke] completed layer1={state.get('completed_dimensions', {}).get('layer1')}")
    print(f"[smoke] completed layer2={state.get('completed_dimensions', {}).get('layer2')}")
    print(f"[smoke] completed layer3={state.get('completed_dimensions', {}).get('layer3')}")
    print(f"[smoke] l1_snapshot_ref={state.get('l1_snapshot_ref')}")

    from app.services.report_store import ReportStore
    store = ReportStore.get_instance()
    for layer in (1, 2, 3):
        reps = await store.get_layer_reports_with_sources(session_id, layer) or {}
        print(f"[smoke] layer{layer} reports in DB: {len(reps)}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
