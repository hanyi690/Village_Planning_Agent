"""Opt-in end-to-end run with the configured remote LLM and real fixture GIS."""

from __future__ import annotations

import json
import os
import threading
import faulthandler
import time
from pathlib import Path
from uuid import uuid4

import pytest


def _live_llm_configured() -> bool:
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()
    if provider in {"zhipuai", "zhipu", "glm"}:
        return bool(os.getenv("ZHIPUAI_API_KEY"))
    if provider in {"dashscope", "qwen"}:
        return bool(os.getenv("DASHSCOPE_API_KEY"))
    if provider in {"minimax", "minimaxai", "mini-max"}:
        return bool(os.getenv("MINIMAX_API_KEY"))
    if provider in {"opencode-go", "opencode_go", "opencodego"}:
        return bool(os.getenv("OPENCODE_GO_API_KEY"))
    return bool(os.getenv("OPENAI_API_KEY"))


def _real_graph_run_enabled() -> bool:
    """Require an explicit operator switch before spending live LLM quota."""
    return os.getenv("RUN_REAL_GRAPH_RESUME", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _real_classification_decisions(review_payload: dict) -> list[dict] | None:
    """Load operator-approved closed-set decisions for a real HUMAN pause.

    The acceptance run must never infer planning codes from names or current
    land-use fields.  A full run therefore requires an explicit JSON payload
    supplied by the operator through ``REAL_CLASSIFICATION_DECISIONS_JSON`` or
    ``REAL_CLASSIFICATION_DECISIONS_PATH``.
    """
    raw = os.getenv("REAL_CLASSIFICATION_DECISIONS_JSON", "").strip()
    path = os.getenv("REAL_CLASSIFICATION_DECISIONS_PATH", "").strip()
    if not raw and path:
        raw = Path(path).read_text(encoding="utf-8")
    if not raw:
        return None
    payload = json.loads(raw)
    if isinstance(payload, dict) and "classification_decisions" in payload:
        payload = payload["classification_decisions"]
    if isinstance(payload, dict):
        payload = [dict(value, target_id=key) for key, value in payload.items()]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("real classification decisions must be a JSON list or target-id object")
    required = {
        str(target_id)
        for item in review_payload.get("items") or []
        if isinstance(item, dict)
        for target_id in ((item.get("context") or {}).get("target_ids") or [])
    }
    supplied = {str(item.get("target_id") or "") for item in payload}
    missing = sorted(required - supplied)
    if missing:
        raise ValueError(
            "REAL_CLASSIFICATION_DECISIONS is missing targets: " + ", ".join(missing)
        )
    return payload


def _sanctioned_classification_decisions(
    client,
    state: dict,
    review_payload: dict,
) -> tuple:
    """Generate closed-set appendix5 decisions via the sanctioned L3 generator.

    The L3 aggregate already runs this same LLM closed-set path over the
    authoritative appendix5 encoding in ``data``; this is a retry at the HUMAN
    boundary when the operator supplied no payload.  It is never a name/dlbm
    crosswalk mapping.  Returns ``(decisions, source)`` or ``(None, reason)``.
    """
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

    program = load_artifact(state, "planning_program", PlanningProgram)
    if program is None:
        return None, "planning_program artifact unavailable at the pause"
    decisions = client.portal.call(generate_classification_decisions, program)
    if not decisions:
        return None, "sanctioned generator produced no decisions"
    supplied = {str(decision.target_id) for decision in decisions}
    missing = sorted(required - supplied)
    if missing:
        return None, f"sanctioned generator missing targets: {missing}"
    return [decision.model_dump(mode="json") for decision in decisions], "llm_closed_set"


def _post_l3_poll_terminal(state: dict) -> bool:
    """Return true only for a delivery terminal, fatal error, or interrupt."""
    delivery_status = str(state.get("delivery_status") or "")
    if delivery_status in {"complete", "partial", "diagnostic_only"}:
        return True
    deliver_gate = state.get("deliver_gate") or {}
    route = (
        deliver_gate.get("feedback_route")
        if isinstance(deliver_gate, dict)
        else getattr(deliver_gate, "feedback_route", None)
    )
    if route in {"PASS", "END_DIAGNOSTIC"}:
        return True
    if state.get("fatal_error"):
        return True
    if state.get("human_review_resume_consumed"):
        return False
    return bool(state.get("paused_stage") or state.get("human_review_items"))


def _delivery_poll_terminal(state: dict) -> bool:
    """Return true only when the post-L3 delivery path is actually terminal."""
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
    """Fingerprint of the fields that must move while the graph is running.

    A live graph keeps changing ``phase``/``active_stage``, the per-layer
    completed dimensions or the delivery fields.  A fingerprint that stays
    constant across a stall window therefore means the graph terminated
    without reaching a delivery terminal (or deadlocked), and polling longer
    only burns the deadline.

    Note: LangGraph checkpoints once per superstep.  A layer's parallel
    dimension workers share a single superstep (LLM slot-limited), so the
    checkpoint fingerprint can legitimately stay frozen for 60-120s while the
    real graph is mid-flight.  The stall guard must therefore pair this
    fingerprint with the ``_graph_has_pending_tasks`` liveness probe.
    """
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
    """Liveness probe: the LangGraph checkpointer has un-consumed tasks.

    A checkpoint whose ``tasks`` is non-empty means a superstep is scheduled
    or in flight (parallel dimension workers, advance-phase dispatch).  A real
    graph therefore reports ``True`` across a long layer superstep even though
    the persisted fingerprint is frozen; a terminated or deadlocked graph
    reports ``False``.  Best-effort: a transient read error is treated as
    "no liveness" so the stall guard stays conservative.
    """
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        snapshot = client.portal.call(
            PlanningRuntimeService.aget_state,
            session_id,
        )
    except Exception:
        return False
    return bool(snapshot and getattr(snapshot, "tasks", None))


def _missing_l3_dimensions(state: dict) -> list[str]:
    """Return only L3 dimensions absent from the persisted checkpoint."""
    from app.config.loader import list_dimensions

    completed = set((state.get("completed_dimensions") or {}).get("layer3", []))
    return [item.key for item in list_dimensions(3) if item.key not in completed]


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
]


