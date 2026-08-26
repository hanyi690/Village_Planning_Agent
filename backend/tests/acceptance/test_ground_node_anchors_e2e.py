"""GROUND 消费 L1 接地锚点 e2e：ground_aggregate 用 anchored entities 产出候选。

设计 §5.1 闭环：L1 后 ground_anchors 产生 grounded_anchors → GROUND 阶段消费，
spec 未解析时优先落锚点 BSM（同坐标=同实体），并显式 provenance grounded_anchor。
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
async def test_ground_consumes_l1_anchors(sqlite_db, pipeline_reset):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-ground-anchors-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.domain.ground.anchors import ground_l1_anchors
        from app.domain.ground.aggregate import ground_aggregate
        from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
        from app.data.ingestion.compiler.profiles.l1_observation import (
            _extract_location_facts_from_observations,
        )

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        villages = ["园寨", "田坑", "社前", "分水", "清明", "塘笃", "长塘", "炉池", "肩丰", "营仔", "新山", "黄竹"]
        village_source_quote = (
            "金田村隶属广东省梅州市平远县泗水镇，下辖 12 个自然村，分别为："
            "园寨、田坑、社前、分水、清明、塘笃、长塘、炉池、肩丰、营仔、新山、黄竹。"
        )
        obs = [
            {
                "fact_type": "spatial_entity",
                "status": "confirmed",
                "entity_type": "自然村",
                "name": v,
                "locator": {"place_names": [v], "relation": "自然村"},
                "description": f"{v}自然村",
                "scale": "",
                "source_quote": village_source_quote,
            }
            for v in villages
        ]
        obs += [
            {
                "fact_type": "spatial_entity",
                "status": "confirmed",
                "entity_type": "现状设施",
                "name": "祠堂",
                "locator": {"place_names": ["社前村"], "relation": "位于社前村"},
                "description": "客家祠堂",
                "scale": "3处",
                "source_quote": "在金田村下属的社前村，黄竹村，田坑村具有三座祠堂。",
            },
            {
                "fact_type": "spatial_entity",
                "status": "confirmed",
                "entity_type": "水系",
                "name": "金田河",
                "locator": {"place_names": ["金田村"], "relation": "西南至东北贯穿金田村；汇入石窟河"},
                "description": "村内主要河流",
                "scale": "",
                "source_quote": "其中，金田河由西南至东北贯穿金田村，汇入石窟河。",
            },
        ]
        facts = _extract_location_facts_from_observations(
            json.dumps(obs, ensure_ascii=False),
            dimension_key="socio_economic",
            report_id="rpt-ground-anchors",
        )

        class _DispatchLLM:
            async def ainvoke(self, prompt):
                if "候选地块" in str(prompt) or "报告摘录" in str(prompt):
                    verbatim = "分别为：园寨、田坑、社前、分水、清明、塘笃、长塘、炉池、肩丰、营仔、新山、黄竹"
                    from app.spatial.grounding.village_cluster_mapper import build_village_clusters
                    clusters = build_village_clusters(parcels)
                    mapping = {
                        name: {"cluster_indexes": [i % max(len(clusters), 1)], "evidence": verbatim}
                        for i, name in enumerate(villages)
                    }
                    return SimpleNamespace(content=json.dumps(mapping, ensure_ascii=False))
                return SimpleNamespace(content="1")

        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1, village_name="金田村",
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
            reports={"current_report": report_text},
        )
        context.current_parcels = lambda: parcels

        anchors = await ground_l1_anchors(context, sid, llm=_DispatchLLM(), bump=False)
        assert anchors, "L1 anchors must be produced"
        context.grounded_anchors = anchors

        specs = [
            SpatialReferenceSpec(
                type="attributive",
                reference=RefObject(kind="place_name", filter={"label_contains": "祠堂"}),
                target_id="t-hall",
            ),
            SpatialReferenceSpec(
                type="attributive",
                reference=RefObject(kind="place_name", filter={"label_contains": "园寨"}),
                target_id="t-village",
            ),
        ]
        result = ground_aggregate(specs, context)
        print("GROUND candidates:", [(c.site_id, c.target_ref, len(c.source_parcels)) for c in result.candidates])
        assert result.candidates, result.unresolved
        by_target = {c.target_ref: c for c in result.candidates}
        assert "t-village" in by_target, result.unresolved
        assert by_target["t-village"].source_parcels, "园寨 spec must land on anchored parcels"
    finally:
        await teardown()
