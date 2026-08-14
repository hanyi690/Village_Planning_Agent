"""Opt-in real-L1 resolution coverage: every typed L1 location -> entity/extent.

Drives the graph through the L1 layer only (the graph parks at the L1 HUMAN
review right after the L1 aggregate), then rebuilds the authoritative context
(name backfill + evidence index) and tallies how many typed L1 facts resolve to
a KG entity with a spatial extent, an extent alone, or a geometry-only entity.
The L2/L3/classification chain is deliberately NOT exercised — the only
acceptance here is that every reported location can be located in space.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest


def _live_llm_configured() -> bool:
    provider = os.getenv("LLM_PROVIDER", "minimax").lower()
    if provider in {"zhipuai", "zhipu", "glm"}:
        return bool(os.getenv("ZHIPUAI_API_KEY"))
    if provider in {"dashscope", "qwen"}:
        return bool(os.getenv("DASHSCOPE_API_KEY"))
    if provider in {"minimax", "minimaxai", "mini-max"}:
        return bool(os.getenv("MINIMAX_API_KEY"))
    return bool(os.getenv("OPENAI_API_KEY"))


def _render_coverage_report(cov) -> str:
    lines = [
        f"L1 resolution coverage: {cov.summary()}",
        "",
        f"{'location':<24} {'role':<10} {'dim':<18} {'status':<16} bsms  entity",
    ]
    for detail in sorted(cov.details, key=lambda d: (d["status"], d["role"])):
        entity = (detail["entity_ref"] or "").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        lines.append(
            f"{detail['name'][:24]:<24} {detail['role'][:10]:<10} "
            f"{detail['dimension_key'][:18]:<18} {detail['status']:<16} "
            f"{detail['bsms']:>3}   {entity[:40]}"
        )
    return "\n".join(lines)


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(
        not _live_llm_configured(),
        reason="live LLM credentials are not configured; set the provider API key",
    ),
]


@pytest.mark.timeout(2400)
def test_real_l1_resolution_coverage(sqlite_db, pipeline_reset, monkeypatch):
    setup, teardown = sqlite_db

    async def _llm_preflight() -> None:
        from app.infrastructure.llm.factory import create_llm
        llm = create_llm(
            temperature=0, max_tokens=8, streaming=False,
            request_timeout=30, max_retries=0,
        )
        await asyncio.wait_for(llm.ainvoke("只回复 OK"), timeout=30)

    try:
        asyncio.run(_llm_preflight())
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"real LLM preflight failed: {type(exc).__name__}: {exc}")

    test_engine = asyncio.run(setup())
    import app.database.engine as db_engine
    test_db_path = Path(test_engine.url.database).resolve()
    monkeypatch.setattr(db_engine, "DB_PATH", test_db_path)
    monkeypatch.setattr(db_engine, "CHECKPOINT_DB_PATH", test_db_path)
    monkeypatch.setattr(db_engine, "get_db_path", lambda: test_db_path)
    monkeypatch.setattr(db_engine, "_checkpointer", None)
    monkeypatch.setattr(db_engine, "_checkpointer_initialized", False)
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    monkeypatch.setattr(PlanningRuntimeService, "_checkpointer", None)
    monkeypatch.setattr(PlanningRuntimeService, "_graph", None)
    monkeypatch.setattr(PlanningRuntimeService, "_initialized", False)

    run_root = (Path.cwd() / ".run-tmp" / f"real-l1-{uuid4().hex}").resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_root))
    from app.infrastructure.paths import reset_run_tmp_root_cache

    reset_run_tmp_root_cache()
    from fastapi.testclient import TestClient
    import app.main as main

    async def no_db_init() -> bool:
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
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        def get_state_values(session: str) -> dict:
            return client.portal.call(
                PlanningRuntimeService.aget_state_values, session
            ) or {}

        response = client.post(
            "/api/v1/sessions",
            data={
                "project_name": "金田村 L1 地点解析覆盖率验收",
                "village_name": "金田村",
                "village_data": report,
                "step_mode": "true",
            },
            files=files,
        )
        assert response.status_code == 201, response.text
        session_id = response.json()["session_id"]
        (run_root / session_id).mkdir(parents=True, exist_ok=True)
        print(f"[REAL-L1] session={session_id}", flush=True)

        # step_mode parks at the layer-completion interrupt BEFORE the L1
        # aggregate, so the typed L1Snapshot artifact does not exist yet.  The
        # test only needs the snapshot, so auto-approve that gate exactly once;
        # the aggregate then runs and persists the artifact.
        deadline = time.monotonic() + 1500.0
        state = {}
        approved_step_gate = False
        while time.monotonic() < deadline:
            state = get_state_values(session_id)
            refs = (state.get("artifact_refs") or {}).get("l1_snapshot")
            if refs:
                break
            if not approved_step_gate and state.get("paused_stage"):
                client.portal.call(
                    PlanningRuntimeService.resume_from_interrupt,
                    session_id,
                    {"action": "approve"},
                )
                approved_step_gate = True
                print(
                    f"[REAL-L1] auto-approved step-mode gate paused={state.get('paused_stage')!r}",
                    flush=True,
                )
            time.sleep(1.0)
        assert state, f"session state was never checkpointed: {session_id}"
        assert (state.get("artifact_refs") or {}).get("l1_snapshot"), (
            "L1Snapshot artifact not produced within 1500s; "
            f"phase={state.get('phase')!r}, paused={state.get('paused_stage')!r}, "
            f"fatal={state.get('fatal_error')!r}"
        )

        from app.infrastructure.artifacts.runtime import load_artifact
        from app.contracts.domain.l1_contracts import L1Snapshot

        snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
        assert snapshot is not None, state.get("artifact_refs")
        assert len(getattr(snapshot, "location_facts", []) or []) > 0, (
            "L1Snapshot produced zero typed location facts; "
            "observations JSON did not compile"
        )

        # Rebuild the authoritative context through the production bootstrap
        # path (name backfill + evidence index).
        from app.infrastructure.context.planning_context_factory import build_planning_context
        from app.workflow.layers.context_bootstrap import _hydrate_l1_spatial_facts

        context = client.portal.call(build_planning_context, session_id, "", True, True, None)
        context.location_facts = list(getattr(snapshot, "location_facts", []) or [])
        client.portal.call(_hydrate_l1_spatial_facts, state, context)

        from app.evidence.index.resolution_coverage import resolution_coverage

        cov = resolution_coverage(context)
        print("\n" + _render_coverage_report(cov) + "\n", flush=True)
        report_path = run_root / session_id / "l1-resolution-coverage.txt"
        report_path.write_text(_render_coverage_report(cov), encoding="utf-8")
        print(f"[REAL-L1] coverage report: {report_path}", flush=True)

        min_rate = float(os.getenv("RESOLUTION_COVERAGE_MIN", "0.85"))
        assert cov.total > 0, "no typed L1 location facts to resolve"
        assert cov.extent_rate >= min_rate, (
            f"L1 location resolution below threshold min={min_rate:.0%} "
            f"{cov.summary()} report={report_path}"
        )