def test_phase_completed_without_post_l3_delivery_is_not_terminal():
    assert not _post_l3_poll_terminal({"phase": "completed"})
    assert _post_l3_poll_terminal({"phase": "completed", "delivery_status": "partial"})
    assert _post_l3_poll_terminal({
        "phase": "completed",
        "deliver_gate": {"feedback_route": "END_DIAGNOSTIC"},
    })
    assert _post_l3_poll_terminal({"paused_stage": "validate"})
    assert not _post_l3_poll_terminal({
        "paused_stage": "validate",
        "human_review_resume_consumed": True,
    })


@pytest.mark.skipif(
    not _real_graph_run_enabled() or not _live_llm_configured(),
    reason=(
        "live graph resume is quota-consuming and disabled by default; set "
        "RUN_REAL_GRAPH_RESUME=true and configure the provider API key"
    ),
)
@pytest.mark.timeout(7200)
def test_real_graph_resume_delivery(sqlite_db, pipeline_reset, monkeypatch):
    setup, teardown = sqlite_db
    import asyncio

    async def _llm_preflight() -> None:
        from app.infrastructure.llm.factory import create_llm
        llm = create_llm(
            temperature=0,
            max_tokens=8,
            streaming=False,
            request_timeout=30,
            max_retries=0,
        )
        await asyncio.wait_for(llm.ainvoke("只回复 OK"), timeout=30)

    try:
        print("[REAL-SESSION] preflight:start", flush=True)
        asyncio.run(_llm_preflight())
        print("[REAL-SESSION] preflight:done", flush=True)
    except Exception as exc:  # noqa: BLE001 - surface provider configuration clearly
        status = getattr(exc, "status_code", None)
        pytest.fail(
            "real LLM preflight failed before Session creation; "
            f"provider_status={status!r}, error_type={type(exc).__name__}. "
            "Update the configured provider credentials before running the full chain."
        )

    print("[REAL-SESSION] database_setup:start", flush=True)
    test_engine = asyncio.run(setup())
    print("[REAL-SESSION] database_setup:done", flush=True)
    import app.database.engine as db_engine
    # The SQLModel fixture and LangGraph checkpointer must use the same
    # temporary file.  Otherwise a "real" session silently writes checkpoints
    # into data/database/village_planning.db and can replay stale state.
    test_db_path = Path(test_engine.url.database).resolve()
    monkeypatch.setattr(db_engine, "DB_PATH", test_db_path)
    monkeypatch.setattr(db_engine, "CHECKPOINT_DB_PATH", test_db_path)
    monkeypatch.setattr(db_engine, "get_db_path", lambda: test_db_path)
    monkeypatch.setattr(db_engine, "_checkpointer", None)
    monkeypatch.setattr(db_engine, "_checkpointer_initialized", False)
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    import app.workflow.stages.execute as execute_stage
    monkeypatch.setattr(PlanningRuntimeService, "_checkpointer", None)
    monkeypatch.setattr(PlanningRuntimeService, "_graph", None)
    monkeypatch.setattr(execute_stage, "_execute_subgraph", None)
    monkeypatch.setattr(PlanningRuntimeService, "_initialized", False)
    faulthandler.enable(all_threads=True)
    stop_memory_sampler = threading.Event()

    def sample_memory() -> None:
        try:
            import psutil
            process = psutil.Process(os.getpid())
            while not stop_memory_sampler.wait(20):
                rss_mb = process.memory_info().rss / (1024 * 1024)
                print(f"[REAL-SESSION-MEMORY] rss_mb={rss_mb:.1f}", flush=True)
        except Exception as exc:
            print(f"[REAL-SESSION-MEMORY] unavailable={exc!r}", flush=True)

    memory_thread = threading.Thread(
        target=sample_memory, name="real-session-memory-sampler", daemon=True
    )
    memory_thread.start()
    try:
        # Opt-in persistent mode lets a later pytest invocation continue the
        # same LangGraph thread from SQLite instead of creating a new run.
        # The default remains isolated so ordinary tests stay disposable.
        persistent_run = os.getenv("REAL_RUN_PERSISTENT", "").lower() in {
            "1", "true", "yes", "on"
        }
        run_root = (
            Path(
                os.getenv(
                    "REAL_RUN_DIR",
                    str(Path.cwd() / ".run-tmp" / "persistent-e2e"),
                )
            ).resolve()
            if persistent_run
            else (Path.cwd() / ".run-tmp" / f"real-llm-{uuid4().hex}").resolve()
        )
        run_root.mkdir(parents=True, exist_ok=True)
        session_file = run_root / "session_id.txt"
        monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_root))
        from app.infrastructure.paths import reset_run_tmp_root_cache

        reset_run_tmp_root_cache()
        from fastapi.testclient import TestClient
        import app.main as main

        async def no_db_init():
            return True

        monkeypatch.setattr("app.database.init_async_db", no_db_init)
        fixture = Path(__file__).parents[1] / "fixtures" / "mvp_village"
        files = []
        for path in sorted((fixture / "gis").glob("*.geojson")):
            files.append((
                "village_data_files",
                (path.name, path.read_bytes(), "application/geo+json"),
            ))
        report = (fixture / "current_report.md").read_text(encoding="utf-8")
        print("[REAL-SESSION] testclient_startup:start", flush=True)
        with TestClient(main.app) as client:
            print("[REAL-SESSION] testclient_startup:done", flush=True)
            # TestClient runs the ASGI app and its async SQLite checkpointer in
            # a dedicated portal loop.  State reads must use that same loop;
            # repeatedly creating asyncio.run() loops leaves the checkpointer
            # lock bound to a different loop and masks the real session result.
            def get_state_values(session: str) -> dict:
                return client.portal.call(
                    PlanningRuntimeService.aget_state_values,
                    session,
                ) or {}

            def dump_state_diagnostic(tag: str) -> None:
                """Persist a full state snapshot for resume/post-resume diagnosis."""
                import json as _json

                try:
                    vals = get_state_values(session_id) or {}
                    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

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
                        "human_review_generation": vals.get("human_review_generation"),
                        "human_interrupt_keys": list((vals.get("human_interrupt") or {}).keys()),
                        "pending_task_count": len(tasks),
                        "pending_interrupt_ids": [
                            [str(i) for i in (getattr(t, "interrupts", ()) or ())] for t in tasks
                        ],
                        "artifact_ref_keys": sorted((vals.get("artifact_refs") or {}).keys()),
                    }
                    diag = run_root / session_id / "resume-diagnostic.json"
                    with diag.open("w", encoding="utf-8") as fh:
                        _json.dump(summary, fh, ensure_ascii=False, indent=2)
                    print(
                        "[REAL-DIAG] " + tag + " " + _json.dumps(summary, ensure_ascii=False),
                        flush=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[REAL-DIAG] dump failed for {tag}: {exc}", flush=True)


            async def close_and_reopen_runtime() -> None:
                """Close and reopen the real checkpointer against the same DB."""
                import app.database.engine as database_engine

                await PlanningRuntimeService.shutdown()
                await database_engine.shutdown_database()
                import app.workflow.stages.execute as execute_stage
                PlanningRuntimeService._checkpointer = None
                PlanningRuntimeService._graph = None
                execute_stage._execute_subgraph = None
                PlanningRuntimeService._initialized = False
                PlanningRuntimeService._lock = None
                PlanningRuntimeService._execution_locks.clear()
                await PlanningRuntimeService.ensure_initialized()

            session_id = ""
            resuming_existing = False
            if persistent_run and session_file.exists():
                candidate = session_file.read_text(encoding="utf-8").strip()
                if candidate and get_state_values(candidate):
                    session_id = candidate
                    resuming_existing = True
                    print(
                        f"[REAL-SESSION] session_resume:found session={session_id}",
                        flush=True,
                    )

            if not session_id:
                print("[REAL-SESSION] session_create:start", flush=True)
                response = client.post(
                    "/api/v1/sessions",
                    data={
                        "project_name": "金田村真实 LLM 全链验收",
                        "village_name": "金田村",
                        "village_data": report,
                        "step_mode": "true",
                    },
                    files=files,
                )
                assert response.status_code == 201, response.text
                session_id = response.json()["session_id"]
                if persistent_run:
                    session_file.write_text(session_id + "\n", encoding="utf-8")
                print(f"[REAL-SESSION] session_create:done session={session_id}", flush=True)
            else:
                print(f"[REAL-SESSION] session_resume:done session={session_id}", flush=True)
            (run_root / session_id).mkdir(parents=True, exist_ok=True)
            from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

            if resuming_existing:
                # A process can be terminated while a remote LLM node is in
                # flight.  Official LangGraph recovery resumes the deepest
                # pending subgraph checkpoint once at startup; it must not be
                # called from the polling loop because a healthy long request
                # can otherwise be duplicated.
                start_values = get_state_values(session_id) or {}
                start_snapshot = client.portal.call(
                    PlanningRuntimeService.aget_state,
                    session_id,
                )
                has_interrupt = any(
                    getattr(task, "interrupts", None) or ()
                    for task in (getattr(start_snapshot, "tasks", None) or ())
                )
                if (
                    start_snapshot is not None
                    and (getattr(start_snapshot, "tasks", None) or [])
                    and not has_interrupt
                    and not _delivery_poll_terminal(start_values)
                ):
                    print(
                        "[REAL-SESSION] session_resume:kick_deepest_checkpoint",
                        flush=True,
                    )
                    client.portal.call(
                        PlanningRuntimeService.resume_from_deepest_checkpoint,
                        session_id,
                    )
                elif (
                    start_values.get("next_stage") == "L3"
                    and not any(
                        getattr(task, "interrupts", None) or ()
                        for task in (getattr(start_snapshot, "tasks", None) or ())
                    )
                ):
                    missing_l3 = _missing_l3_dimensions(start_values)
                    if missing_l3:
                        print(
                            "[REAL-SESSION] session_resume:state_entry "
                            f"entry=provider_resume_dispatch missing={missing_l3}",
                            flush=True,
                        )
                        resume_updates = {
                            "phase": "layer3",
                            "current_stage": "L3",
                            "next_stage": "L3",
                            "delivery_status": "",
                            "diagnostic_terminal": {},
                            "fatal_error": None,
                            "paused_stage": None,
                            "human_interrupt": {},
                            "human_review_items": [],
                            "human_review_event_id": "",
                            "human_review_resume_consumed": False,
                            "provider_failures": [],
                            "dimension_failures": [],
                            "provider_resume_dimensions": missing_l3,
                            "layer_timed_out": False,
                            "layer_just_completed": None,
                            "layer_started_at": time.time(),
                        }
                        client.portal.call(
                            lambda: PlanningRuntimeService.resume_from_state_entry(
                                session_id,
                                entry="provider_resume_dispatch",
                                state_updates=resume_updates,
                            )
                        )

            # A real fixture may legitimately stop at HUMAN when the report
            # names a village that has no BSM/coordinate evidence.  The live
            # acceptance path must exercise the official interrupt/resume
            # contract instead of treating that pause as a deadlock.  This is
            # an explicit operator acknowledgement of the unresolved spatial
            # references, not a synthetic geometry mapping or candidate
            # fallback.  Each resume is bounded and auditable.
            human_resolutions = []
            # A resumed invocation has already proven that it can reopen the
            # persisted thread.  A fresh invocation still has to observe and
            # explicitly close/reopen a live HUMAN interrupt below.
            checkpoint_reopened = resuming_existing
            interrupt_event_id = ""
            last_processed_event_id = ""
            # L3 summary enrichment is supervised but may finish after the
            # worker checkpoint. Keep polling long enough for the official
            # interrupt payload to become visible before declaring a deadlock.
            # A stalled fingerprint for STALL_WAIT_S is treated as an early
            # termination (graph ENDed or deadlocked) and fails fast instead
            # of exhausting the per-iteration wait budget.
            last_progress = None
            last_progress_at = time.monotonic()
            stall_wait_seconds = float(
                os.getenv("REAL_RUN_STALL_WAIT_SECONDS", "300")
            )
            overall_deadline_seconds = float(
                os.getenv("REAL_RUN_DEADLINE_SECONDS", "7200")
            )
            overall_deadline = time.monotonic() + overall_deadline_seconds
            state = {}
            terminal = False
            processed_event_ids: set[str] = set()
            last_watchdog_report_at = 0.0
            while time.monotonic() < overall_deadline:
                current = get_state_values(session_id)
                state = current or state
                if current and _delivery_poll_terminal(current):
                    terminal = True
                    break
                progress = _progress_fingerprint(current)
                now = time.monotonic()
                pending_tasks = _graph_has_pending_tasks(client, session_id)
                if now - last_watchdog_report_at >= 10.0:
                    print(
                        "[REAL-WATCHDOG] "
                        f"phase={current.get('phase')!r} "
                        f"active_stage={current.get('active_stage')!r} "
                        f"pending_tasks={pending_tasks} "
                        f"delivery_status={current.get('delivery_status')!r}",
                        flush=True,
                    )
                    last_watchdog_report_at = now
                # Pending tasks are not progress.  A live interrupt can remain
                # pending for a long time while its public HUMAN projection is
                # broken; treating that as progress disables the stall
                # watchdog exactly when recovery is stuck.
                if progress != last_progress:
                    last_progress = progress
                    last_progress_at = now
                elif now - last_progress_at > stall_wait_seconds:
                    dump_state_diagnostic("stall")
                    pytest.fail(
                        "real graph stalled: state fingerprint unchanged for 90s "
                        f"phase={current.get('phase')!r}, "
                        f"active_stage={current.get('active_stage')!r}, "
                        f"paused_stage={current.get('paused_stage')!r}, "
                        f"delivery_status={current.get('delivery_status')!r}"
                    )
                # The interrupt payload is the authoritative HITL signal.  The
                # state projection does not expose paused_stage/resume markers,
                # so poll the public review endpoint every iteration and
                # auto-approve every HUMAN breakpoint (L1/L2/L3, post-L3 gates,
                # ground/select/validate/reconcile/deliver) so the run advances
                # without an interactive operator.  Only closed-set L3
                # classification decisions require an explicit external payload.
                review = client.get(f"/api/v1/sessions/{session_id}/human-review")
                if review.status_code == 404 and not current:
                    time.sleep(0.5)
                    continue
                assert review.status_code == 200, review.text
                review_payload = review.json()
                if not (review_payload.get("items") or []):
                    time.sleep(0.5)
                    continue
                event_id = str(review_payload.get("event_id") or "")
                if (
                    event_id
                    and event_id in processed_event_ids
                    and event_id == last_processed_event_id
                ):
                    # The graph is still replaying the exact interrupt after a
                    # resume; do not submit the same decision twice.
                    time.sleep(0.5)
                    continue
                if not checkpoint_reopened:
                    checkpoint_snapshot = client.portal.call(
                        PlanningRuntimeService.aget_state,
                        session_id,
                    )
                    assert checkpoint_snapshot is not None
                    assert checkpoint_snapshot.config["configurable"]["thread_id"] == session_id
                    assert any(
                        getattr(task, "interrupts", ())
                        for task in checkpoint_snapshot.tasks or ()
                    ), checkpoint_snapshot
                    interrupt_event_id = str(review_payload["event_id"])
                    client.portal.call(close_and_reopen_runtime)
                    reopened_snapshot = client.portal.call(
                        PlanningRuntimeService.aget_state,
                        session_id,
                    )
                    assert reopened_snapshot is not None
                    assert reopened_snapshot.config["configurable"]["thread_id"] == session_id
                    assert get_state_values(session_id).get("human_review_event_id") == interrupt_event_id
                    checkpoint_reopened = True
                provider_failure = any(
                    (item.get("context") or {}).get("code") in {
                        "llm_provider_error",
                        "llm_stream_timeout",
                        "llm_timeout",
                        "llm_provider_circuit_open",
                    }
                    for item in review_payload.get("items") or []
                    if isinstance(item, dict)
                )
                auto_provider_retry = os.getenv(
                    "REAL_RUN_AUTO_PROVIDER_RETRY", "0"
                ).lower() in {"1", "true", "yes", "on"}
                if provider_failure and auto_provider_retry:
                    decision = {
                        "action": "retry",
                        "feedback": "provider retry",
                    }
                    action = "retry"
                elif provider_failure:
                    # A provider failure is an auditable breakpoint, not an
                    # instruction to burn another full LLM attempt.  Opt in
                    # to one exact-dimension retry only when the operator
                    # explicitly sets REAL_RUN_AUTO_PROVIDER_RETRY=1.
                    decision = {
                        "action": "reject",
                        "feedback": "provider failure requires explicit retry decision",
                    }
                    action = "reject"
                else:
                    classification_required = any(
                        str(item.get("request_type") or "")
                        == "classification_decision_required"
                        for item in review_payload.get("items") or []
                        if isinstance(item, dict)
                    )
                    if classification_required:
                        classification_decisions = _real_classification_decisions(
                            review_payload
                        )
                        decision_source = "operator"
                        if classification_decisions is None:
                            classification_decisions, decision_source = (
                                _sanctioned_classification_decisions(
                                    client, current, review_payload
                                )
                            )
                        if classification_decisions is None:
                            pytest.fail(
                                "real graph reached classification_decision_required; "
                                "operator REAL_CLASSIFICATION_DECISIONS absent and the "
                                f"sanctioned closed-set generator failed: {decision_source}"
                            )
                        print(
                            f"[REAL-SESSION] classification decisions from {decision_source} "
                            f"({len(classification_decisions)})",
                            flush=True,
                        )
                        decision = {
                            "action": "approve",
                            "feedback": "classification approved",
                            "classification_decisions": classification_decisions,
                        }
                    else:
                        decision = {
                            "action": "approve",
                            "feedback": (
                                "approve with unresolved spatial references deferred to GROUND/SELECT"
                            ),
                            "acknowledge_unresolved_spatial_references": True,
                            "defer_unresolved_spatial_references": True,
                            "deferred_target_ids": list(dict.fromkeys(
                                str(target_id)
                                for item in review_payload.get("items") or []
                                for target_id in ((item.get("context") or {}).get("target_ids") or [])
                                if str(target_id).strip()
                            )),
                        }
                    action = "approve"
                dump_state_diagnostic("pre-resume")
                resolved = client.post(
                    f"/api/v1/sessions/{session_id}/human-review",
                    json={
                        "event_id": review_payload["event_id"],
                        "action": action,
                        "decisions": decision,
                    },
                )
                assert resolved.status_code == 200, resolved.text
                dump_state_diagnostic("post-resume")
                if event_id:
                    processed_event_ids.add(event_id)
                    last_processed_event_id = event_id
                human_resolutions.append({
                    "stage": review_payload.get("paused_stage"),
                    "item_count": len(review_payload.get("items") or []),
                })
                time.sleep(0.5)

            assert checkpoint_reopened, (
                "the real run did not expose and reopen a LangGraph interrupt checkpoint; "
                f"session={session_id}"
            )
            assert state, f"session state was never checkpointed within the run: {session_id}"
            assert terminal or time.monotonic() - last_progress_at <= stall_wait_seconds, (
                "real graph stalled: state fingerprint unchanged for 120s "
                f"phase={state.get('phase')!r}, "
                f"active_stage={state.get('active_stage')!r}, "
                f"paused_stage={state.get('paused_stage')!r}, "
                f"delivery_status={state.get('delivery_status')!r}, "
                f"session={session_id}"
            )
            from app.infrastructure.reports.stage_report import render_stage_report_markdown
            from app.infrastructure.reports.step_report import (
                build_backend_run_report,
                build_positioning_trace,
            )

            trace = client.portal.call(build_positioning_trace, session_id)
            backend_report = client.portal.call(build_backend_run_report, session_id)
            stage_report = render_stage_report_markdown(trace.get("reports", []), backend_report)
            (run_root / session_id / "real-llm-session-report.md").write_text(
                stage_report, encoding="utf-8"
            )
            required_stages = ("TARGET_PROJECTION", "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER")
            completed_reports = [
                item
                for item in trace.get("reports", [])
                if (item.get("diagnostics") or {}).get("status") == "stage_completed"
            ]
            missing_stages = [
                stage for stage in required_stages
                if not any(report.get("stage") == stage for report in completed_reports)
                or f"## {stage} /" not in stage_report
            ]
            assert not missing_stages, (
                "real LLM session did not produce complete stage audit; "
                f"missing={missing_stages}, phase={state.get('phase')!r}, "
                f"run_root={run_root}, "
                f"human_resolutions={human_resolutions!r}, "
                f"stage_report={run_root / session_id / 'reports' / 'stage-report.md'}"
            )
            for report_item in completed_reports:
                if report_item.get("stage") not in required_stages:
                    continue
                assert (report_item.get("inputs") or {}).get("input_checksum"), report_item
                assert (report_item.get("outputs") or {}).get("output_checksum"), report_item
                assert "output_summary" in (report_item.get("outputs") or {}), report_item
                diagnostics = report_item.get("diagnostics") or {}
                for key in (
                    "gate_input_checksum",
                    "gate_output_checksum",
                    "issue_fingerprint",
                    "route_reason",
                    "progress_made",
                    "gate_route",
                ):
                    assert key in diagnostics, report_item
            assert "input_checksum" in stage_report and "output_summary" in stage_report

            validation_fingerprints = [
                str((item.get("diagnostics") or {}).get("issue_fingerprint"))
                for item in completed_reports
                if item.get("stage") == "VALIDATE"
                and (item.get("diagnostics") or {}).get("issue_fingerprint")
            ]
            assert len(validation_fingerprints) == len(set(validation_fingerprints)), (
                "VALIDATE repeated an identical issue fingerprint; "
                f"fingerprints={validation_fingerprints!r}"
            )

            from app.infrastructure.artifacts.runtime import load_artifact
            from app.contracts.artifacts.delivery_manifest_contracts import DeliveryManifest
            from app.contracts.workflow.execution_plan_contracts import ExecutionResult
            from app.contracts.planning.approval import ApprovedExecutionInput
            from app.contracts.spatial.spatial_delivery_contracts import DeliverySpatialSnapshot

            manifest = load_artifact(state, "delivery_manifest", DeliveryManifest)
            outcome = load_artifact(state, "execution_result", ExecutionResult)
            approval = load_artifact(state, "approved_execution_input", ApprovedExecutionInput)
            spatial_snapshot = load_artifact(
                state,
                "delivery_spatial_snapshot",
                DeliverySpatialSnapshot,
            )
            assert manifest is not None, state.get("artifact_refs")
            assert outcome is not None, state.get("artifact_refs")
            assert spatial_snapshot is not None, state.get("artifact_refs")
            assert spatial_snapshot.complete_planned_landuse is not None
            planned_path = Path(spatial_snapshot.complete_planned_landuse.path)
            planned_payload = json.loads(planned_path.read_text(encoding="utf-8"))
            assert planned_payload["type"] == "FeatureCollection"
            assert len(planned_payload["features"]) == spatial_snapshot.complete_planned_landuse.feature_count
            assert manifest.delivery_status in {"complete", "partial"}, manifest
            assert state.get("delivery_status") == manifest.delivery_status
            if manifest.delivery_status == "partial":
                assert manifest.statutory_complete is False
                assert manifest.deferral_ledger is not None
                assert manifest.deferral_ledger.entries
                assert manifest.deferral_summary.get("count", 0) > 0
                assert any(item.status == "deferred" for item in manifest.traceability)

            outcome_target_ids = {
                item.target_id
                for item in outcome.task_results
                if item.status in {"succeeded", "deferred"}
            }
            deferred_target_ids = {
                item.target_id
                for item in (manifest.deferral_ledger.entries if manifest.deferral_ledger else ())
            }
            selected_facility_ids = set(approval.target_ids if approval else [])
            assert selected_facility_ids <= outcome_target_ids | deferred_target_ids, (
                "selected facilities are not fully accounted by execution/deferral; "
                f"selected={sorted(selected_facility_ids)!r}, "
                f"outcome={sorted(outcome_target_ids)!r}, "
                f"deferred={sorted(deferred_target_ids)!r}"
            )
            selected_project_point_ids = {
                item.target_id
                for item in (selection.target_assignments if selection else [])
                if (
                    item.target_type == "site_area"
                    and item.status == "placed"
                    and item.expected_output_kind == "point"
                )
            }
            if selected_project_point_ids:
                project_point_ref = spatial_snapshot.planned_overlay_layers.get(
                    "planned_project_point_geojson"
                )
                assert project_point_ref is not None
                assert project_point_ref.feature_count >= len(selected_project_point_ids)

            status_response = client.get(f"/api/v1/sessions/{session_id}/state")
            assert status_response.status_code == 200, status_response.text
            status_payload = status_response.json()
            assert status_payload.get("delivery_status") == manifest.delivery_status
            delivery_payload = client.get(f"/api/v1/sessions/{session_id}/delivery")
            assert delivery_payload.status_code == 200, delivery_payload.text
            assert delivery_payload.json().get("deferral_summary") == manifest.deferral_summary

            deliver_gate = state.get("deliver_gate") or {}
            deliver_route = (
                deliver_gate.get("feedback_route")
                if isinstance(deliver_gate, dict)
                else getattr(deliver_gate, "feedback_route", None)
            )
            assert deliver_route in {None, "PASS"}, (
                "real LLM session did not reach a successful terminal delivery; "
                f"phase={state.get('phase')!r}, deliver_gate={deliver_gate!r}, "
                f"paused_stage={state.get('paused_stage')!r}, "
                f"human_review_items={state.get('human_review_items')!r}, "
                f"human_resolutions={human_resolutions!r}, "
                f"stage_report={run_root / session_id / 'reports' / 'stage-report.md'}"
            )

            # L1 location resolution coverage (历史记录地点 → 实体/空间范围).
            from app.evidence.index.resolution_coverage import resolution_coverage
            from app.infrastructure.context.planning_context_factory import (
                build_planning_context,
            )
            from app.workflow.layers.context_bootstrap import _hydrate_l1_spatial_facts

            audit_context = client.portal.call(
                build_planning_context, session_id, "", True, True, None
            )
            client.portal.call(_hydrate_l1_spatial_facts, state, audit_context)
            cov = resolution_coverage(audit_context)
            print(f"[REAL-SESSION] L1 resolution {cov.summary()}", flush=True)
            min_rate = float(os.getenv("RESOLUTION_COVERAGE_MIN", "0.85"))
            assert cov.total > 0, (
                "real L1 snapshot produced no typed location facts; "
                "observations JSON did not compile into the evidence index"
            )
            assert cov.extent_rate >= min_rate, (
                "real L1 location resolution below threshold "
                f"min={min_rate:.0%} {cov.summary()} session={session_id}"
            )

            render_response = client.get(f"/api/v1/sessions/{session_id}/map-layers")
            assert render_response.status_code == 200, render_response.text
            layers = render_response.json().get("layers") or []
            assert layers, "DELIVER PASS produced no render layers"
            for layer in layers:
                data = layer.get("geojson") or layer.get("data") or {}
                assert data.get("type") == "FeatureCollection", layer
                assert data.get("features"), layer

            # DELIVER stores the render metadata as an explicit artifact; the
            # ref-only checkpoint must not regain the retired inline field.
            render_artifacts = load_artifact(state, "render_artifacts") or {}
            assert render_artifacts.get("layer_count", 0) > 0, render_artifacts
            for key in ("static_preview", "interactive_map"):
                artifact = render_artifacts.get(key) or {}
                assert artifact.get("status") == "completed", render_artifacts
                assert Path(artifact.get("path", "")).exists(), artifact
            preview_path = Path(render_artifacts["static_preview"]["path"])
            map_path = Path(render_artifacts["interactive_map"]["path"])
            assert preview_path.name == "planning_preview.png"
            assert map_path.name == "planning_map.html"
            assert preview_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            assert "complete_planned_landuse" in map_path.read_text(encoding="utf-8")
            from PIL import Image

            with Image.open(preview_path) as preview:
                assert preview.width >= 1200
                assert preview.height >= 800
    finally:
        stop_memory_sampler.set()
        memory_thread.join(timeout=5)
        asyncio.run(teardown())
