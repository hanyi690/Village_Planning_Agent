"""完整执行 e2e：GROUND→SELECT→EXECUTE（materialization）→ 渲染执行结果。

在真实金田村 fixture 上：锚点接地 → GroundingResult → SiteSelectionDecision →
ExecutionPlan → EXECUTE 子图（facility worker）→ parcel_changeset / planned_state，
并用 matplotlib 渲染"现状 + 规划变更"执行结果图，供 minimax 视觉 MCP 检验。
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
OUTPUT = Path(__file__).parents[2] / "output" / "execution_result_v2.png"

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


def _render_execution(parcels, changed_bsms, path: Path, boundary=None, change_wkts=None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shapely.geometry as sg

    import matplotlib.font_manager as fm

    cjk_font_path = next(
        (
            candidate
            for candidate in (
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/NotoSansSC-VF.ttf",
                "C:/Windows/Fonts/Deng.ttf",
            )
            if Path(candidate).exists()
        ),
        None,
    )
    if cjk_font_path:
        fm.fontManager.addfont(cjk_font_path)
        cjk_font_name = fm.FontProperties(fname=cjk_font_path).get_name()
        plt.rcParams["font.family"] = cjk_font_name
        plt.rcParams["font.sans-serif"] = [cjk_font_name]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(13, 11))
    if boundary is not None:
        try:
            bg = sg.shape(getattr(boundary, "geometry", None) or {})
            polys = bg.geoms if bg.geom_type == "MultiPolygon" else [bg]
            for poly in polys:
                xs, ys = poly.exterior.xy
                ax.plot(xs, ys, color="#000000", linewidth=2.6, zorder=7)
        except Exception:
            pass
    changed = set(changed_bsms)
    n_changed = 0
    for p in parcels:
        geom = getattr(p, "geometry", None) or {}
        if not isinstance(geom, dict):
            continue
        try:
            g = sg.shape(geom)
            polys = g.geoms if g.geom_type == "MultiPolygon" else ([g] if g.geom_type == "Polygon" else [])
            if not polys:
                continue
            bsm = str(getattr(p, "bsm", "") or "")
            is_changed = bsm in changed
            for poly in polys:
                if poly.is_empty:
                    continue
                xs, ys = poly.exterior.xy
                ax.fill(xs, ys, color="#f59e0b" if is_changed else "#d8e2dc",
                        alpha=0.85 if is_changed else 0.55, edgecolor="#333" if is_changed else "#aaa",
                        linewidth=0.8 if is_changed else 0.3, zorder=5 if is_changed else 2)
            if is_changed:
                n_changed += 1
        except Exception:
            pass
    # 合并目标水田：醒目橙色面 + 粗描边（变更核心输出）
    from shapely.wkt import loads as wkt_loads
    for wkt in list(change_wkts or []):
        try:
            mg = wkt_loads(wkt)
            polys = mg.geoms if getattr(mg, "geom_type", "") == "MultiPolygon" else [mg]
            for poly in polys:
                xs, ys = poly.exterior.xy
                ax.fill(xs, ys, color="#f59e0b", alpha=0.75, edgecolor="#dc2626",
                        linewidth=2.5, zorder=8)
        except Exception:
            pass
    if n_changed:
        # 变更区质心加醒目标记，便于视觉检验
        import math
        cxs, cys = [], []
        for p in parcels:
            if str(getattr(p, "bsm", "") or "") not in changed:
                continue
            geom = getattr(p, "geometry", None) or {}
            try:
                gg = sg.shape(geom)
                for poly in (gg.geoms if gg.geom_type == "MultiPolygon" else [gg]):
                    c = poly.centroid
                    cxs.append(c.x); cys.append(c.y)
            except Exception:
                pass
        if cxs:
            cx, cy = sum(cxs)/len(cxs), sum(cys)/len(cys)
            ax.scatter([cx], [cy], s=320, marker="*", color="#dc2626", zorder=9,
                       edgecolor="white", linewidth=1.2)
            ax.annotate("高标准农田建设(8源地块合并→水田)", (cx, cy),
                        xytext=(10, 10), textcoords="offset points", fontsize=10,
                        color="#dc2626", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#dc2626", alpha=0.9))
    ax.set_title(f"EXECUTE 执行结果：现状（灰绿）+ 规划变更地块（橙，{n_changed} 块）")
    try:
        from matplotlib.patches import Patch as _Patch

        ax.legend(
            handles=[
                _Patch(facecolor="#d8e2dc", edgecolor="#aaa", label="现状地块"),
                _Patch(facecolor="#f59e0b", edgecolor="#dc2626", label="规划变更(高标农田)"),
            ],
            loc="upper right", fontsize=9, framealpha=0.9,
        )
    except Exception:
        pass
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


@pytest.mark.asyncio
async def test_complete_execution_and_render(sqlite_db, pipeline_reset, monkeypatch):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-complete-exec-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.context.planning_context_factory import build_planning_context
        from app.domain.ground.anchors import ground_l1_anchors
        from app.domain.ground.aggregate import ground_aggregate
        import app.core.settings as settings

        # This acceptance test verifies deterministic GROUND -> EXECUTE
        # materialization and rendering. Do not let an ambiguous resolver
        # branch create a real provider request and turn a render test into a
        # multi-minute network test; the production LLM path is covered by the
        # provider integration tests.
        monkeypatch.setattr(settings, "GROUND_MAX_LLM_CALLS", 0)
        from app.domain.allocation.select_service import select_aggregate
        from app.domain.materialization.plan_builder import build_execution_plan
        from app.domain.materialization.execute_state import ExecuteAgentState
        from app.domain.materialization.planned_state_builder import changeset_to_planned_state
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
            report_id="rpt-complete-exec",
        )

        class _DispatchLLM:
            async def ainvoke(self, prompt):
                if "候选地块" in str(prompt) or "报告摘录" in str(prompt):
                    from app.spatial.grounding.village_cluster_mapper import build_village_clusters
                    clusters = build_village_clusters(parcels)
                    return SimpleNamespace(content=json.dumps(
                        {"园寨": {"cluster_indexes": [0], "evidence": "园寨"}},
                        ensure_ascii=False,
                    ))
                return SimpleNamespace(content="1")

        context = await build_planning_context(sid, village_name="金田村", include_reports=True)
        context.location_facts = facts
        context.kg = kg
        context.gazetteer = gazetteer
        context.reports = {"current_report": report_text}
        # 保留真实 context.workspace（SpatialWorkspace），EXECUTE 图需要它
        parcels = list(context.current_parcels() or [])

        anchors = await ground_l1_anchors(context, sid, llm=_DispatchLLM(), bump=False)
        assert anchors

        grounding = ground_aggregate(
            [
                SpatialReferenceSpec(type="attributive",
                                     reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}),
                                     target_id="t-hall"),
                SpatialReferenceSpec(type="attributive",
                                     reference=RefObject(kind="place_name", filter={"label_contains": "园寨"}),
                                     target_id="t-village"),
                SpatialReferenceSpec(type="attributive",
                                     reference=RefObject(kind="place_name", filter={"label_contains": "园寨"}),
                                     target_id="p-1"),
            ],
            context,
        )
        assert grounding.candidates, grounding.unresolved

        # 项目目标（如 高标准农田建设）→ project_worker 物化为地块变更；
        # 设施目标（祠堂）→ 点放置。地块变更来自项目，符合用户预期。
        village_anchor = next(
            (a for a in anchors if a.normalized_name == "园寨"), None
        )
        project_anchor = next((a for a in anchors if a.normalized_name == "园寨"), None)
        project_bsms = list(project_anchor.source_bsms[:8] if project_anchor else [])
        assert project_bsms, "园寨 anchor must carry parcels"

        from app.contracts.workflow.parse_contracts import ProjectTarget
        from app.contracts.artifacts.classification_ref import ClassificationDecision, ClassificationSystem

        intent = SpatialPlanningIntent(
            facilities=[FacilityTarget(target_id="t-hall", type="公共服务设施", action="new", location_hint="社前村")],
            project_targets=[
                ProjectTarget(
                    project_id="p-1",
                    name="高标准农田建设",
                    category="农田水利",
                    materialization_role="project_footprint",
                    action="new",
                    area_ha=0.2,
                    location_hint="园寨",
                    candidate_bsms=project_bsms,
                    classification_decision=ClassificationDecision(
                        target_id="p-1",
                        code_system=ClassificationSystem.GBT21010,
                        candidate_codes=["1103"],
                        selected_code="1103",
                        evidence_refs=["grounding:high-standard-farmland"],
                        status="resolved",
                    ),
                )
            ],
        )
        decision, briefs = select_aggregate(grounding, intent, context)
        assert decision.target_assignments
        plan = build_execution_plan(intent, decision, briefs, run_id=sid, context_version="1")
        assert plan.worker_tasks

        # EXECUTE 子图（生产路径照搬 execute_node）
        exec_state = ExecuteAgentState(
            session_id=sid,
            village_name="金田村",
            spatial_workspace=context.workspace,
            site_selection=decision,
            land_design_briefs=list(plan.land_design_briefs or []),
            execution_plan=plan,
            kg_session_ref="",
        )
        from app.domain.materialization.execute_agent import build_execute_agent_graph
        graph = build_execute_agent_graph(checkpointer=None)
        result = await graph.ainvoke(exec_state, config={"configurable": {"thread_id": sid}})
        changeset = result.get("parcel_changeset")
        planned_state = result.get("planned_state")
        print("EXECUTE changeset:", changeset.model_dump(mode="json")["change_count"] if changeset and hasattr(changeset, "model_dump") and "change_count" in changeset.model_dump(mode="json") else (len(getattr(changeset, "changes", []) or []) if changeset else None))
        assert changeset is not None or planned_state is not None, result.get("execution_errors")

        changed_bsms = []
        if changeset is not None:
            for ch in list(getattr(changeset, "changes", None) or []):
                if isinstance(ch, dict):
                    bsms = [ch.get("bsm"), *list(ch.get("derived_from_bsms") or [])]
                else:
                    bsms = [getattr(ch, "bsm", None), *list(getattr(ch, "derived_from_bsms", None) or [])]
                changed_bsms.extend(str(b) for b in bsms if b)
        changed_bsms = list(dict.fromkeys(changed_bsms))

        # 合并后的目标水田几何（after_geometry_wkt）用于醒目渲染
        change_wkts = []
        if changeset is not None:
            for ch in list(getattr(changeset, "changes", None) or []):
                wkt = (ch.get("after_geometry_wkt") if isinstance(ch, dict) else getattr(ch, "after_geometry_wkt", None)) or ""
                if wkt:
                    change_wkts.append(wkt)
        # 渲染执行结果（现状 + 规划变更）；用类型化地块（带 .bsm）
        render_parcels = list(bundle.polygons.get("landuse_current") or [])
        render_bsms = {str(getattr(p, "bsm", "")) for p in render_parcels}
        match = [b for b in changed_bsms if b in render_bsms]
        boundary = getattr(bundle, "boundary", None)
        _render_execution(render_parcels, changed_bsms, OUTPUT, boundary=boundary, change_wkts=change_wkts)
    finally:
        await teardown()
