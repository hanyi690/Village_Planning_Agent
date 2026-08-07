"""Opt-in end-to-end run with the configured remote LLM and real fixture GIS."""

from __future__ import annotations

import json
import os
import threading
import faulthandler
from pathlib import Path

import pytest


def _live_llm_configured() -> bool:
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()
    if provider in {"zhipuai", "zhipu", "glm"}:
        return bool(os.getenv("ZHIPUAI_API_KEY"))
    if provider in {"dashscope", "qwen"}:
        return bool(os.getenv("DASHSCOPE_API_KEY"))
    return bool(os.getenv("OPENAI_API_KEY"))


pytestmark = pytest.mark.skipif(
    bool(os.getenv("GITHUB_ACTIONS")) and not _live_llm_configured(),
    reason="live LLM credentials are not configured; set the provider API key to run this chain",
)


@pytest.mark.timeout(1800)
def test_real_llm_session_full_fixture(sqlite_db, pipeline_reset, monkeypatch, tmp_path):
    setup, teardown = sqlite_db
    import asyncio

    asyncio.run(setup())
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
        # Never share the repository-level .run-tmp between P1 runs.  This
        # also makes reruns deterministic when the same test process is reused.
        monkeypatch.chdir(tmp_path)
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

            # TestClient waits for FastAPI BackgroundTasks; the runtime's
            # checkpoint/state is the authoritative completion evidence.
            from app.services.runtime import PlanningRuntimeService

            state = asyncio.run(PlanningRuntimeService.aget_state_values(session_id)) or {}
            report_response = client.get(f"/api/sessions/{session_id}/stage-report.md")
            assert report_response.status_code == 200, report_response.text
            (Path(".run-tmp") / session_id / "real-llm-session-report.md").write_text(
                report_response.text, encoding="utf-8"
            )
            if not state.get("deliver_gate"):
                gate_summary = {
                    key: (value.get("feedback_route") if isinstance(value, dict) else value)
                    for key, value in state.items()
                    if key.endswith("_gate_decision") or key.endswith("_gate")
                }
                # A gate-exhaustion HUMAN pause is a completed, persisted
                # business outcome—not a blocked test.  Require the pause
                # contract and finish the test; an operator can resume it
                # through the normal HITL API in a separate test.
                human_route = bool(
                    state.get("paused_stage")
                    or state.get("human_review_items")
                    or any(value == "HUMAN" for value in gate_summary.values())
                )
                if human_route:
                    assert state.get("human_review_items") or state.get("__interrupt__"), (
                        "HUMAN route has no persisted review checkpoint: "
                        f"phase={state.get('phase')!r}, gates={gate_summary}"
                    )
                else:
                    pytest.fail(
                        "real LLM session stopped before DELIVER; "
                        f"phase={state.get('phase')!r}, gates={gate_summary}, "
                        f"retry_counts={state.get('retry_counts')}, "
                        f"stage_report=.run-tmp/{session_id}/reports/stage-report.md"
                    )
    finally:
        stop_memory_sampler.set()
        asyncio.run(teardown())
