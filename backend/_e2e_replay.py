#!/usr/bin/env python
"""Replay the post-L3 tail (GROUND->SELECT->EXECUTE->VALIDATE->RECONCILE->DELIVER)
from a persisted post-L3 checkpoint WITHOUT rerunning L1-L3.

Usage: python _e2e_replay.py [checkpoint_id]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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
LOG_FILE = BASE / "replay.log"
STALL_WAIT_S = 90.0


def log(msg: str) -> None:
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _delivery_poll_terminal(state: dict) -> bool:
    delivery_status = str(state.get("delivery_status") or "")
    if delivery_status in {"complete", "partial", "diagnostic_only"}:
        return True
    deliver_gate = state.get("deliver_gate") or {}
    route = (
        deliver_gate.get("feedback_route")
        if isinstance(deliver_gate, dict)
        else getattr(deliver_gate, "feedback_route", None)
    )
    return route in {"PASS", "END_DIAGNOSTIC"} or bool(state.get("fatal_error"))


def _progress_fingerprint(state: dict) -> str:
    completed = state.get("completed_dimensions") or {}
    return "|".join([
        str(state.get("phase") or ""),
        str(state.get("active_stage") or ""),
        str(state.get("delivery_status") or ""),
        str(state.get("paused_stage") or ""),
        str(bool(state.get("human_review_resume_consumed"))),
        str(len(state.get("human_review_items") or [])),
    ])


def _graph_has_pending_tasks(client, session_id: str) -> bool:
    try:
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )
        snapshot = client.portal.call(PlanningRuntimeService.aget_state, session_id)
    except Exception:
        return False
    return bool(snapshot and getattr(snapshot, "tasks", None))


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
    checkpoint_id = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    setup_engine()
    pipeline_reset()
    os.environ["BACKEND_RUN_TMP_DIR"] = str(ARTIFACT_ROOT)
    from app.infrastructure.paths import reset_run_tmp_root_cache
    reset_run_tmp_root_cache()
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    if not SESSION_FILE.exists():
        log("no session id file")
        return 2
    session_id = SESSION_FILE.read_text(encoding="utf-8").strip()

    import app.main as main_app
    from fastapi.testclient import TestClient

    with TestClient(main_app.app) as client:
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )

        def get_state_values(session: str) -> dict:
            return client.portal.call(
                PlanningRuntimeService.aget_state_values, session
            ) or {}

        if checkpoint_id:
            log("forking checkpoint %s" % checkpoint_id)
            resp = client.post(
                "/api/v1/sessions/%s/resume" % session_id,
                json={
                    "mode": "checkpoint",
                    "checkpoint_id": checkpoint_id,
                },
            )
            log("replay trigger status=%s body=%s" % (resp.status_code, resp.text[:300]))

        state = {}
        last_progress = None
        last_progress_at = time.monotonic()
        last_watchdog_at = 0.0
        last_resume_kick_at = 0.0
        processed = set()
        deadline = time.monotonic() + 1800.0
        terminal = False
        while time.monotonic() < deadline:
            current = get_state_values(session_id)
            state = current or state
            if current and _delivery_poll_terminal(current):
                terminal = True
                break
            progress = _progress_fingerprint(current)
            now = time.monotonic()
            pending_tasks = _graph_has_pending_tasks(client, session_id)
            if now - last_watchdog_at >= 10.0:
                log("[WATCHDOG] phase=%r paused=%r delivery=%r tasks=%s"
                    % (current.get("phase"), current.get("paused_stage"),
                       current.get("delivery_status"), pending_tasks))
                last_watchdog_at = now
            if progress != last_progress or pending_tasks:
                last_progress = progress
                last_progress_at = now
            elif now - last_progress_at > STALL_WAIT_S:
                log("STALL phase=%r paused=%r" % (current.get("phase"), current.get("paused_stage")))
                break
            review = client.get("/api/v1/sessions/%s/human-review" % session_id)
            if review.status_code != 200:
                time.sleep(0.5)
                continue
            payload = review.json()
            items = payload.get("items") or []
            if not items:
                time.sleep(0.5)
                continue
            event_id = str(payload.get("event_id") or "")
            if event_id and event_id in processed:
                time.sleep(0.5)
                continue
            paused_stage = str(payload.get("paused_stage") or "")
            selection = any(
                str(it.get("request_type") or "") in {"selection_no_candidate", "portfolio_infeasible"}
                for it in items if isinstance(it, dict)
            )
            provider_failure = any(
                (it.get("context") or {}).get("code") in {
                    "llm_provider_error", "llm_stream_timeout", "llm_timeout",
                    "llm_provider_circuit_open",
                }
                for it in items if isinstance(it, dict)
            )
            program_rework_dims = list(dict.fromkeys(
                str((it.get("context") or {}).get("dimension_key") or "").strip()
                for it in items if isinstance(it, dict)
                and str(it.get("request_type") or "") == "program_rework"
                and str((it.get("context") or {}).get("dimension_key") or "").strip()
            ))
            if program_rework_dims:
                decision = {
                    "action": "retry",
                    "feedback": "rework invalid claims with corrective feedback",
                    "dimensions": program_rework_dims,
                }
                action = "retry"
            elif provider_failure:
                decision = {"action": "retry", "feedback": "provider retry"}
                action = "retry"
            elif selection or paused_stage == "select":
                decision = {"action": "approve", "feedback": "accept partial selection"}
                action = "approve"
            else:
                decision = {
                    "action": "approve",
                    "feedback": "approve with unresolved spatial references deferred",
                    "acknowledge_unresolved_spatial_references": True,
                    "defer_unresolved_spatial_references": True,
                    "deferred_target_ids": list(dict.fromkeys(
                        str(tid) for it in items
                        for tid in ((it.get("context") or {}).get("target_ids") or [])
                        if str(tid).strip()
                    )),
                }
                action = "approve"
            log("submit stage=%s items=%d action=%s event=%s" % (paused_stage, len(items), action, event_id))
            resp = client.post(
                "/api/v1/sessions/%s/human-review" % session_id,
                json={"event_id": event_id, "action": action, "decisions": decision},
            )
            if resp.status_code != 200:
                log("submit failed %s %s" % (resp.status_code, resp.text[:200]))
                time.sleep(1.0)
                continue
            if event_id:
                processed.add(event_id)
            time.sleep(0.5)

        log("RESULT terminal=%s phase=%r paused=%r delivery=%r"
            % (terminal, state.get("phase"), state.get("paused_stage"), state.get("delivery_status")))
        log("artifacts: %s" % sorted((state.get("artifact_refs") or {}).keys()))
        return 0 if terminal else 1


if __name__ == "__main__":
    sys.exit(main())
