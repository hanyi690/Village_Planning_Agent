"""真实 fixture 端到端：L1 锚点接地 → 地名解析结果 + 地图渲染（供 minimax 图像审查）。

用 mvp_village fixture（金田村）的真实 GIS + 报告名（园寨/田坑…、122乡道、金田河、
祠堂@社前村）验证：ground_anchors 不留下不可解析的地点，且能产出准确 BSM/几何。
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
OUTPUT = Path(__file__).parents[3] / "output" / "grounding_review_20260814.png"

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


def _real_observations() -> list[dict]:
    """从真实报告抽取的观察（村/路/水/设施）。"""
    villages = ["园寨", "田坑", "社前", "分水", "清明", "塘笃", "长塘", "炉池", "肩丰", "营仔", "新山", "黄竹"]
    obs = [
        {
            "fact_type": "spatial_entity",
            "entity_type": "自然村",
            "name": v,
            "locator": {"place_names": [v], "relation": "自然村"},
            "description": f"{v}自然村",
            "scale": "",
        }
        for v in villages
    ]
    obs.append({
        "fact_type": "spatial_entity",
        "entity_type": "现状分区",
        "name": "金田村",
        "locator": {"place_names": ["金田村"], "relation": "规划范围"},
        "description": "金田村村庄规划范围",
        "scale": "",
    })
    obs.append({
        "fact_type": "spatial_entity",
        "entity_type": "地物",
        "name": "南粤古驿道",
        "locator": {"place_names": ["肩丰", "炉池"], "relation": "沿古驿道"},
        "description": "南粤古驿道沿线保护",
        "scale": "1500m",
    })
    obs.extend([
        {
            "fact_type": "spatial_entity",
            "entity_type": "道路",
            "name": "122乡道",
            "locator": {"place_names": ["园寨", "田坑"], "relation": "东西走向；金田村唯一东西向道路"},
            "description": "对外交通主要道路",
            "scale": "",
        },
        {
            "fact_type": "spatial_entity",
            "entity_type": "水系",
            "name": "金田河",
            "locator": {"place_names": ["金田村"], "relation": "西南至东北贯穿金田村；汇入石窟河"},
            "description": "村内主要河流",
            "scale": "",
        },
        {
            "fact_type": "spatial_entity",
            "entity_type": "现状设施",
            "name": "祠堂",
            "locator": {"place_names": ["社前村"], "relation": "位于社前村"},
            "description": "客家祠堂",
            "scale": "3处",
        },
        {
            "fact_type": "spatial_entity",
            "entity_type": "水系",
            "name": "石窟河",
            "locator": {"place_names": ["村界西南"], "relation": "金田河汇入"},
            "description": "镇域河流",
            "scale": "",
        },
    ])
    return obs


def _parcel_centroid(p) -> tuple:
    import shapely.geometry as sg

    geom = getattr(p, "geometry", None) or {}
    if not isinstance(geom, dict) or "coordinates" not in geom:
        return None
    try:
        return sg.shape(geom).centroid.coords[0]
    except Exception:
        return None


def _render(anchors, parcels, path: Path, bundle=None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import shapely.geometry as sg

    # Register a real single-file CJK font; setting a family name alone can
    # silently fall back to DejaVu Sans and render Chinese as tofu boxes.
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
    # 道路线
    if bundle is not None:
        for road in (bundle.lines.get("road") if getattr(bundle, "lines", None) else []) or []:
            geom = getattr(road, "geometry", None) or {}
            if isinstance(geom, dict) and geom.get("coordinates"):
                try:
                    g = sg.shape(geom)
                    if g.geom_type in ("LineString", "MultiLineString"):
                        for line in ([g] if g.geom_type == "LineString" else g.geoms):
                            xs, ys = line.xy
                            ax.plot(xs, ys, color="#2a9d8f", linewidth=1.4, alpha=0.8, zorder=3)
                except Exception:
                    pass
    # 行政边界（整个规划范围）
    if bundle is not None:
        boundary = getattr(bundle, "boundary", None)
        if boundary is not None:
            try:
                bg = sg.shape(getattr(boundary, "geometry", None) or {})
                if bg.geom_type == "Polygon":
                    xs, ys = bg.exterior.xy
                    ax.plot(xs, ys, color="#000000", linewidth=2.6, zorder=7)
                    ax.fill(xs, ys, color="#f2f7f2", alpha=0.35, zorder=1)
                elif bg.geom_type == "MultiPolygon":
                    for poly in bg.geoms:
                        xs, ys = poly.exterior.xy
                        ax.plot(xs, ys, color="#000000", linewidth=2.6, zorder=7)
            except Exception:
                pass
    for p in parcels:
        c = _parcel_centroid(p)
        if c is None:
            continue
        code = str(getattr(p, "dlbm", "") or getattr(p, "dlmc", "") or "")
        color = "#f6c453" if code.startswith(("13", "07")) else "#d8e2dc"
        geom = getattr(p, "geometry", None) or {}
        if isinstance(geom, dict):
            try:
                import shapely.geometry as sg

                g = sg.shape(geom)
                if g.geom_type == "Polygon":
                    xs, ys = g.exterior.xy
                    ax.fill(xs, ys, color=color, alpha=0.6, edgecolor="#999999", linewidth=0.3)
            except Exception:
                pass
    role_colors = {
        "village": "#d62828",
        "facility": "#1d3557",
        "road": "#2a9d8f",
        "water": "#0077b6",
        "landmark": "#7b2cbf",
        "unknown": "#555555",
    }
    for a in anchors:
        xy = None
        if a.geometry_ref:
            import re

            m = re.search(r"POINT\(([-\d.eE]+)\s+([-\d.eE]+)\)", a.geometry_ref)
            if m:
                xy = (float(m.group(1)), float(m.group(2)))
        if xy is None and a.source_bsms:
            pts = [_parcel_centroid(p) for p in parcels if str(getattr(p, "bsm", "")) in set(a.source_bsms)]
            pts = [pt for pt in pts if pt]
            if pts:
                xy = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
        if xy is None:
            continue
        color = role_colors.get(a.role, "#555555")
        ax.scatter(*xy, s=60, color=color, zorder=5, edgecolor="white", linewidth=0.6)
        label = f"{a.normalized_name}"
        if a.best_effort:
            label += "?"
        ax.annotate(label, xy, xytext=(4, 4), textcoords="offset points", fontsize=7, color=color)
    ax.set_title("L1 锚点接地结果（金田村 fixture）· 红=村 蓝=设施 青=道路 深蓝=水系  ?=低置信")
    ax.set_aspect("equal", adjustable="box")
    ax.set_axis_off()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)


@pytest.mark.asyncio
async def test_real_fixture_ground_anchors_and_render(sqlite_db, pipeline_reset):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-grounding-demo-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.data.ingestion.compiler.profiles.l1_observation import (
            _extract_location_facts_from_observations,
        )
        from app.domain.ground.anchors import ground_l1_anchors
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            assign_water_bodies,
            build_landuse_bodies,
            build_village_clusters,
        )

        bundle = await build_session_bundle(sid)
        annotation_bsms = [
            str(getattr(point, "bsm", "") or "")
            for point in bundle.points.get("annotations_current") or []
        ]
        assert annotation_bsms and all(
            len(bsm) == 20 and bsm.startswith("441426108004")
            for bsm in annotation_bsms
        ), annotation_bsms[:3]
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        observations = json.dumps(_real_observations(), ensure_ascii=False)
        facts = _extract_location_facts_from_observations(
            observations,
            dimension_key="socio_economic",
            report_id="rpt-real-v1",
        )
        assert facts, "real observations must compile to location facts"
        village_names = sorted(
            {str(getattr(f, "normalized_name", "")) for f in facts if f.role == "village"}
        )
        water_names = sorted(
            {str(getattr(f, "normalized_name", "")) for f in facts if f.role == "water"}
        )

        clusters = build_village_clusters(parcels)
        water_bodies = build_landuse_bodies(
            parcels, ("水域", "河流", "水库", "坑塘", "沟渠", "水利设施")
        )

        verbatim = "分别为：园寨、田坑、社前、分水、清明、塘笃、长塘、炉池、肩丰、营仔、新山、黄竹"

        class _DispatchLLM:
            """可调度 LLM 占位：聚落/水体映射 prompt → 逐字证据 JSON；其余编号判别 → '1'。"""

            def __init__(self):
                self.mapping = {}

            async def ainvoke(self, prompt):
                if "候选地块" in str(prompt) or "报告摘录" in str(prompt) or "cluster_indexes" in str(prompt):
                    return SimpleNamespace(
                        content=json.dumps(self.mapping, ensure_ascii=False)
                    )
                return SimpleNamespace(content="1")

        dispatch_llm = _DispatchLLM()

        if clusters:
            dispatch_llm.mapping = {
                name: {"cluster_indexes": [i % len(clusters)], "evidence": verbatim}
                for i, name in enumerate(village_names)
            }
            for entry in await assign_villages_to_clusters(
                gazetteer, parcels, village_names, report_text,
                llm=dispatch_llm,
            ):
                gazetteer.upsert(entry)
        if water_bodies:
            dispatch_llm.mapping = {
                name: {"cluster_indexes": [i % len(water_bodies)], "evidence": verbatim}
                for i, name in enumerate(water_names)
            }
            for entry in await assign_water_bodies(
                gazetteer, parcels, water_names, report_text,
                llm=dispatch_llm,
            ):
                gazetteer.upsert(entry)

        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            village_name="金田村",
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
            reports={"current_report": report_text},
        )
        context.current_parcels = lambda: parcels

        anchors = await ground_l1_anchors(context, sid, llm=dispatch_llm, bump=False)

        # 1) 不留下不可解析：每个锚点都有 BSM/几何/实体引用
        assert anchors, "anchors must be produced"
        by_name = {a.normalized_name: a for a in anchors}
        for a in anchors:
            assert a.source_bsms or a.geometry_ref or a.entity_ref, a

        # 2) 准确解析：报告真名（村/路/水/设施）都能定位到 BSM 或实体
        for key in ("园寨", "田坑", "社前", "122乡道", "金田河", "祠堂", "石窟河"):
            assert key in by_name, f"missing anchor for {key}: {sorted(by_name)}"

        # 规划范围识别：金田村 = 行政村/项目范围，绑定到整个行政边界
        scope = [a for a in anchors if a.role == "administrative_village"]
        assert scope and scope[0].normalized_name == "金田村", [a.normalized_name for a in anchors]
        assert scope[0].geometry_ref and scope[0].geometry_ref.startswith("boundary:"), scope[0]

        # 实体级绑定优先：祠堂必须绑定到 bundle 设施点 + 附近地块。
        # EvidenceGraph 只暴露不透明 geometry_ref，真实几何需通过 bundle
        # geometry resolver 按 ref 获取，不能在这里断言 WKT。
        hall = by_name["祠堂"]
        assert hall.geometry_ref and hall.geometry_ref.startswith("bundle://feature/"), hall
        assert hall.source_bsms, hall
        assert not str(hall.geometry_ref or "").startswith("village_anchor"), hall
        # 不透明 geometry_ref 下，以 bundle feature BSM 作为点实体身份；
        # 坐标键是可选的派生索引，不作为跨边界定位凭据。
        assert hall.feature_bsm or hall.source_bsms, hall
        # 拓扑消歧检查必须执行（fixture 的祠点距社前≥1km，无精确命中点时
        # refined=False，仍保留实体级最近祠点，不归并到村质心）
        assert any(
            (t.get("step") or "") == "kg_topology_facility" for t in hall.query_trace
        ), hall.query_trace

        # 祠堂必须绑定到设施点（同坐标=同实体），不是合成 l1_fact/村质心
        assert not hall.entity_ref.startswith("l1_fact"), hall.entity_ref
        assert hall.entity_ref in ("", "poi:祠") or hall.entity_ref.startswith(("poi:", "http")), hall.entity_ref
        assert hall.geometry_ref and hall.geometry_ref.startswith("bundle://feature/"), hall

        # L1 后接地推理注入 KG：村名写在聚落簇实体上
        from rdflib import RDF as _RDF
        from app.infrastructure.kg.ontology import EntityTypes as _ET, PLN as _PLN
        kg_g = getattr(kg, "g", None)
        cluster_names = {
            str(kg_g.value(s, _PLN.name) or "") for s in kg_g.subjects(_RDF.type, _ET.ResidentialCluster)
        }
        assert any("园寨" in n for n in cluster_names), cluster_names
        assert any("社前" in n for n in cluster_names), cluster_names

        # 3) 渲染供 minimax 图像审查
        _render(anchors, parcels, OUTPUT, bundle=bundle)
        print(f"RENDERED {OUTPUT} anchors={len(anchors)} best_effort="
              f"{sum(1 for a in anchors if a.best_effort)}")
        for a in anchors:
            print(f"  ANCHOR {a.normalized_name} role={a.role} bsms={len(a.source_bsms)} "
                  f"conf={a.confidence} best_effort={a.best_effort} entity={a.entity_ref[:60]}")
    finally:
        await teardown()
