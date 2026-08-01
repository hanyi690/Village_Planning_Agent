"""B 子任务：BridgeAdvisor 单测（llm=None 确定性路径，无网络）。"""
import asyncio

import pytest

from app.agent.explore.bridge_advisor import (
    BridgeAdvisor,
    SpatialCognitionBrief,
    format_brief_section,
)
from app.modules.schema.types.base import PolygonFeature
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentAnnotation


def _boundary_polygon():
    return PolygonFeature(
        geometry={
            "type": "MultiPolygon",
            "coordinates": [[[[116.00, 24.80], [116.10, 24.80], [116.10, 24.84], [116.00, 24.84], [116.00, 24.80]]]],
        },
        layer_type="admin_area",
    )


class _FakeKG:
    village_name = "金田村"


async def _fake_resolve_bundle(session_id: str):
    bundle = VillageBundle(village_name="金田村")
    bundle.add(_boundary_polygon())
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.047, 24.850]},
            layer_type="current_annotation", text="八社村", category="村名",
        ),
    )
    return bundle


def test_point_in_polygon_ray_casting():
    from app.modules.spatial_ops.geometry import point_in_polygon

    poly = {
        "type": "MultiPolygon",
        "coordinates": [[[[116.00, 24.80], [116.10, 24.80], [116.10, 24.84], [116.00, 24.84], [116.00, 24.80]]]],
    }
    assert point_in_polygon((116.05, 24.835), poly) is True    # 村内
    assert point_in_polygon((116.047, 24.850), poly) is False   # 村外（八社村实测点）
    assert point_in_polygon((115.996, 24.812), poly) is False   # 村外（上举村实测点）


def test_village_boundary_geometry_finds_admin_areas():
    from app.modules.spatial_ops.geometry import village_boundary_geometry

    bundle = VillageBundle(village_name="金田村")
    bundle.add(_boundary_polygon())
    assert village_boundary_geometry(bundle) is not None


def test_compose_dim_brief_separates_internal_and_external_villages(monkeypatch):
    import app.agent.explore.bridge_advisor as ba
    import app.tools.access.shared as shared

    monkeypatch.setattr(shared, "resolve_bundle", _fake_resolve_bundle)
    monkeypatch.setattr(shared, "session_kg", lambda sid: _FakeKG())

    advisor = BridgeAdvisor(session_id="sess-brief2")
    brief = asyncio.run(advisor.compose_dim_brief("land_use", 1))

    assert isinstance(brief, SpatialCognitionBrief)
    assert "八社村" not in brief.relevant_entities   # 村外不进 relevant
    assert brief.external_villages == ["八社村"]      # 明确标为村外
    section = format_brief_section(brief)
    assert "毗邻行政村（村外，非本村居民点）" in section


def test_compose_dim_brief_no_session_returns_empty_safe(monkeypatch):
    import app.agent.explore.bridge_advisor as ba
    import app.tools.access.shared as shared

    monkeypatch.setattr(shared, "resolve_bundle", _fake_resolve_bundle)
    monkeypatch.setattr(shared, "session_kg", lambda sid: None)

    advisor = BridgeAdvisor(session_id="sess-nokg")
    brief = asyncio.run(advisor.compose_dim_brief("traffic", 1))
    assert isinstance(brief, SpatialCognitionBrief)


def test_format_brief_section_contains_entities():
    brief = SpatialCognitionBrief(
        village_overview="金田村，总面积200公顷，共660个地块",
        spatial_pattern="村庄沿公王河呈组团式布局",
        spatial_constraints="永久基本农田81.43公顷",
        relevant_entities="田坑自然村、黄竹自然村",
        focus_hints=["关注田坑耕地集中区"],
        kg_confidence=0.8,
    )
    section = format_brief_section(brief)
    assert section.startswith("**【EXPLORE 空间基础（供分析参考）】**")
    assert "田坑自然村" in section
    assert "0.8" in section
