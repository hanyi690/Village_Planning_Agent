"""Step A: run the real main graph (L1/L2/L3) for the MVP fixture, record reports."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts.run_mvp_real_chain import (
    _RECORD_DIR, _build_uploads, _load_report_md, _load_session_config,
    _run_main_graph, _write_recorded_reports,
)


async def main() -> int:
    import app.database.models  # noqa: F401 — register all tables on SQLModel.metadata
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    cfg = _load_session_config()
    db_path = Path(tempfile.mkdtemp()) / "mvp-stepA.db"
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

    session_id = f"mvp-{cfg['village_name']}"
    from tests.fixtures.db import make_session_with_uploads

    await make_session_with_uploads(session_id=session_id, village_name=cfg["village_name"], uploads=_build_uploads())
    print(f"[stepA] session {session_id} created")

    try:
        await _run_main_graph(session_id, cfg)
        await _write_recorded_reports(session_id, _RECORD_DIR)
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
