"""阶段级完整执行 e2e：GROUND 接地产物 → SELECT → EXECUTE 计划。

证明后续阶段已适配：ground_aggregate 产出的 GroundingResult 被 select_aggregate
消费 → SiteSelectionDecision → build_execution_plan → ExecutionPlan（含 worker
任务），全链在真实金田村 fixture 几何上运行。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"

_LAYER_TYPES = {
    "admin_boundary_line.geojson": "admin_boundary_line",
    "annotation.geojson": "annotation",
    "boundary.geojson": "boundary",
    "construction_zone.geojson": "construction_zone",
    "ecological_protection.geojson": "ecological_protection",
    "farmland_protection.geojson": "farmland_protection",
    "geological_hazard_points.geojson": "geological_hazard_points",
    "historical_protection.geojson": "historical_protection",
    "landuse.geojson": "landuse_current",
    "road.geojson": "road",
}


def _uploads() -> list[dict]:
    ups = [{
        "file_category": "village_data",
        "filename": "current_report.md",
        "original_filename": "current_report.md",
        "content_type": "text/markdown",
        "file_type": "md",
        "parsed_text": (FIXTURE / "current_report.md").read_text(encoding="utf-8"),
    }]
    for path in sorted((FIXTURE / "gis").glob("*.geojson")):
        ups.append({
            "file_category": "gis_data",
            "filename": path.name,
            "original_filename": path.name,
            "content_type": "application/geo+json",
            "file_type": "geojson",
            "file_size": path.stat().st_size,
            "gis_data": json.loads(path.read_text(encoding="utf-8")),
            "gis_data_type": _LAYER_TYPES[path.name],
        })
    return ups


@pytest.mark.asyncio
async def test_select_execute_consume_grounded_anchors(sqlite_db, pipeline_reset):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-select-exec-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.domain.ground.anchors import ground_l1_anchors
        from app.domain.ground.aggregate import ground_aggregate
        from app.domain.allocation.select_service import select_aggregate
        from app.domain.materialization.plan_builder import build_execution_plan
        from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
        from app.contracts.workflow.parse_contracts import FacilityTarget, SpatialPlanningIntent
        from app.data.ingestion.compiler.profiles.l1_observation import (
            _extract_location_facts_from_observations,
        )

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        obs = [
            {"entity_type": "自然村", "name": "园寨", "location": "园寨", "relation": "自然村", "description": "园寨自然村", "scale": ""},
            {"entity_type": "现状设施", "name": "祠堂", "location": "社前村", "relation": "位于社前村", "description": "客家祠堂", "scale": "3处"},
        ]
        facts = _extract_location_facts_from_observations(
            json.dumps(obs, ensure_ascii=False),
            dimension_key="socio_economic",
            report_id="rpt-select-exec",
        )

        class _DispatchLLM:
            async def ainvoke(self, prompt):
                if "候选地块" in str(prompt) or "报告摘录" in str(prompt):
                    from app.spatial.grounding.village_cluster_mapper import build_village_clusters
                    clusters = build_village_clusters(parcels)
                    verbatim = "园寨"
                    mapping = {"园寨": {"cluster_indexes": [0], "evidence": verbatim}}
                    return SimpleNamespace(content=json.dumps(mapping, ensure_ascii=False))
                return SimpleNamespace(content="1")

        from app.infrastructure.context.planning_context_factory import build_planning_context

        context = await build_planning_context(
            sid, village_name="金田村", include_reports=True,
        )
        context.location_facts = facts
        context.kg = kg
        context.workspace = bundle
        context.gazetteer = gazetteer
        context.reports = {"current_report": report_text}
        context.current_parcels = lambda: parcels

        anchors = await ground_l1_anchors(context, sid, llm=_DispatchLLM(), bump=False)
        assert anchors

        specs = [
            SpatialReferenceSpec(type="attributive",
                                 reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}),
                                 target_id="t-hall"),
            SpatialReferenceSpec(type="attributive",
                                 reference=RefObject(kind="place_name", filter={"label_contains": "园寨"}),
                                 target_id="t-village"),
        ]
        grounding = ground_aggregate(specs, context)
        assert grounding.candidates, grounding.unresolved

        intent = SpatialPlanningIntent(
            facilities=[
                FacilityTarget(target_id="t-hall", type="公共服务设施", action="new", location_hint="社前村"),
            ],
        )
        decision, briefs = select_aggregate(grounding, intent, context)
        print("SELECT assignments:", [(a.target_id, a.selected_bsm or a.bsms[:3] if hasattr(a, "bsms") else "", a.status) for a in getattr(decision, "target_assignments", [])][:5])
        assert decision.target_assignments, "SELECT must assign the grounded facility candidate"

        plan = build_execution_plan(
            intent, decision, briefs,
            run_id=sid, context_version="1",
        )
        print("EXECUTE tasks:", [(t.target_id, str(t.worker_type)) for t in plan.worker_tasks][:5])
        assert plan.worker_tasks, "EXECUTE plan must contain worker tasks"
    finally:
        await teardown()
