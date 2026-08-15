#!/usr/bin/env python
"""Persistent, resume-capable real e2e driver (standalone; no pytest).

First invocation:  creates a session + persistent checkpoint DB and drives the
                    graph forward (L1->L2->L3->post-L3->GROUND->SELECT->...).
Later invocations: reuses the persisted session id + checkpoint DB and RESUMES
                    from the last checkpoint (no L1-L3 rerun) unless the run is
                    already terminal.

Usage (PowerShell):
    cd backend; python _e2e_resume.py [--force-new] [--deadline-seconds N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

BASE = BACKEND / ".run-tmp" / "persistent-e2e"
BASE.mkdir(parents=True, exist_ok=True)
PERSISTENT_DB = BASE / "test.db"
SESSION_FILE = BASE / "session_id.txt"
ARTIFACT_ROOT = BASE / "artifacts"
LOG_FILE = BASE / "run.log"

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
        str(sorted(
            (str(k) + ":" + ",".join(sorted(v)) for k, v in completed.items())
        )),
    ])


def _graph_has_pending_tasks(client, session_id: str) -> bool:
    try:
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )

        snapshot = client.portal.call(
            PlanningRuntimeService.aget_state, session_id
        )
    except Exception:
        return False
    return bool(snapshot and getattr(snapshot, "tasks", None))


def _sanctioned_classification_decisions(client, session_id: str, review_payload: dict):
    """Generate closed-set appendix5 decisions via the sanctioned L3 generator."""
    required = {
        str(target_id)
        for item in review_payload.get("items") or []
        if isinstance(item, dict)
        for target_id in ((item.get("context") or {}).get("target_ids") or [])
        if str(target_id).strip()
    }
    if not required:
        return None, "classification review carried no target_ids"
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.contracts.domain.l3_contracts import PlanningProgram
    from app.domain.program.classification_generator import (
        generate_classification_decisions,
    )

    from app.infrastructure.runtime.planning_runtime_service import (
        PlanningRuntimeService,
    )

    state = client.portal.call(PlanningRuntimeService.aget_state_values, session_id) or {}
    program = load_artifact(state, "planning_program", PlanningProgram)
    if program is None:
        return None, "planning_program artifact unavailable at the pause"
    decisions = client.portal.call(generate_classification_decisions, program)
    if not decisions:
        return None, "sanctioned generator produced no decisions"
    supplied = {str(decision.target_id) for decision in decisions}
    missing = sorted(required - supplied)
    if missing:
        return None, "sanctioned generator missing targets: %s" % missing
    return [decision.model_dump(mode="json") for decision in decisions], "llm_closed_set"


def dump_diag(client, session_id: str, tag: str) -> None:
    try:
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )

        vals = client.portal.call(
            PlanningRuntimeService.aget_state_values, session_id
        ) or {}
        snapshot = client.portal.call(
            PlanningRuntimeService.aget_state, session_id
        )
        tasks = getattr(snapshot, "tasks", None) or []
        summary = {
            "tag": tag,
            "phase": vals.get("phase"),
            "active_stage": vals.get("active_stage"),
            "current_stage": vals.get("current_stage"),
            "next_stage": vals.get("next_stage"),
            "paused_stage": vals.get("paused_stage"),
            "delivery_status": vals.get("delivery_status"),
            "human_review_event_id": vals.get("human_review_event_id"),
            "human_review_resume_consumed": vals.get("human_review_resume_consumed"),
            "pending_task_count": len(tasks),
            "artifact_ref_keys": sorted((vals.get("artifact_refs") or {}).keys()),
        }
        diag = ARTIFACT_ROOT / session_id / "resume-diagnostic.json"
        diag.parent.mkdir(parents=True, exist_ok=True)
        with diag.open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        log("[DIAG] %s %s" % (tag, json.dumps(summary, ensure_ascii=False)))
    except Exception as exc:
        log("[DIAG] dump failed for %s: %s" % (tag, exc))


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
    eng.AsyncSessionLocal = async_sessionmaker(
        bind=engine, expire_on_commit=False
    )
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


def load_fixture():
    fixture = BACKEND / "tests" / "fixtures" / "mvp_village"
    files = []
    for path in sorted((fixture / "gis").glob("*.geojson")):
        files.append((
            "village_data_files",
            (path.name, path.read_bytes(), "application/geo+json"),
        ))
    report = (fixture / "current_report.md").read_text(encoding="utf-8")
    cfg = json.loads((fixture / "session_config.json").read_text(encoding="utf-8"))
    return files, report, cfg


def create_session(client, files, report, cfg):
    response = client.post(
        "/api/v1/sessions",
        data={
            "project_name": cfg.get("project_name", ""),
            "village_name": cfg.get("village_name", ""),
            "province": cfg.get("province", ""),
            "city": cfg.get("city", ""),
            "county": cfg.get("county", ""),
            "township": cfg.get("township", ""),
            "planning_period": cfg.get("planning_period", "2022-2035"),
            "task_description": cfg.get("task_description", ""),
            "constraints": cfg.get("constraints", ""),
            "step_mode": "true",
            "village_data": report,
        },
        files=files,
    )
    if response.status_code != 201:
        log("session create FAILED: %s %s" % (response.status_code, response.text))
        sys.exit(2)
    session_id = response.json()["session_id"]
    SESSION_FILE.write_text(session_id, encoding="utf-8")
    log("created session id=%s" % session_id)
    return session_id


def drive(client, session_id: str, deadline: float) -> dict:
    from app.infrastructure.runtime.planning_runtime_service import (
        PlanningRuntimeService,
    )

    def get_state_values(session: str) -> dict:
        return client.portal.call(
            PlanningRuntimeService.aget_state_values, session
        ) or {}

    state = {}
    terminal = False
    processed_event_ids = set()
    last_progress = None
    last_progress_at = time.monotonic()
    last_progress_change_at = time.monotonic()
    last_watchdog_at = 0.0
    last_resume_kick_at = 0.0
    terminal_state = {}

    while time.monotonic() < deadline:
        current = get_state_values(session_id)
        state = current or state
        if current and _delivery_poll_terminal(current):
            terminal = True
            terminal_state = current
            break
        progress = _progress_fingerprint(current)
        now = time.monotonic()
        pending_tasks = _graph_has_pending_tasks(client, session_id)
        if now - last_watchdog_at >= 10.0:
            log(
                "[WATCHDOG] phase=%r active_stage=%r pending_tasks=%s "
                "delivery_status=%r paused_stage=%r"
                % (
                    current.get("phase"),
                    current.get("active_stage"),
                    pending_tasks,
                    current.get("delivery_status"),
                    current.get("paused_stage"),
                )
            )
            last_watchdog_at = now
        if progress != last_progress:
            last_progress = progress
            last_progress_at = now
            last_progress_change_at = now
        if progress != last_progress or pending_tasks:
            last_progress = progress
            last_progress_at = now
        elif now - last_progress_at > STALL_WAIT_S:
            dump_diag(client, session_id, "stall")
            log("STALL: fingerprint unchanged for %ss; phase=%r paused_stage=%r"
                % (STALL_WAIT_S, current.get("phase"), current.get("paused_stage")))
            return {"stalled": True, "state": state}

        review = client.get(
            "/api/v1/sessions/%s/human-review" % session_id
        )
        if review.status_code != 200:
            time.sleep(0.5)
            continue
        review_payload = review.json()
        has_review_items = bool(review_payload.get("items") or [])
        if not has_review_items:
            time.sleep(0.5)
            continue
        event_id = str(review_payload.get("event_id") or "")
        if event_id and event_id in processed_event_ids:
            time.sleep(0.5)
            continue
        provider_failure = any(
            (item.get("context") or {}).get("code")
            in {
                "llm_provider_error",
                "llm_stream_timeout",
                "llm_timeout",
                "llm_provider_circuit_open",
            }
            for item in review_payload.get("items") or []
            if isinstance(item, dict)
        )
        if provider_failure:
            decision = {"action": "retry", "feedback": "provider retry"}
            action = "retry"
        else:
            classification_required = any(
                str(item.get("request_type") or "")
                == "classification_decision_required"
                for item in review_payload.get("items") or []
                if isinstance(item, dict)
            )
            program_rework_dims = list(dict.fromkeys(
                str((item.get("context") or {}).get("dimension_key") or "").strip()
                for item in review_payload.get("items") or []
                if isinstance(item, dict)
                and str(item.get("request_type") or "") == "program_rework"
                and str((item.get("context") or {}).get("dimension_key") or "").strip()
            ))
            if program_rework_dims:
                # L3 claims with structural errors (e.g. bad area units) need a
                # single-dimension rework with corrective feedback, not approve.
                decision = {
                    "action": "retry",
                    "feedback": "rework invalid claims with corrective feedback",
                    "dimensions": program_rework_dims,
                }
                action = "retry"
            elif classification_required:
                decisions, source = _sanctioned_classification_decisions(
                    client, session_id, review_payload
                )
                if decisions is None:
                    log("classification decisions unavailable: %s" % source)
                    time.sleep(2.0)
                    continue
                log("classification decisions from %s (%d)" % (source, len(decisions)))
                decision = {
                    "action": "approve",
                    "feedback": "classification approved",
                    "classification_decisions": decisions,
                }
            else:
                paused_stage = str(review_payload.get("paused_stage") or "")
                selection_no_candidate = any(
                    str(item.get("request_type") or "")
                    in {"selection_no_candidate", "portfolio_infeasible"}
                    for item in review_payload.get("items") or []
                    if isinstance(item, dict)
                )
                if paused_stage == "select" or selection_no_candidate:
                    # SELECT could not place every target.  Accept the partial
                    # selection so EXECUTE runs the placed targets; do NOT
                    # defer the whole portfolio (that empties the execution
                    # plan and forces diagnostic_only).
                    decision = {
                        "action": "approve",
                        "feedback": (
                            "accept partial selection; EXECUTE runs placed "
                            "targets only, unplaced stay unplaced"
                        ),
                    }
                else:
                    # GROUND unresolved spatial references -> bounded deferral
                    # of exactly the listed unresolved targets.
                    decision = {
                        "action": "approve",
                        "feedback": (
                            "approve with unresolved spatial references deferred "
                            "to GROUND/SELECT"
                        ),
                        "acknowledge_unresolved_spatial_references": True,
                        "defer_unresolved_spatial_references": True,
                        "deferred_target_ids": list(dict.fromkeys(
                            str(target_id)
                            for item in review_payload.get("items") or []
                            for target_id in (
                                (item.get("context") or {}).get("target_ids") or []
                            )
                            if str(target_id).strip()
                        )),
                    }
            action = "approve"
        log(
            "human-review submit stage=%s items=%d action=%s event=%s"
            % (
                review_payload.get("paused_stage"),
                len(review_payload.get("items") or []),
                action,
                event_id,
            )
        )
        dump_diag(client, session_id, "pre-resume")
        resolved = client.post(
            "/api/v1/sessions/%s/human-review" % session_id,
            json={
                "event_id": event_id,
                "action": action,
                "decisions": decision,
            },
        )
        if resolved.status_code != 200:
            log("human-review submit FAILED: %s %s" % (resolved.status_code, resolved.text))
            time.sleep(1.0)
            continue
        if event_id:
            processed_event_ids.add(event_id)
        dump_diag(client, session_id, "post-resume")
        time.sleep(0.5)

    if not terminal:
        dump_diag(client, session_id, "deadline")
        log("DEADLINE reached without terminal; last phase=%r paused_stage=%r"
            % (state.get("phase"), state.get("paused_stage")))
        return {"stalled": True, "state": state}
    return {"terminal": True, "state": terminal_state}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-new", action="store_true", help="create a fresh session")
    parser.add_argument("--deadline-seconds", type=float, default=1800.0)
    args = parser.parse_args()

    setup_engine()
    pipeline_reset()

    from app.infrastructure.paths import reset_run_tmp_root_cache

    os.environ["BACKEND_RUN_TMP_DIR"] = str(ARTIFACT_ROOT)
    reset_run_tmp_root_cache()
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    import app.main as main_app

    from fastapi.testclient import TestClient

    resume = False
    session_id = ""
    if SESSION_FILE.exists() and not args.force_new:
        session_id = SESSION_FILE.read_text(encoding="utf-8").strip()
        resume = bool(session_id)

    log("persistent db=%s resume=%s session=%s" % (PERSISTENT_DB, resume, session_id or "-"))

    with TestClient(main_app.app) as client:
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )

        if resume:
            existing = client.portal.call(
                PlanningRuntimeService.aget_state_values, session_id
            )
            if not existing:
                log("session id file exists but checkpoint is empty; creating fresh session")
                resume = False
            else:
                log(
                    "resuming existing session phase=%r paused_stage=%r"
                    % (existing.get("phase"), existing.get("paused_stage"))
                )
        if not resume:
            files, report, cfg = load_fixture()
            session_id = create_session(client, files, report, cfg)
            log("session created (fresh run): %s" % session_id)

        # Resume-first recovery: if a previous process was killed mid-superstep
        # (pending tasks, no HUMAN interrupt), kick the graph ONCE from the
        # persisted thread head.  Never kick inside the poll loop - a healthy
        # long LLM superstep also freezes the fingerprint, and kicking there
        # re-runs L1/L3 (duplicate LLM work).
        try:
            from app.workflow.stages.support import _progress_fingerprint as _fp
            start_vals = client.portal.call(
                PlanningRuntimeService.aget_state_values, session_id
            ) or {}
            start_snap = client.portal.call(
                PlanningRuntimeService.aget_state, session_id
            )
            has_interrupt = any(
                getattr(t, "interrupts", None) or ()
                for t in (getattr(start_snap, "tasks", None) or ())
            )
            if (
                start_snap is not None
                and (getattr(start_snap, "tasks", None) or [])
                and not has_interrupt
                and not _delivery_poll_terminal(start_vals)
                and not start_vals.get("paused_stage")
            ):
                log("kick resume_execution once for stale mid-superstep checkpoint")
                client.portal.call(PlanningRuntimeService.resume_execution, session_id)
        except Exception as exc:
            log("startup resume kick failed: %s" % exc)

        deadline = time.monotonic() + args.deadline_seconds
        result = drive(client, session_id, deadline)
        state = result.get("state") or {}
        if result.get("terminal"):
            log(
                "TERMINAL delivery_status=%r phase=%r"
                % (state.get("delivery_status"), state.get("phase"))
            )
            dump_diag(client, session_id, "final")
            return 0
        log(
            "NOT TERMINAL: phase=%r paused_stage=%r delivery_status=%r"
            % (state.get("phase"), state.get("paused_stage"), state.get("delivery_status"))
        )
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(3)
