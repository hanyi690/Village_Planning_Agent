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


def _render_execution(
    parcels,
    changed_bsms,
    path: Path,
    boundary=None,
    change_wkts=None,
    planned_state=None,
) -> dict | None:
    if planned_state is not None:
        return _render_authoritative_execution(
            parcels,
            changed_bsms,
            path,
            boundary=boundary,
            change_wkts=change_wkts,
            planned_state=planned_state,
        )

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


def _render_authoritative_execution(
    parcels,
    changed_bsms,
    path: Path,
    *,
    boundary=None,
    change_wkts=None,
    planned_state=None,
) -> dict:
    """Render the same typed overlays that DELIVER exposes to the frontend."""
    from shutil import copyfile

    from app.domain.delivery.render_layers import build_planned_overlay_layers
    from app.infrastructure.rendering.static_render import render_comparison_preview
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping

    changed = {str(value) for value in changed_bsms if str(value).strip()}

    def feature(geometry, **properties):
        return {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry,
        }

    current_features = []
    changed_features = []
    for parcel in parcels:
        geometry = getattr(parcel, "geometry", None) or {}
        if not isinstance(geometry, dict):
            continue
        bsm = str(getattr(parcel, "bsm", "") or "")
        properties = {
            "bsm": bsm,
            "change_status": "modified" if bsm in changed else "preserved",
            "planning_land_use": "规划变更" if bsm in changed else "现状",
        }
        current_features.append(feature(geometry, **properties))
        if bsm in changed:
            changed_features.append(feature(geometry, **properties))

    for raw_wkt in change_wkts or []:
        try:
            geometry = mapping(shapely_wkt.loads(raw_wkt))
        except Exception:
            continue
        changed_features.append(
            feature(geometry, change_status="modified", planning_land_use="规划变更")
        )

    layers = [
        {
            "layerType": "current_landuse",
            "layerName": "现状地类",
            "data": {"type": "FeatureCollection", "features": current_features},
            "geojson": {"type": "FeatureCollection", "features": current_features},
        },
        {
            "layerType": "complete_planned_landuse",
            "layerName": "完整期末地类",
            "data": {"type": "FeatureCollection", "features": current_features},
            "geojson": {"type": "FeatureCollection", "features": current_features},
        },
    ]
    if changed_features:
        layers.append({
            "layerType": "planned_changes",
            "layerName": "规划变更地块",
            "color": "#dc2626",
            "data": {"type": "FeatureCollection", "features": changed_features},
            "geojson": {"type": "FeatureCollection", "features": changed_features},
        })
    if boundary is not None:
        geometry = getattr(boundary, "geometry", None) or {}
        if isinstance(geometry, dict):
            layers.append({
                "layerType": "boundary",
                "layerName": "村域边界",
                "color": "#0f172a",
                "data": {"type": "FeatureCollection", "features": [feature(geometry)]},
                "geojson": {"type": "FeatureCollection", "features": [feature(geometry)]},
            })
    layers.extend(build_planned_overlay_layers(planned_state))
    result = render_comparison_preview(layers, str(path.parent), "金田村")
    if result.get("status") != "completed":
        raise AssertionError(f"authoritative render failed: {result}")
    copyfile(result["path"], path)
    return result


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
        # The injected typed stand-in is local and quota-free, but the
        # production budget must still be nonzero for the report→cluster
        # mapping to run.  Real provider calls remain disabled by injection.
        monkeypatch.setattr(settings, "GROUND_MAX_LLM_CALLS", 20)
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
            def with_structured_output(self, schema, **_kwargs):
                class _Runner:
                    async def ainvoke(self, _messages):
                        if schema.__name__ == "_GMappingSet":
                            from app.spatial.grounding.village_cluster_mapper import (
                                build_village_clusters,
                            )

                            clusters = build_village_clusters(parcels)
                            return schema(entries=[{
                                "name": "园寨",
                                "candidate_indexes": [clusters[0].index],
                                "evidence": "园寨",
                            }])
                        return schema(candidate_index=1)

                return _Runner()

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
            site_area_targets=[
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
        render_result = _render_execution(
            render_parcels,
            changed_bsms,
            OUTPUT,
            boundary=boundary,
            change_wkts=change_wkts,
            planned_state=planned_state,
        )
        assert render_result["status"] == "completed"
        assert render_result["planned_point_count"] >= 1
        assert render_result["planned_road_count"] == 0
        assert render_result["missing_outputs"] == ["规划道路"]
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_real_evidence_graph_selects_subgeometry_near_scoped_facility(
    sqlite_db, pipeline_reset
):
    """真实 bundle 上验证设施语义会进入关系选择，而不是只返回一个 BSM。"""
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-real-evidence-relation-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from shapely.geometry import shape
        from shapely.ops import transform
        from pyproj import Transformer

        from app.application.sessions.session_bundle import build_session_bundle
        from app.contracts.domain.l1_contracts import L1LocationFact
        from app.contracts.evidence.source_semantic_contracts import (
            SourceFeatureSemanticDecision,
        )
        from app.contracts.planning.constraint_factor import ConstraintFactor
        from app.contracts.planning.relation_parameters import DistanceParameters
        from app.contracts.spatial.candidate_geometry import CandidateGeometry
        from app.contracts.spatial.grounded_problem import (
            GroundedCandidateDomain,
            GroundedPlanningProblem,
        )
        from app.domain.allocation.scenario_solver import solve_scenario
        from app.domain.relations.reference_features import (
            resolve_relation_reference_features,
        )
        from app.domain.relations.service import RelationEvaluationContext
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
        from app.evidence.retrieval.evidence_graph import EvidenceGraph
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.kg.manager import KGManager
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            build_village_clusters,
        )

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        assert len(parcels) >= 3

        clusters = build_village_clusters(parcels)
        assert clusters
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        class _VillageBindingLLM:
            def with_structured_output(self, schema, **_kwargs):
                class _Runner:
                    async def ainvoke(self, _prompt):
                        return schema(entries=[{
                            "name": "社前",
                            "candidate_indexes": [clusters[min(1, len(clusters) - 1)].index],
                            "evidence": "在金田村下属的社前村",
                        }])

                return _Runner()

        village_entries = await assign_villages_to_clusters(
            gazetteer,
            parcels,
            ["社前"],
            report_text,
            llm=_VillageBindingLLM(),
        )
        for entry in village_entries:
            gazetteer.upsert(entry)

        # 这条 L1 fact 是语义到行政/自然村范围的桥；设施 geometry 仍只从
        # bundle 读取，EvidenceGraph 不持有可执行几何。
        facts = [
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                aliases=["祠堂", "祠"],
                spatial_hint="社前村",
                source_span="现状设施 | 祠堂 | 社前村 | 三座祠堂",
                source_report_ref="report:current",
                dimension_key="historical_culture",
                confidence=0.95,
            )
        ]
        context = SimpleNamespace(
            session_id=sid,
            village_name="金田村",
            version=1,
            kg_version=1,
            gazetteer=gazetteer,
            kg=kg,
            workspace=bundle,
            location_facts=facts,
            l1_snapshot_ref="artifact://l1/real-fixture",
            data_snapshot=SimpleNamespace(digest=bundle.spatial_snapshot_digest()),
        )
        context.source_semantic_decisions = {
            str((getattr(feature, "_raw", {}) or {}).get("source_feature_id")): SourceFeatureSemanticDecision(
                source_feature_id=str((getattr(feature, "_raw", {}) or {}).get("source_feature_id")),
                raw_label="祠",
                semantic_type="祠堂",
                status="accepted",
                authority="inferred_current",
                candidate_ref="l1:fixture:祠堂:entity",
                supporting_fact_refs=["report:current"],
            )
            for feature in list(
                (getattr(bundle, "points", {}) or {}).get("annotations_current") or []
            )
            if str(getattr(feature, "text", "") or "").strip() == "祠"
            and str((getattr(feature, "_raw", {}) or {}).get("source_feature_id") or "").strip()
        }
        context.current_parcels = lambda: parcels
        context.evidence_graph = EvidenceGraph(
            context, index=PlaceEvidenceIndex.build(context)
        )

        scoped = context.evidence_graph.query_facility_bsms("社前村", "祠堂")
        assert scoped.status == "resolved", scoped
        assert scoped.candidates, scoped
        facility = scoped.candidates[0]
        assert facility.feature_bsm or facility.source_bsm
        assert facility.related_parcel_bsms

        # Relation object is an EvidenceGraph identity.  It must be resolved
        # back to the exact bundle feature before geometry evaluation.
        external_ref = facility.entity_ref or "祠堂"
        factor = ConstraintFactor(
            kind="near",
            subject_ref="site-hall-buffer",
            object_ref=external_ref,
            object_ref_kind="entity",
            hard=True,
            evaluator_key="near",
            evidence_refs=["l1:fact:祠堂", *facility.evidence_refs],
            parameters=DistanceParameters(
                max_distance_m=1.0,
                metric="euclidean",
            ),
        )
        resolution = resolve_relation_reference_features(
            context, [factor], scenario_id="scenario:real-fixture"
        )
        assert not resolution.diagnostics, resolution.diagnostics
        external = resolution.features.get(external_ref)
        assert external is not None
        assert external.generation_operation == "relation_bundle_reference"
        assert external.entity_refs
        assert external.feature_bsms or external.source_bsms
        assert external.l1_fact_refs == ["report:current"]
        assert external.bundle_snapshot_digest == bundle.spatial_snapshot_digest()

        # 以真实设施点为参照，选出最近与最远的真实地块，并从各自地块
        # 切一个小的规划子几何；选择只能使用这些子几何，不能回写整块面。
        to_metric = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
        facility_geometry = __import__("shapely.wkt", fromlist=["loads"]).loads(
            external.geometry_wkt
        )
        facility_metric = transform(to_metric, facility_geometry)
        parcel_rows = []
        for parcel in parcels:
            geometry = shape(getattr(parcel, "geometry", None) or {})
            if geometry.is_empty or not geometry.is_valid:
                continue
            metric = transform(to_metric, geometry)
            parcel_rows.append((metric.distance(facility_metric), parcel, geometry))
        parcel_rows.sort(key=lambda row: (row[0], str(getattr(row[1], "bsm", ""))))
        near_distance, near_parcel, near_geometry = parcel_rows[0]
        far_distance, far_parcel, far_geometry = parcel_rows[-1]
        assert far_distance > near_distance

        def _slice(geometry):
            point = geometry.representative_point()
            width = max(min(geometry.bounds[2] - geometry.bounds[0], geometry.bounds[3] - geometry.bounds[1]) * 0.2, 1e-6)
            clipped = geometry.intersection(point.buffer(width))
            return clipped if not clipped.is_empty else geometry

        near_slice = _slice(near_geometry)
        far_slice = _slice(far_geometry)
        near_slice_distance = transform(to_metric, near_slice).distance(facility_metric)
        far_slice_distance = transform(to_metric, far_slice).distance(facility_metric)
        assert far_slice_distance > near_slice_distance
        threshold = (near_slice_distance + far_slice_distance) / 2.0

        def _candidate(target_id, parcel, geometry):
            bsm = str(getattr(parcel, "bsm", "") or "")
            return CandidateGeometry(
                target_id=target_id,
                kind="polygon",
                role="execution_geometry",
                materialization_role="site_footprint",
                wkt=geometry.wkt,
                crs="EPSG:4326",
                granularity="parcel_extent",
                spatial_domain_kind="parcel_extent",
                source_ref=f"bundle:landuse_current:{bsm}",
                source_bsms=[bsm],
                feature_bsms=[bsm],
                evidence_refs=[f"bundle:landuse_current:{bsm}"],
                l1_fact_refs=["l1:fact:祠堂"],
                l1_snapshot_ref="artifact://l1/real-fixture",
                bundle_snapshot_digest=bundle.spatial_snapshot_digest(),
                subgeometry_operation="fixture_centroid_slice",
                generation_operation="select_planning_subgeometry",
                confidence=0.8,
                hard_constraint_status="passed",
            )

        near_candidate = _candidate("site-hall-buffer", near_parcel, near_slice)
        far_candidate = _candidate("site-hall-buffer", far_parcel, far_slice)
        problem = GroundedPlanningProblem(
            baseline_ref="bundle:real-fixture",
            candidate_domains=[
                GroundedCandidateDomain(
                    target_id="site-hall-buffer",
                    candidate_ids=[near_candidate.candidate_id, far_candidate.candidate_id],
                )
            ],
            candidate_geometries=[near_candidate, far_candidate],
            constraint_factors=[
                factor.model_copy(
                    update={
                        "parameters": DistanceParameters(
                            max_distance_m=threshold,
                            metric="euclidean",
                        )
                    }
                )
            ],
            source_artifact_refs=["artifact://evidence/real-fixture"],
        )
        scenario = solve_scenario(
            problem,
            scenario_id="scenario:real-fixture",
            evaluator_context=RelationEvaluationContext(
                scenario_id="scenario:real-fixture",
                reference_features=resolution.features,
            ),
        )
        assert scenario.status == "complete", json.dumps({
            "status": scenario.status,
            "relations": [item.model_dump(mode="json") for item in scenario.relation_satisfactions],
            "findings": [item.model_dump(mode="json") for item in scenario.findings],
        }, ensure_ascii=False)
        assert {
            item.target_id: item.candidate_ids
            for item in scenario.target_selections
        }["site-hall-buffer"] == [near_candidate.candidate_id]
        satisfaction = scenario.relation_satisfactions[0]
        assert satisfaction.status == "satisfied", satisfaction
        selected_feature = next(
            item for item in scenario.feature_intents
            if item.target_id == "site-hall-buffer"
        )
        assert selected_feature.subgeometry_operation == "fixture_centroid_slice"
        assert selected_feature.source_bsms == [str(getattr(near_parcel, "bsm", ""))]
        assert selected_feature.bundle_snapshot_digest == bundle.spatial_snapshot_digest()
    finally:
        await teardown()
