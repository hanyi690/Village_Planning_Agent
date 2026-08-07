"""Real SQLite/session-bundle stage audit using the repository fixture data."""

from __future__ import annotations

import json
import hashlib
from uuid import uuid4
from pathlib import Path
from types import SimpleNamespace

import pytest


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"


@pytest.mark.timeout(45)
@pytest.mark.asyncio
async def test_real_session_fixture_runs_all_post_l3_stages(
    sqlite_db, pipeline_reset, monkeypatch, tmp_path,
):
    setup, teardown = sqlite_db
    await setup()
    # All filesystem artifacts for this integration run must be isolated.
    # The application intentionally uses a relative ``.run-tmp`` root, so
    # changing cwd prevents a previous run (or a parallel worker) from
    # reusing the same session/artifact directory.
    monkeypatch.chdir(tmp_path)
    try:
        uploads = []
        for path in sorted((FIXTURE / "gis").glob("*.geojson")):
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            dtype = "landuse_current" if path.stem == "landuse" else path.stem
            uploads.append({
                "file_category": "gis_data",
                "filename": path.name,
                "file_type": "geojson",
                "gis_data_type": dtype,
                "gis_data": data,
            })
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        # Exercise the real multipart session endpoint against the isolated
        # SQLite engine; only the expensive model execution is replaced.
        import app.main as main
        from app.services.runtime import PlanningRuntimeService
        from app.utils.sse_publisher import SSEPublisher

        async def no_db_init():
            return True

        async def no_runtime_init():
            return None

        async def no_background(*args, **kwargs):
            return None

        monkeypatch.setattr("app.database.init_async_db", no_db_init)
        monkeypatch.setattr(PlanningRuntimeService, "initialize", no_runtime_init)
        monkeypatch.setattr(PlanningRuntimeService, "_trigger_planning_execution", no_background)
        monkeypatch.setattr(SSEPublisher, "send_layer_start", lambda *args, **kwargs: None)
        monkeypatch.setattr(SSEPublisher, "send_event", lambda *args, **kwargs: None)
        files = [
            ("village_data_files", (item["filename"], json.dumps(item["gis_data"], ensure_ascii=False).encode("utf-8"), "application/geo+json"))
            for item in uploads
        ]
        with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(main.app) as client:
            response = client.post(
                "/api/sessions",
                data={"project_name": "金田村真实数据审计", "village_name": "金田村", "village_data": report_text},
                files=files,
            )
            assert response.status_code == 200, response.text
            session_id = response.json()["session_id"]

        from app.services.context.planning_context import build_planning_context
        context = await build_planning_context(session_id, village_name="金田村")
        assert context.bundle is not None, "BOOTSTRAP: real GIS bundle missing"

        from app.agent.bootstrap import post_l3_main_nodes as nodes
        from app.agent.plan_state.state import create_initial_state
        from app.modules.schema.contracts.l3_contracts import PlanningIntervention, PlanningProgram
        from app.modules.schema.contracts.workflow_contracts import GateDecision
        from app.modules.schema.contracts.parse_result_contracts import (
            CompilationStatus, IntentCompilationResult,
        )
        from app.modules.schema.contracts.parse_contracts import ProjectTarget, SpatialPlanningIntent
        from app.modules.schema.contracts.grounding_contracts import GroundingResult
        from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
        from app.modules.schema.contracts.parcel_change_contracts import (
            ClassificationRef, ParcelChange, ParcelChangeSet,
        )
        from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport
        from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest
        from app.modules.schema.contracts.validation_report_contracts import ValidationReport

        def gate(stage):
            return GateDecision(stage=stage, passed=True, feedback_route=None, pending_requests=[])

        intervention = PlanningIntervention(intervention_id="real-i1", name="金田村综合整治")
        program = PlanningProgram(artifact_id="real-program", interventions=[intervention])
        typed_intent = SpatialPlanningIntent(
            village_name="金田村",
            project_targets=[ProjectTarget(project_id="real-p1", name="金田村综合整治", category="公共设施")],
        )
        intent_result = IntentCompilationResult(
            typed_intent=typed_intent,
            program_ref=program.artifact_id,
            compilation_status=CompilationStatus.VALIDATED,
            spatial_reference_specs=[],
        )
        changeset = ParcelChangeSet(changes=[ParcelChange(
            bsm="REAL-P1", action="reclassify",
            after_classification=ClassificationRef(system="gb", code="0701", canonical_name="村庄建设用地", source="derived"),
            after_geometry_wkt="POLYGON((0 0,1 0,1 1,0 1,0 0))",
        )], area_conservation_verified=True, geometry_validity_verified=True)

        async def fake_parse(*args, **kwargs):
            return intent_result, [], gate("parse")

        monkeypatch.setattr("app.agent.parse.aggregate.compile_program_async", fake_parse)
        monkeypatch.setattr("app.agent.ground.aggregate.ground_aggregate", lambda *a, **k: GroundingResult())
        monkeypatch.setattr("app.agent.ground.gate.evaluate_ground_gate", lambda result: gate("ground"))
        monkeypatch.setattr("app.agent.select.aggregate.select_aggregate", lambda *a, **k: (SiteSelectionDecision(selected_combination=["REAL-P1"]), []))
        monkeypatch.setattr("app.agent.select.gate.evaluate_select_gate", lambda *a, **k: gate("select"))
        monkeypatch.setattr("app.agent.validate.aggregate.validate_aggregate", lambda *a, **k: ValidationReport(overall_passed=True))
        monkeypatch.setattr("app.agent.validate.gate.evaluate_validate_gate", lambda result: gate("validate"))
        monkeypatch.setattr("app.agent.reconcile.aggregate.reconcile_aggregate", lambda *a, **k: ReconciliationReport())
        monkeypatch.setattr("app.agent.reconcile.gate.evaluate_reconcile_gate", lambda result: gate("reconcile"))
        monkeypatch.setattr("app.agent.deliver.aggregate.deliver_aggregate", lambda *a, **k: DeliveryManifest())
        monkeypatch.setattr("app.agent.deliver.gate.evaluate_deliver_gate", lambda result: gate("deliver"))

        class FakeExecuteGraph:
            async def ainvoke(self, state, config=None):
                return {"parcel_changeset": changeset, "layout_configs": [], "allocated_geojson": {}, "execution_errors": []}

        monkeypatch.setattr(PlanningRuntimeService, "_execute_subgraph", FakeExecuteGraph())
        monkeypatch.setattr(nodes, "_get_cached_context", lambda state: context)

        state = create_initial_state(session_id, "金田村规划", "current_report")
        report_checksum = hashlib.sha256(report_text.encode("utf-8")).hexdigest()
        from app.agent.bootstrap.artifact_runtime import store_artifact
        state.update({
            "context_version": str(context.version),
            "context_fingerprint": getattr(context, "context_fingerprint", "") or "",
            "context_ref": {"session_id": session_id, "version": str(context.version)},
            "artifact_refs": {},
            "uploaded_files": [
                {"filename": "current_report.md", "checksum": report_checksum},
                *[
                    {
                        "filename": item["filename"],
                        "checksum": hashlib.sha256(
                            json.dumps(item["gis_data"], ensure_ascii=False).encode("utf-8")
                        ).hexdigest(),
                    }
                    for item in uploads
                ],
            ],
        })
        # Artifact identity is bound to the context version at write time.
        # Build the fixture ref only after the state carries the canonical
        # PlanningContext reference; the loader must remain fail-closed.
        state["artifact_refs"]["planning_program"] = store_artifact(
            state, "planning_program", "l3", "PlanningProgram", program.model_dump(mode="json")
        )
        for fn in (nodes.parse_node, nodes.ground_node, nodes.select_node):
            delta = await fn(state)
            if delta.get("artifact_refs"):
                delta["artifact_refs"] = {**(state.get("artifact_refs") or {}), **delta["artifact_refs"]}
            state.update(delta)

        # EXECUTE is a formal mounted subgraph: pre_execute maps inputs, the
        # subgraph runs, post_execute maps outputs back and persists artifacts.
        # It must run before VALIDATE (which consumes the changeset).
        pre = await nodes.pre_execute_node(state)
        execute_result = await (PlanningRuntimeService._execute_subgraph).ainvoke(pre, config={})
        state.update(pre)
        state.update(execute_result)
        post = await nodes.post_execute_node(state)
        if post.get("artifact_refs"):
            post["artifact_refs"] = {**(state.get("artifact_refs") or {}), **post["artifact_refs"]}
        state.update(post)

        for fn in (nodes.validate_node, nodes.reconcile_node, nodes.deliver_node):
            delta = await fn(state)
            if delta.get("artifact_refs"):
                delta["artifact_refs"] = {**(state.get("artifact_refs") or {}), **delta["artifact_refs"]}
            state.update(delta)

        from app.services.stage_report import build_stage_report_markdown
        markdown = await build_stage_report_markdown(session_id)
        assert markdown, "DELIVER: stage Markdown was not generated"
        for stage in ("PARSE", "GROUND", "SELECT", "EXECUTE", "VALIDATE", "RECONCILE", "DELIVER"):
            assert f"## {stage} /" in markdown, f"{stage}: missing stage report"
        output = Path(".run-tmp") / session_id / "reports" / "stage-report.md"
        assert output.exists(), "DELIVER: local Markdown report missing"
        assert state["artifact_refs"].get("planned_state"), "EXECUTE: PlannedState ref missing"
        assert state["deliver_gate"].get("passed") is True, "DELIVER: final gate is not PASS"
        assert "gate_route: PASS" in markdown, "DELIVER: stage audit did not record PASS route"
        assert state["artifact_refs"].get("render_layers"), "DELIVER: render layer ref missing"
        assert "render_layers" in markdown, "DELIVER: render layer artifact missing from report"
        assert "FeatureCollection" in markdown, "DELIVER: rendered GeoJSON layer missing"
        with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(main.app) as client:
            api_report = client.get(f"/api/sessions/{session_id}/stage-report.md")
            assert api_report.status_code == 200, api_report.text
            assert api_report.text == markdown, "DELIVER: API/file stage report diverged"
            trace = client.get(f"/api/sessions/{session_id}/positioning-trace")
            assert trace.status_code == 200, trace.text
            assert trace.json().get("reports"), "DELIVER: positioning trace is empty"
    finally:
        await teardown()


async def _resolved_context(context):
    return context
