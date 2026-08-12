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
    return bool(os.getenv("OPENAI_API_KEY"))


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


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(
        not _live_llm_configured(),
        reason="live LLM credentials are not configured; set the provider API key to run this chain",
    ),
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


@pytest.mark.timeout(1800)
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
        # Keep every run in a unique, workspace-visible directory.  It is not
        # pytest's disposable tmp_path, so operators can inspect the report
        # and PNG/HTML render after the test exits.
        run_root = (Path.cwd() / ".run-tmp" / f"real-llm-{uuid4().hex}").resolve()
        run_root.mkdir(parents=True, exist_ok=True)
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
            (run_root / session_id).mkdir(parents=True, exist_ok=True)
            print(f"[REAL-SESSION] session_create:done session={session_id}", flush=True)
            from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

            # A real fixture may legitimately stop at HUMAN when the report
            # names a village that has no BSM/coordinate evidence.  The live
            # acceptance path must exercise the official interrupt/resume
            # contract instead of treating that pause as a deadlock.  This is
            # an explicit operator acknowledgement of the unresolved spatial
            # references, not a synthetic geometry mapping or candidate
            # fallback.  Each resume is bounded and auditable.
            human_resolutions = []
            checkpoint_reopened = False
            interrupt_event_id = ""
            # L3 summary enrichment is supervised but may finish after the
            # worker checkpoint. Keep polling long enough for the official
            # interrupt payload to become visible before declaring a deadlock.
            # A stalled fingerprint for STALL_WAIT_S is treated as an early
            # termination (graph ENDed or deadlocked) and fails fast instead
            # of exhausting the per-iteration wait budget.
            last_progress = None
            last_progress_at = time.monotonic()
            last_progress = None
            last_progress_at = time.monotonic()
            overall_deadline = time.monotonic() + 1500.0
            state = {}
            terminal = False
            processed_event_ids: set[str] = set()
            while time.monotonic() < overall_deadline:
                current = get_state_values(session_id)
                state = current or state
                if current and _delivery_poll_terminal(current):
                    terminal = True
                    break
                progress = _progress_fingerprint(current)
                now = time.monotonic()
                if progress != last_progress or _graph_has_pending_tasks(client, session_id):
                    last_progress = progress
                    last_progress_at = now
                elif now - last_progress_at > 90.0:
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
                if event_id and event_id in processed_event_ids:
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
                if provider_failure:
                    decision = {
                        "action": "retry",
                        "feedback": "????????????????????",
                    }
                    action = "retry"
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
                        if classification_decisions is None:
                            pytest.fail(
                                "real graph reached classification_decision_required; "
                                "provide operator-approved REAL_CLASSIFICATION_DECISIONS_JSON "
                                "or REAL_CLASSIFICATION_DECISIONS_PATH instead of auto-approving"
                            )
                        decision = {
                            "action": "approve",
                            "feedback": "??????????????????",
                            "classification_decisions": classification_decisions,
                        }
                    else:
                        decision = {
                            "action": "approve",
                            "feedback": (
                                "????????????????????????"
                                "????????? BSM ???"
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
                resolved = client.post(
                    f"/api/v1/sessions/{session_id}/human-review",
                    json={
                        "event_id": review_payload["event_id"],
                        "action": action,
                        "decisions": decision,
                    },
                )
                assert resolved.status_code == 200, resolved.text
                if event_id:
                    processed_event_ids.add(event_id)
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
            assert terminal or time.monotonic() - last_progress_at <= 120.0, (
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
            from app.contracts.domain.selection_contracts import SiteSelectionDecision
            from app.contracts.spatial.spatial_delivery_contracts import DeliverySpatialSnapshot

            manifest = load_artifact(state, "delivery_manifest", DeliveryManifest)
            outcome = load_artifact(state, "execution_result", ExecutionResult)
            selection = load_artifact(state, "site_selection", SiteSelectionDecision)
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
            selected_facility_ids = {
                item.target_id
                for item in (selection.target_assignments if selection else [])
                if item.target_type == "facility" and item.status == "placed"
            }
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
                    item.target_type == "project"
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
        asyncio.run(teardown())
