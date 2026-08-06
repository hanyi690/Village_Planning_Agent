"""Isolate: L2 worker call with fake LLM, step-by-step timing (file-run)."""
import os
import sys
import time
import asyncio
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ["AMAP_EXTERNAL_ANCHOR_ENABLED"] = "false"
os.environ["BAIDU_EXTERNAL_ANCHOR_ENABLED"] = "false"
os.environ["TECENT_MAP_EXTERNAL_ANCHOR_ENABLED"] = "false"
os.environ["TIANDITU_WFS_ANCHOR_ENABLED"] = "false"

t0 = time.time()


def log(msg):
    print(f"[{round(time.time()-t0,1)}s] {msg}", flush=True)


async def main():
    import app.database.models  # noqa
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    log("imports done")
    db_path = Path(tempfile.mkdtemp()) / "t.db"
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
    log("create_all done")

    import app.modules.data.connections.base as cb
    import app.modules.kg.manager as km
    import app.services.bundle_store as bbs
    import app.services.session_bundle as sbb

    sbb._bundle_cache.clear()
    km.KGManager._instance = None
    bbs.BundleStore._instance = None
    cb.ConnectionRegistry._connections.clear()

    from scripts.run_mvp_real_chain import _build_uploads
    from tests.fixtures.db import make_session_with_uploads

    await make_session_with_uploads("mvp-l2e", "金田村", uploads=_build_uploads())
    log("session created")

    import app.agent.l2_strategize.worker as l2w
    import app.core.llm as lf
    import app.modules.rag.service as rmod

    class C:
        def __init__(self, *a, **k):
            self.content = "【INSTRUCTION】x"

        async def astream(self, p):
            yield type("X", (), {"content": "c"})()

        async def ainvoke(self, p):
            return self

        async def bind_tools(self, t):
            return self

    l2w._get_llm = lambda: C()
    lf.create_llm = lambda *a, **k: C()
    lf.create_flash_llm = lambda *a, **k: C()

    async def fg(s, *a, **k):
        return ["q"]

    async def fs(s, *a, **k):
        return []

    rmod.RagService.generate_queries = fg
    rmod.RagService.search = fs
    log("patched, calling L2...")
    try:
        out = await asyncio.wait_for(
            l2w.analyze_l2_dimension(
                {
                    "dimension_key": "resource_endowment",
                    "session_id": "mvp-l2e",
                    "config": {"village_name": "金田村"},
                    "is_revision": False,
                }
            ),
            timeout=40,
        )
        log(f"L2 OK completed={out.get('completed_dimensions')}")
    except asyncio.TimeoutError:
        log("L2 TIMEOUT 40s")
    except Exception as e:
        log(f"L2 ERR: {type(e).__name__}: {str(e)[:200]}")
    await engine.dispose()
    log("DONE")


if __name__ == "__main__":
    asyncio.run(main())
