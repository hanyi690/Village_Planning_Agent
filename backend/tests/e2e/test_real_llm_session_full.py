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
    return bool(state.get("paused_stage") or state.get("human_review_items"))


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(
        bool(os.getenv("GITHUB_ACTIONS")) and not _live_llm_configured(),
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


@pytest.mark.timeout(1800)
def test_real_llm_session_full_fixture(sqlite_db, pipeline_reset, monkeypatch):
    setup, teardown = sqlite_db
    import asyncio

    async def _llm_preflight() -> None:
        from app.core.llm import create_llm
        llm = create_llm(
            temperature=0,
            max_tokens=8,
            streaming=False,
        )
        await asyncio.wait_for(llm.ainvoke("只回复 OK"), timeout=30)

    try:
        asyncio.run(_llm_preflight())
    except Exception as exc:  # noqa: BLE001 - surface provider configuration clearly
        status = getattr(exc, "status_code", None)
        pytest.fail(
            "real LLM preflight failed before Session creation; "
            f"provider_status={status!r}, error_type={type(exc).__name__}. "
            "Update the configured provider credentials before running the full chain."
        )

    test_engine = asyncio.run(setup())
    import app.database.engine as db_engine
    # The SQLModel fixture and LangGraph checkpointer must use the same
    # temporary file.  Otherwise a "real" session silently writes checkpoints
    # into data/database/village_planning.db and can replay stale state.
    test_db_path = Path(test_engine.url.database).resolve()
    monkeypatch.setattr(db_engine, "DB_PATH", test_db_path)
    monkeypatch.setattr(db_engine, "get_db_path", lambda: test_db_path)
    monkeypatch.setattr(db_engine, "_checkpointer", None)
    monkeypatch.setattr(db_engine, "_checkpointer_initialized", False)
    from app.services.runtime import PlanningRuntimeService
    monkeypatch.setattr(PlanningRuntimeService, "_checkpointer", None)
    monkeypatch.setattr(PlanningRuntimeService, "_graph", None)
    monkeypatch.setattr(PlanningRuntimeService, "_execute_subgraph", None)
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
        monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_root))
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
        with TestClient(main.app) as client:
            response = client.post(
                "/api/sessions",
                data={
                    "project_name": "金田村真实 LLM 全链验收",
                    "village_name": "金田村",
                    "village_data": report,
                },
                files=files,
            )
            assert response.status_code == 200, response.text
            session_id = response.json()["session_id"]
            from app.services.runtime import PlanningRuntimeService

            # A real fixture may legitimately stop at HUMAN when the report
            # names a village that has no BSM/coordinate evidence.  The live
            # acceptance path must exercise the official interrupt/resume
            # contract instead of treating that pause as a deadlock.  This is
            # an explicit operator acknowledgement of the unresolved spatial
            # references, not a synthetic geometry mapping or candidate
            # fallback.  Each resume is bounded and auditable.
            human_resolutions = []
            for _ in range(6):
                current = asyncio.run(PlanningRuntimeService.aget_state_values(session_id)) or {}
                if current.get("human_review_resume_consumed"):
                    # The previous resume is still being replayed.  Do not
                    # submit the same decision twice; wait for a fresh HUMAN
                    # checkpoint (prepare_human_review resets the marker).
                    resume_wait_deadline = time.monotonic() + 45.0
                    while time.monotonic() < resume_wait_deadline:
                        time.sleep(0.5)
                        current = asyncio.run(PlanningRuntimeService.aget_state_values(session_id)) or {}
                        if (
                            not current.get("human_review_resume_consumed")
                            or _post_l3_poll_terminal(current)
                        ):
                            break
                    if current.get("human_review_resume_consumed"):
                        break
                paused_stage = current.get("paused_stage") or ""
                if not paused_stage:
                    # HUMAN preparation/checkpointing can lag the worker's
                    # layer aggregate by a few seconds. Do not mistake that
                    # observable gap for a completed run; wait within the
                    # bounded loop until a pause or a terminal state appears.
                    wait_deadline = time.monotonic() + 45.0
                    while time.monotonic() < wait_deadline:
                        if _post_l3_poll_terminal(current):
                            break
                        time.sleep(0.5)
                        current = asyncio.run(PlanningRuntimeService.aget_state_values(session_id)) or {}
                        paused_stage = current.get("paused_stage") or ""
                        if paused_stage:
                            break
                    if not paused_stage:
                        continue
                review = client.get(f"/api/human-review/{session_id}")
                assert review.status_code == 200, review.text
                review_payload = review.json()
                if not (review_payload.get("pending_items") or []):
                    break
                decision = {
                    "action": "accept",
                    "feedback": (
                        "测试操作员确认继续；未解析村名保留为人工确认项，"
                        "不得视为已有坐标或 BSM 绑定。"
                    ),
                    "acknowledge_unresolved_spatial_references": True,
                    "defer_unresolved_spatial_references": True,
                }
                resolved = client.post(
                    f"/api/human-review/{session_id}/resolve",
                    json={"action": "accept", "decisions": decision},
                )
                assert resolved.status_code == 200, resolved.text
                human_resolutions.append({
                    "stage": review_payload.get("paused_stage"),
                    "item_count": review_payload.get("count"),
                })

            # The runtime may hand work to TaskSupervisor after the FastAPI
            # background callback returns, so poll the checkpoint explicitly
            # instead of assuming TestClient waited for the graph.
            deadline = time.monotonic() + 45.0
            state = {}
            while time.monotonic() < deadline:
                state = asyncio.run(PlanningRuntimeService.aget_state_values(session_id)) or {}
                if state and (
                    _post_l3_poll_terminal(state)
                ):
                    break
                time.sleep(0.5)
            assert state, f"session state was never checkpointed within 45s: {session_id}"
            trace_response = client.get(f"/api/sessions/{session_id}/positioning-trace")
            assert trace_response.status_code == 200, trace_response.text
            trace = trace_response.json()
            report_response = client.get(f"/api/sessions/{session_id}/stage-report.md")
            assert report_response.status_code == 200, report_response.text
            stage_report = report_response.text
            (run_root / session_id / "real-llm-session-report.md").write_text(
                stage_report, encoding="utf-8"
            )
            required_stages = ("PARSE", "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER")
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

            from app.agent.bootstrap.artifact_runtime import load_artifact
            from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
            from app.modules.schema.contracts.execution_plan_contracts import ExecutionOutcome
            from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision

            manifest = load_artifact(state, "delivery_manifest", DeliveryManifest)
            outcome = load_artifact(state, "execution_outcome", ExecutionOutcome)
            selection = load_artifact(state, "site_selection", SiteSelectionDecision)
            assert manifest is not None, state.get("artifact_refs")
            assert outcome is not None, state.get("artifact_refs")
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

            status_response = client.get(f"/api/sessions/{session_id}/status")
            assert status_response.status_code == 200, status_response.text
            status_payload = status_response.json()
            assert status_payload.get("delivery_status") == manifest.delivery_status
            assert status_payload.get("deferral_summary") == manifest.deferral_summary
            assert status_payload.get("diagnostic_terminal") == state.get("diagnostic_terminal") or (
                not manifest.diagnostic_summary and not status_payload.get("diagnostic_terminal")
            )

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

            render_response = client.get(f"/api/sessions/{session_id}/render-layers")
            assert render_response.status_code == 200, render_response.text
            layers = render_response.json().get("layers") or []
            assert layers, "DELIVER PASS produced no render layers"
            for layer in layers:
                data = layer.get("data") or layer.get("geojson") or {}
                assert data.get("type") == "FeatureCollection", layer
                assert data.get("features"), layer

            render_artifacts = state.get("render_artifacts") or {}
            assert render_artifacts.get("layer_count", 0) > 0, render_artifacts
            for key in ("static_preview", "interactive_map"):
                artifact = render_artifacts.get(key) or {}
                assert artifact.get("status") == "completed", render_artifacts
                assert Path(artifact.get("path", "")).exists(), artifact
    finally:
        stop_memory_sampler.set()
        asyncio.run(teardown())
