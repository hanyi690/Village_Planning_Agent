"""MVP real vertical chain driver - runs the full real-LLM pipeline end to end.

Mode control (env var RUN_REAL_LLM):
  - "record" (default when RUN_REAL_LLM=record): runs real LLM through the
    full main graph (L1/L2/L3) + post-L3 chain, records the L1/L2/L3 reports
    and the LLM-direction metadata hash to tests/fixtures/mvp_village/llm_recordings/.
  - "replay": restores the recorded reports into the DB, runs only the
    post-L3 chain (PARSE -> GROUND -> SELECT -> EXECUTE -> VALIDATE ->
    RECONCILE -> DELIVER) plus a verification of the 12 typed artifacts.
  - "real" (RUN_REAL_LLM=1): runs real LLM but does NOT write recordings
    (developer-local validation).

Usage:
  cd backend
  python scripts/run_mvp_real_chain.py --mode record
  python scripts/run_mvp_real_chain.py --mode replay
  python scripts/run_mvp_real_chain.py --mode real
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# MVP 验证环境：禁用外部地图 POI/WFS 实时注入（设计文档：MVP 不承诺生产级外部地图实时搜索）。
os.environ.setdefault("AMAP_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("BAIDU_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("TECENT_MAP_EXTERNAL_ANCHOR_ENABLED", "false")
os.environ.setdefault("TIANDITU_WFS_ANCHOR_ENABLED", "false")

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_FIXTURE_DIR = _BACKEND_DIR / "tests" / "fixtures" / "mvp_village"
_RECORD_DIR = _FIXTURE_DIR / "llm_recordings"

# 12 typed artifacts that must all be produced by the vertical chain.
_REQUIRED_ARTIFACTS = (
    "L1Snapshot", "L2Strategy", "PlanningProgram", "IntentCompilationResult",
    "GroundingResult", "SiteSelectionDecision", "ExecutionPlan",
    "ParcelChangeSet", "PlannedState", "ValidationReport",
    "ReconciliationReport", "DeliveryManifest",
)

# filename -> gis_data_type (must match session_routes.py upload inference)
_FILENAME_TYPE = [
    ("boundary.geojson", "boundary"),
    ("admin_boundary_line.geojson", "admin_boundary_line"),
    ("landuse.geojson", "landuse_current"),
    ("road.geojson", "road"),
    ("annotation.geojson", "annotation"),
    ("construction_zone.geojson", "construction_zone"),
    ("farmland_protection.geojson", "farmland_protection"),
    ("ecological_protection.geojson", "ecological_protection"),
    ("historical_protection.geojson", "historical_protection"),
    ("geological_hazard_points.geojson", "geological_hazard_points"),
]


def _load_session_config() -> dict:
    cfg_path = _FIXTURE_DIR / "session_config.json"
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _load_report_md() -> str:
    md_path = _FIXTURE_DIR / "current_report.md"
    return md_path.read_text(encoding="utf-8-sig")


def _build_uploads() -> list[dict]:
    uploads = []
    for fname, dtype in _FILENAME_TYPE:
        path = _FIXTURE_DIR / "gis" / fname
        geojson = json.loads(path.read_text(encoding="utf-8-sig"))
        uploads.append({
            "file_category": "gis_data",
            "filename": fname,
            "file_type": "geojson",
            "gis_data_type": dtype,
            "gis_data": geojson,
        })
    uploads.append({
        "file_category": "village_data",
        "filename": "current_report.md",
        "file_type": "md",
        "parsed_text": _load_report_md(),
    })
    return uploads


def _prompt_hashes() -> dict:
    """Hash the L1/L2/L3 prompt templates + compiler profiles."""
    import hashlib

    def _hash_dir(rel) -> str:
        base = _BACKEND_DIR / rel
        h = hashlib.sha256()
        if base.exists():
            for p in sorted(base.rglob("*.py")):
                h.update(p.read_bytes())
        return h.hexdigest()

    return {
        "l1_prompts": _hash_dir("app/modules/prompts/analysis"),
        "l2_prompts": _hash_dir("app/modules/prompts/concept"),
        "l3_prompts": _hash_dir("app/modules/prompts/detailed"),
        "l1_profile": _hash_dir("app/modules/parsing/compiler/profiles"),
        "llm_model": os.getenv("LLM_MODEL", "qwen3.7-plus"),
    }


async def _create_session(sqlite_db, pipeline_reset) -> str:
    setup, teardown = sqlite_db
    await setup()
    pipeline_reset.__wrapped__() if hasattr(pipeline_reset, "__wrapped__") else None

    from tests.fixtures.db import make_session_with_uploads

    cfg = _load_session_config()
    sid = f"mvp-{cfg['village_name']}"
    await make_session_with_uploads(
        session_id=sid,
        village_name=cfg["village_name"],
        uploads=_build_uploads(),
    )
    return sid, teardown


async def _write_recorded_reports(session_id: str, dest: Path) -> None:
    """Dump all DimensionReport rows to dest/reports.json + metadata."""
    from app.services.report_store import ReportStore

    store = ReportStore.get_instance()
    all_reports = {}
    for layer in (1, 2, 3):
        reports = await store.get_layer_reports_with_sources(session_id, layer) or {}
        for dk, rec in reports.items():
            all_reports[f"L{layer}:{dk}"] = {
                "content": rec.get("content", ""),
                "summary": rec.get("summary", ""),
                "instruction": rec.get("instruction", ""),
            }
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "reports.json").write_text(
        json.dumps(all_reports, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (dest / "llm_meta.json").write_text(
        json.dumps(_prompt_hashes(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[mvp] recorded {len(all_reports)} reports -> {dest}")


async def _restore_recorded_reports(session_id: str, src: Path) -> int:
    """Load recorded reports into the DB (skip LLM)."""
    if not (src / "reports.json").exists():
        raise FileNotFoundError(
            f"No recorded reports at {src}. Run 'python scripts/run_mvp_real_chain.py --mode record' first."
        )
    # Verify LLM-direction metadata before replay.
    current = _prompt_hashes()
    saved = json.loads((src / "llm_meta.json").read_text(encoding="utf-8"))
    if current != saved:
        raise RuntimeError(
            "LLM 方向已变更（prompt 模板 hash / LLM model / compiler profile 版本不匹配）。"
            "请运行 'python scripts/run_mvp_real_chain.py --mode record' 重新录制。"
        )
    from app.services.report_store import ReportStore

    store = ReportStore.get_instance()
    reports = json.loads((src / "reports.json").read_text(encoding="utf-8"))
    count = 0
    for key, rec in reports.items():
        layer_str, _, dk = key.partition(":")
        layer = int(layer_str[1:])
        latest = await store.get_latest_version(session_id, dk)
        await store.save(
            session_id,
            dk,
            latest + 1,
            rec.get("content", ""),
            layer=layer,
            metadata={"replay": True},
        )
        count += 1
    print(f"[mvp] restored {count} recorded reports -> DB")
    return count


async def _run_main_graph(session_id: str, cfg: dict) -> None:
    """Run the real main graph (L1/L2/L3) through PlanningRuntimeService."""
    from app.services.runtime import PlanningRuntimeService
    from app.agent.plan_state.state_factory import StateFactory

    await PlanningRuntimeService.ensure_initialized()
    initial_state = StateFactory.create(
        project_name=cfg["project_name"],
        village_data=_load_report_md(),
        village_name=cfg["village_name"],
        province=cfg["province"],
        city=cfg["city"],
        county=cfg["county"],
        township=cfg["township"],
        planning_period=cfg["planning_period"],
        task_description=cfg["task_description"],
        constraints=cfg["constraints"],
        session_id=session_id,
        stream_mode=False,
        step_mode=False,
        rag_enabled=True,
        rag_layer_config={1: True, 2: False, 3: True},
    )
    await PlanningRuntimeService._trigger_planning_execution(session_id, initial_state)
    state = await PlanningRuntimeService.aget_state_values(session_id)
    print(f"[mvp] main graph done. phase={state.get('phase')} completed_dims={state.get('completed_dimensions')}")


async def _trigger_post_l3(session_id: str) -> dict:
    """Inject gis_analysis intent to trigger the post-L3 chain."""
    from langchain_core.messages import AIMessage
    from app.services.runtime import PlanningRuntimeService

    synthetic = AIMessage(
        content="",
        tool_calls=[{
            "name": "gis_analysis",
            "id": f"call_gis_{session_id[:8]}",
            "args": {"reason": "生成空间布局规划", "dimension_key": "spatial_layout"},
        }],
    )
    state_values = await PlanningRuntimeService.aget_state_values(session_id)
    messages = list(state_values.get("messages") or []) + [synthetic]
    await PlanningRuntimeService.aupdate_state(
        session_id,
        {"messages": messages},
        as_node="__start__",
    )
    await PlanningRuntimeService._trigger_planning_execution(session_id, state_values=state_values)
    return await PlanningRuntimeService.aget_state_values(session_id)


def _verify_artifacts(session_id: str) -> dict:
    from app.modules.ports.artifact_store import ArtifactRef
    from app.services.artifact_store import FilesystemArtifactStore

    store = FilesystemArtifactStore()
    refs = store.list_by_run(session_id)
    types = {r.artifact_type for r in refs}
    missing = [t for t in _REQUIRED_ARTIFACTS if t not in types]
    result = {
        "found": sorted(types),
        "missing": missing,
        "count": len(refs),
        "ok": not missing,
    }
    return result


async def _run_record(session_id: str, cfg: dict) -> None:
    await _run_main_graph(session_id, cfg)
    await _write_recorded_reports(session_id, _RECORD_DIR)
    final = await _trigger_post_l3(session_id)
    print(f"[mvp] post-L3 final status: {final.get('post_l3_status')} / delivery_manifest={'yes' if final.get('delivery_manifest') else 'no'}")


async def _run_replay(session_id: str, cfg: dict) -> None:
    await _restore_recorded_reports(session_id, _RECORD_DIR)
    final = await _trigger_post_l3(session_id)
    print(f"[mvp] post-L3 final status: {final.get('post_l3_status')} / delivery_manifest={'yes' if final.get('delivery_manifest') else 'no'}")


async def main() -> int:
    mode = os.getenv("RUN_REAL_LLM", "replay")
    if len(sys.argv) > 2 and sys.argv[1] == "--mode":
        mode = sys.argv[2]

    cfg = _load_session_config()
    print(f"[mvp] mode={mode} village={cfg['village_name']}")

    # Minimal in-test DB bootstrap (mirrors tests/fixtures/db.py).
    import tempfile
    from pathlib import Path as _P

    import app.database.models  # noqa: F401 — register all tables on SQLModel.metadata
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    db_path = _P(tempfile.mkdtemp()) / "mvp.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    eng.async_engine = engine
    eng.AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Clear pipeline caches.
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

    await make_session_with_uploads(
        session_id=session_id,
        village_name=cfg["village_name"],
        uploads=_build_uploads(),
    )

    try:
        if mode == "record":
            await _run_record(session_id, cfg)
        elif mode == "real":
            await _run_main_graph(session_id, cfg)
            await _trigger_post_l3(session_id)
        else:
            await _run_replay(session_id, cfg)
    finally:
        await engine.dispose()

    result = _verify_artifacts(session_id)
    print(f"[mvp] ARTIFACTS: {result}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
