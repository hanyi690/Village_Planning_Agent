"""P1 单元测试：grounding 空间描述分类器 + 分派器。

覆盖：
  - classify_spatial_description 7 类描述分类
  - resolve_spatial_description 各类型分派（toponym/directional/linear/constraint）
  - _parcel_centroid 修复（单 geometry dict → FeatureCollection）
  - 拓扑 SPARQL 模板注册
"""

from unittest.mock import MagicMock, patch

import pytest


# ── classify_spatial_description ──────────────────────────────────────


class TestClassifySpatialDescription:
    def test_classify_toponym(self):
        from app.modules.spatial_ops.grounding import classify_spatial_description
        assert classify_spatial_description("园寨") == "toponym"
        assert classify_spatial_description("田坑") == "toponym"

    def test_classify_directional(self):
        from app.modules.spatial_ops.grounding import classify_spatial_description
        assert classify_spatial_description("村北") == "directional"
        assert classify_spatial_description("村南") == "directional"
        assert classify_spatial_description("村域中部") == "directional"

    def test_classify_linear(self):
        from app.modules.spatial_ops.grounding import classify_spatial_description
        assert classify_spatial_description("沿金田河") == "linear_water"
        assert classify_spatial_description("沿122乡道") == "linear_road"
        assert classify_spatial_description("沿公王河") == "linear_water"

    def test_classify_constraint(self):
        from app.modules.spatial_ops.grounding import classify_spatial_description
        assert classify_spatial_description("生态边缘区") == "constraint"
        assert classify_spatial_description("生态红线内") == "constraint"

    def test_classify_compound(self):
        from app.modules.spatial_ops.grounding import classify_spatial_description
        assert classify_spatial_description("村北靠近园寨") == "compound"
        assert classify_spatial_description("园寨北部") == "compound"

    def test_classify_empty(self):
        from app.modules.spatial_ops.grounding import classify_spatial_description
        assert classify_spatial_description("") == "empty"
        assert classify_spatial_description(None) == "empty"


# ── _parcel_centroid 修复 ─────────────────────────────────────────────


class TestParcelCentroid:
    def test_parcel_centroid_single_geometry(self):
        """单个 GeoJSON geometry dict 应正确求质心（修复 bug）。"""
        from app.modules.spatial_ops.grounding import _parcel_centroid

        parcel = MagicMock()
        parcel.geometry = {
            "type": "Polygon",
            "coordinates": [[[116.04, 24.81], [116.05, 24.81],
                             [116.05, 24.82], [116.04, 24.82],
                             [116.04, 24.81]]],
        }
        c = _parcel_centroid(parcel)
        assert c is not None
        assert 116.044 < c[0] < 116.046
        assert 24.814 < c[1] < 24.816

    def test_parcel_centroid_none_geometry(self):
        from app.modules.spatial_ops.grounding import _parcel_centroid
        assert _parcel_centroid(MagicMock(geometry=None)) is None


# ── resolve_spatial_description 分派器 ─────────────────────────────────


