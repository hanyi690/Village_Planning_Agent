"""真实 LLM 接地运行（金田村 fixture + 真实 MiniMax flash）。

证明 ground_anchors 在真实 LLM 路径下可用：聚落/水体映射、名字回填、方位重绑
都走真实 provider（无凭据时跳过，不破坏 CI）。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

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
async def test_ground_anchors_real_llm(sqlite_db, pipeline_reset):
    if not (os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY")):
        pytest.skip("no LLM credentials; real-provider grounding skipped")

    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-real-llm-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.llm.factory import create_flash_llm
        from app.data.ingestion.compiler.profiles.l1_observation import (
            _extract_location_facts_from_observations,
        )
        from app.domain.ground.anchors import ground_l1_anchors

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        villages = ["园寨", "田坑", "社前", "分水", "清明", "塘笃", "长塘", "炉池", "肩丰", "营仔", "新山", "黄竹"]
        obs = [
            {"entity_type": "自然村", "name": v, "location": v, "relation": "自然村", "description": f"{v}自然村", "scale": ""}
            for v in villages
        ]
        obs += [
            {"entity_type": "现状设施", "name": "祠堂", "location": "社前村", "relation": "位于社前村", "description": "客家祠堂", "scale": "3处"},
            {"entity_type": "水系", "name": "金田河", "location": "西南至东北贯穿金田村", "relation": "汇入石窟河", "description": "村内主要河流", "scale": ""},
            {"entity_type": "道路", "name": "122乡道", "location": "园寨至田坑东西走向", "relation": "金田村唯一东西向道路", "description": "对外交通主要道路", "scale": ""},
        ]
        facts = _extract_location_facts_from_observations(
            json.dumps(obs, ensure_ascii=False),
            dimension_key="socio_economic",
            report_id="rpt-real-llm",
        )

        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1, village_name="金田村",
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
            reports={"current_report": report_text},
        )
        context.current_parcels = lambda: parcels

        llm = create_flash_llm(max_tokens=500, temperature=0.1)
        anchors = await ground_l1_anchors(context, sid, llm=llm, bump=False)

        assert anchors, "real-LLM grounding must produce anchors"
        by_name = {a.normalized_name: a for a in anchors}
        for a in anchors:
            assert a.source_bsms or a.geometry_ref or a.entity_ref, a
        for key in ("园寨", "社前", "122乡道", "金田河", "祠堂"):
            assert key in by_name, f"missing {key}: {sorted(by_name)}"
        print(f"REAL_LLM_ANCHORS={len(anchors)} best_effort="
              f"{sum(1 for a in anchors if a.best_effort)}")
        for a in anchors:
            print(f"  A {a.normalized_name} role={a.role} bsms={len(a.source_bsms)} "
                  f"conf={a.confidence} be={a.best_effort}")
    finally:
        await teardown()
