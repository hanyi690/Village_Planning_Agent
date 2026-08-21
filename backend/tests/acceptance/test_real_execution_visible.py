"""可见进度的真实完整执行：真实 MiniMax LLM 接地 + 人工分类决策 + GROUND/SELECT/EXECUTE。

每阶段显式打印进度；分类决策由"人工评审"（本脚本内显式给出，依据金田村报告
高标农田建设目标 → 水田 GBT21010 1103）。
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"
OUTPUT = Path(__file__).parents[2] / "output" / "execution_result_real_llm.png"

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
async def test_real_execution_visible(sqlite_db, pipeline_reset):
    setup, teardown = sqlite_db
    await setup()
    try:
        t0 = time.time()
        sid = "sess-real-vis-" + uuid.uuid4().hex[:6]
        print(f"[阶段0] 构建金田村 session... ", flush=True)
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.context.planning_context_factory import build_planning_context
        from app.infrastructure.llm.factory import create_flash_llm
        from app.domain.ground.anchors import ground_l1_anchors
        from app.domain.ground.aggregate import ground_aggregate
        from app.domain.allocation.select_service import select_aggregate
        from app.domain.materialization.plan_builder import build_execution_plan
        from app.domain.materialization.execute_state import ExecuteAgentState
        from app.data.ingestion.compiler.profiles.l1_observation import (
            _extract_location_facts_from_observations,
        )
        from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
        from app.contracts.workflow.parse_contracts import FacilityTarget, ProjectTarget, SpatialPlanningIntent
        from app.contracts.artifacts.classification_ref import ClassificationDecision, ClassificationSystem

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        obs = [
            {"entity_type": "自然村", "name": "园寨", "location": "园寨", "relation": "自然村", "description": "园寨自然村", "scale": ""},
            {"entity_type": "现状设施", "name": "祠堂", "location": "社前村", "relation": "位于社前村", "description": "客家祠堂", "scale": "3处"},
        ]
        facts = _extract_location_facts_from_observations(
            json.dumps(obs, ensure_ascii=False),
            dimension_key="socio_economic",
            report_id="rpt-real-vis",
        )
        context = await build_planning_context(sid, village_name="金田村", include_reports=True)
        context.location_facts = facts
        context.kg = kg
        context.gazetteer = gazetteer
        context.reports = {"current_report": report_text}
        parcels = list(context.current_parcels() or [])

        print(f"[阶段1] 真实 MiniMax 锚点接地（约1-2分钟）...", flush=True)
        llm = create_flash_llm(max_tokens=500, temperature=0.1)
        anchors = await ground_l1_anchors(context, sid, llm=llm, bump=False)
        print(f"  -> 锚点 {len(anchors)} 个；园寨 bsms={len(next((a for a in anchors if a.normalized_name=='园寨'), SimpleNamespace(source_bsms=[])).source_bsms)}", flush=True)

        print(f"[阶段2] GROUND：spec → GroundingResult...", flush=True)
        grounding = ground_aggregate(
            [
                SpatialReferenceSpec(type="attributive", reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}), target_id="t-hall"),
                SpatialReferenceSpec(type="attributive", reference=RefObject(kind="place_name", filter={"label_contains": "园寨"}), target_id="p-1"),
            ],
            context,
        )
        print(f"  -> 候选 {len(grounding.candidates)} 个", flush=True)

        print(f"[阶段3] SELECT：项目+设施落位（含我的分类决策：高标农田→水田 1103）...", flush=True)
        village_anchor = next((a for a in anchors if a.normalized_name == "园寨"), None)
        project_bsms = list(village_anchor.source_bsms[:8] if village_anchor else [])
        intent = SpatialPlanningIntent(
            facilities=[FacilityTarget(target_id="t-hall", type="公共服务设施", action="new", location_hint="社前村")],
            site_area_targets=[
                ProjectTarget(
                    project_id="p-1", name="高标准农田建设", category="农田水利",
                    materialization_role="project_footprint", action="new", area_ha=0.2,
                    location_hint="园寨", candidate_bsms=project_bsms,
                    classification_decision=ClassificationDecision(
                        target_id="p-1", code_system=ClassificationSystem.GBT21010,
                        candidate_codes=["1103"], selected_code="1103",
                        evidence_refs=["human-review:高标农田建设目标→水田"],
                        status="resolved",
                    ),
                )
            ],
        )
        decision, briefs = select_aggregate(grounding, intent, context)
        print(f"  -> 决策: {[(a.target_id, a.status) for a in decision.target_assignments]}", flush=True)
        plan = build_execution_plan(intent, decision, briefs, run_id=sid, context_version="1")
        print(f"  -> 执行计划: {[(t.target_id, str(t.worker_type)) for t in plan.worker_tasks]}", flush=True)

        print(f"[阶段4] EXECUTE：物化地块变更...", flush=True)
        from app.domain.materialization.execute_agent import build_execute_agent_graph
        exec_state = ExecuteAgentState(
            session_id=sid, village_name="金田村", spatial_workspace=context.workspace,
            site_selection=decision, land_design_briefs=list(plan.land_design_briefs or []),
            execution_plan=plan, kg_session_ref="",
        )
        result = await build_execute_agent_graph(checkpointer=None).ainvoke(
            exec_state, config={"configurable": {"thread_id": sid}}
        )
        changeset = result.get("parcel_changeset")
        changed_bsms = []
        if changeset is not None:
            for ch in list(getattr(changeset, "changes", None) or []):
                if isinstance(ch, dict):
                    changed_bsms.extend(str(b) for b in [ch.get("bsm"), *list(ch.get("derived_from_bsms") or [])] if b)
                else:
                    changed_bsms.extend(str(b) for b in [getattr(ch, "bsm", None), *list(getattr(ch, "derived_from_bsms", None) or [])] if b)
        changed_bsms = list(dict.fromkeys(changed_bsms))
        print(f"  -> changeset 变更数={len(changed_bsms)} 变更地块示例={changed_bsms[:3]}", flush=True)
        assert changed_bsms, result.get("execution_errors")

        print(f"[阶段5] 渲染执行结果...", flush=True)
        from test_complete_execution_render import _render_execution  # noqa: F401
        render_parcels = list(bundle.polygons.get("landuse_current") or [])
        _render_execution(
            render_parcels,
            changed_bsms,
            OUTPUT,
            boundary=getattr(bundle, "boundary", None),
            planned_state=result.get("planned_state"),
        )
        print(f"[完成] 真实执行 + 渲染产出: {OUTPUT}（总耗时 {time.time()-t0:.0f}s）", flush=True)
    finally:
        await teardown()