class TestResolveSpatialDescription:
    def _make_bundle(self):
        from app.modules.schema.types.canonical import VillageBundle
        from app.modules.schema.types.spatial_types import CurrentLandUseParcel

        bundle = VillageBundle(village_name="test")
        parcels = [
            CurrentLandUseParcel(
                bsm=f"BSM{i:03d}",
                dlbm="1100",
                geometry={"type": "Polygon", "coordinates": [[
                    [116.04 + i * 0.001, 24.81], [116.05 + i * 0.001, 24.81],
                    [116.05 + i * 0.001, 24.82], [116.04 + i * 0.001, 24.82],
                    [116.04 + i * 0.001, 24.81]]]},
            )
            for i in range(10)
        ]
        for p in parcels:
            bundle.add(p)
        return bundle

    def test_toponym_with_gazetteer(self):
        from app.modules.spatial_ops.grounding import resolve_spatial_description

        bundle = self._make_bundle()
        gaz = MagicMock()
        entry = MagicMock()
        entry.bsms = ["BSM001", "BSM002"]
        gaz.resolve.return_value = entry

        r = resolve_spatial_description("园寨", bundle, gazetteer=gaz)
        assert r.candidate_bsms == ["BSM001", "BSM002"]
        assert r.query_path == "gazetteer:bsms"

    def test_toponym_gazetteer_miss_falls_back(self):
        from app.modules.spatial_ops.grounding import resolve_spatial_description

        bundle = self._make_bundle()
        gaz = MagicMock()
        gaz.resolve.return_value = None

        r = resolve_spatial_description("园寨", bundle, gazetteer=gaz)
        # gazetteer miss → 退化村中心邻近（非空）
        assert r.candidate_bsms
        assert r.query_path == "geometry:village_center"

    def test_directional_bbox(self):
        from app.modules.spatial_ops.grounding import resolve_spatial_description

        bundle = self._make_bundle()
        r = resolve_spatial_description("村北", bundle)
        assert r.query_path == "geometry:directional_bbox"
        assert r.candidate_bbox is not None

    def test_linear_road_kg(self):
        from app.modules.spatial_ops.grounding import resolve_spatial_description

        bundle = self._make_bundle()
        evidence_index = MagicMock()
        evidence_index.candidate_bsms.return_value = ["BSM001"]
        r = resolve_spatial_description(
            "沿122乡道", bundle, evidence_index=evidence_index
        )
        assert r.query_path == "evidence:linear_touching"
        assert r.candidate_bsms == ["BSM001"]

    def test_linear_water_kg(self):
        from app.modules.spatial_ops.grounding import resolve_spatial_description

        bundle = self._make_bundle()
        evidence_index = MagicMock()
        evidence_index.candidate_bsms.return_value = ["BSM002"]
        r = resolve_spatial_description(
            "沿金田河", bundle, evidence_index=evidence_index
        )
        assert r.query_path == "evidence:linear_touching"
        assert r.candidate_bsms == ["BSM002"]

    def test_empty_desc(self):
        from app.modules.spatial_ops.grounding import resolve_spatial_description

        r = resolve_spatial_description("", self._make_bundle())
        assert r.unresolved_reason


# ── 拓扑 SPARQL 模板注册 ──────────────────────────────────────────────


class TestTopologyTemplatesRegistered:
    def test_execute_queries_registered(self):
        from app.modules.kg.queries import execute_queries

        for q in ["get_parcels_touching_bsm", "get_parcels_intersecting_road",
                  "get_parcels_touching_water", "get_parcels_touching_constraint",
                  "get_village_anchors"]:
            assert q in execute_queries, f"{q} not registered"
            assert execute_queries[q].get("status") == "available"

    def test_sparql_templates_exist(self):
        from app.modules.kg.queries.sparql import QUERY_TEMPLATES

        for q in ["get_parcels_touching_bsm", "get_parcels_intersecting_road",
                  "get_parcels_touching_water", "get_parcels_touching_constraint"]:
            assert q in QUERY_TEMPLATES, f"{q} template missing"


# ── phases.yaml kg_query 配置 ──────────────────────────────────────────


class TestKgQueryConfig:
    def test_l2_kg_query(self):
        from app.config.loader import get_dimension_config

        for dim in ["resource_endowment", "planning_positioning",
                    "development_goals", "planning_strategies"]:
            cfg = get_dimension_config(dim)
            assert cfg is not None
            assert cfg.kg_query == "analysis+shared"

    def test_l3_spatial_kg_query(self):
        from app.config.loader import get_dimension_config

        for dim in ["spatial_structure", "land_use_planning", "settlement_planning",
                    "traffic_planning", "public_service", "ecological"]:
            cfg = get_dimension_config(dim)
            assert cfg is not None
            assert cfg.kg_query == "execute+shared"
