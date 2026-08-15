#!/usr/bin/env python
"""Verify a persisted e2e session: artifact landing stats + render preview.

Usage: python _e2e_verify.py [session_id]
Reads the persisted checkpoint DB (.run-tmp/persistent-e2e/test.db).  If no
session id is given, uses .run-tmp/persistent-e2e/session_id.txt.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

BASE = BACKEND / ".run-tmp" / "persistent-e2e"
PERSISTENT_DB = BASE / "test.db"
SESSION_FILE = BASE / "session_id.txt"
ARTIFACT_ROOT = BASE / "artifacts"


def setup_engine() -> None:
    import app.database.engine as eng
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel

    engine = create_async_engine(
        "sqlite+aiosqlite:///%s" % PERSISTENT_DB,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    asyncio.run(_create_all())
    eng.async_engine = engine
    eng.AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
    eng.DB_PATH = PERSISTENT_DB
    eng.CHECKPOINT_DB_PATH = PERSISTENT_DB
    eng._checkpointer = None
    eng._checkpointer_initialized = False
    eng._checkpointers_by_loop.clear()


def pipeline_reset() -> None:
    import app.data.ingestion.connections.base as conn_base
    import app.infrastructure.kg.manager as kg_man
    import app.infrastructure.storage.bundle_store as bs
    import app.application.sessions.session_bundle as sb

    sb._bundle_cache.clear()
    kg_man.KGManager._instance = None
    bs.BundleStore._instance = None
    conn_base.ConnectionRegistry._connections.clear()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id", nargs="?", default="")
    args = parser.parse_args()

    setup_engine()
    pipeline_reset()
    os.environ["BACKEND_RUN_TMP_DIR"] = str(ARTIFACT_ROOT)
    from app.infrastructure.paths import reset_run_tmp_root_cache

    reset_run_tmp_root_cache()
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    session_id = args.session_id.strip()
    if not session_id and SESSION_FILE.exists():
        session_id = SESSION_FILE.read_text(encoding="utf-8").strip()
    if not session_id:
        print("no session id available")
        return 2

    import app.main as main_app
    from fastapi.testclient import TestClient

    with TestClient(main_app.app) as client:
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )

        state = client.portal.call(
            PlanningRuntimeService.aget_state_values, session_id
        ) or {}
        if not state:
            print("session %s has no checkpoint state" % session_id)
            return 2
        print("phase=%r delivery_status=%r paused_stage=%r"
              % (state.get("phase"), state.get("delivery_status"), state.get("paused_stage")))

        from app.infrastructure.artifacts.runtime import load_artifact
        from app.contracts.artifacts.delivery_manifest_contracts import DeliveryManifest
        from app.contracts.workflow.execution_plan_contracts import ExecutionResult
        from app.contracts.domain.selection_contracts import SiteSelectionDecision
        from app.contracts.spatial.spatial_delivery_contracts import DeliverySpatialSnapshot

        manifest = load_artifact(state, "delivery_manifest", DeliveryManifest)
        outcome = load_artifact(state, "execution_result", ExecutionResult)
        selection = load_artifact(state, "site_selection", SiteSelectionDecision)
        snapshot = load_artifact(state, "delivery_spatial_snapshot", DeliverySpatialSnapshot)

        print("delivery_manifest:", "MISSING" if manifest is None else manifest.delivery_status)
        print("execution_result:", "MISSING" if outcome is None else "present")
        print("site_selection:", "MISSING" if selection is None else "present")
        print("delivery_spatial_snapshot:", "MISSING" if snapshot is None else "present")

        # ── landing statistics ────────────────────────────────────────────
        if manifest is not None:
            items = list(getattr(manifest, "traceability", None) or [])
            covered = [it for it in items if getattr(it, "status", "") == "covered"]
            partial = [it for it in items if getattr(it, "status", "") == "partial"]
            deferred = [it for it in items if getattr(it, "status", "") == "deferred"]
            failed = [it for it in items if getattr(it, "status", "") == "failed"]
            missing = [it for it in items if getattr(it, "status", "") == "missing"]
            total = len(items)
            print("manifest traceability: total=%d covered=%d partial=%d deferred=%d failed=%d missing=%d"
                  % (total, len(covered), len(partial), len(deferred), len(failed), len(missing)))
            by_type = {}
            for it in items:
                t = str(getattr(it, "target_type", "") or "")
                by_type.setdefault(t, [0, 0])
                by_type[t][0] += 1
                if getattr(it, "status", "") in {"covered", "partial"}:
                    by_type[t][1] += 1
            for t, (n, ok) in sorted(by_type.items()):
                print("  target_type=%s total=%d landed=%d" % (t, n, ok))
            for it in deferred + failed:
                print("  NOT-COVERED:", getattr(it, "target_id", ""), getattr(it, "target_type", ""), getattr(it, "status", ""))
            actions = list(getattr(manifest, "action_results", None) or [])
            ok_actions = [a for a in actions if str(getattr(a, "status", "") or "") == "succeeded"]
            print("manifest action_results: total=%d succeeded=%d" % (len(actions), len(ok_actions)))
            print("deferral_summary:", json.dumps(getattr(manifest, "deferral_summary", None) or {}, ensure_ascii=False)[:800])

        if outcome is not None:
            res = list(getattr(outcome, "task_results", None) or [])
            landed = [r for r in res if str(getattr(r, "status", "") or "") == "succeeded"]
            deferred_t = [r for r in res if str(getattr(r, "status", "") or "") == "deferred"]
            failed_t = [r for r in res if str(getattr(r, "status", "") or "") == "failed"]
            print("execution task_results: total=%d succeeded=%d deferred=%d failed=%d"
                  % (len(res), len(landed), len(deferred_t), len(failed_t)))
            for r in landed[:20]:
                print("  LANDED:", getattr(r, "target_id", ""), getattr(r, "target_type", ""), getattr(r, "status", ""))

        if selection is not None:
            decisions = list(getattr(selection, "target_assignments", None) or [])
            placed_d = [d for d in decisions if str(getattr(d, "status", "") or "") == "placed"]
            unplaced_d = [d for d in decisions if str(getattr(d, "status", "") or "") == "unplaced"]
            deferred_d = [d for d in decisions if str(getattr(d, "status", "") or "") == "deferred"]
            print("site_selection target_assignments: total=%d placed=%d unplaced=%d deferred=%d"
                  % (len(decisions), len(placed_d), len(unplaced_d), len(deferred_d)))

        # ── render ────────────────────────────────────────────────────────
        try:
            render_artifacts = load_artifact(state, "render_artifacts") or {}
            print("render_artifacts layer_count:", render_artifacts.get("layer_count"))
            for key in ("static_preview", "interactive_map"):
                artifact = render_artifacts.get(key) or {}
                print("  %s status=%s path=%s"
                      % (key, artifact.get("status"), artifact.get("path")))
            preview = render_artifacts.get("static_preview") or {}
            preview_path = preview.get("path")
            if preview_path and Path(preview_path).exists():
                print("PREVIEW_PNG=%s" % Path(preview_path).resolve())
        except Exception as exc:
            print("render artifact read failed: %s" % exc)

        render_response = client.get("/api/v1/sessions/%s/map-layers" % session_id)
        print("map-layers status:", render_response.status_code)
        if render_response.status_code == 200:
            layers = render_response.json().get("layers") or []
            print("map-layers layer count:", len(layers))
            for layer in layers:
                data = layer.get("geojson") or layer.get("data") or {}
                print("  layer %s features=%d" % (layer.get("id"), len(data.get("features") or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
