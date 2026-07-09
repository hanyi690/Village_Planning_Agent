"""GIS API 端点 TestClient 测试。

验证 POST /api/dev/gis/spatial-layout 端点在传入 L3 reports 后触发完整流程：
  KG 构建 → 布局生成 → CA refinement → 验证闭环
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """FastAPI TestClient fixture。"""
    return TestClient(app)


class TestGISAPIEndpoints:
    """验证 GIS Dev API 端点。"""

    def test_spatial_layout_endpoint_success_with_reports(self, client: TestClient):
        """POST /api/dev/gis/spatial-layout 应成功触发 full_pipeline（含 reports）。"""
        response = client.post(
            "/api/dev/gis/spatial-layout",
            json={"village_name": "金田村委会"},
        )

        assert response.status_code == 200, \
            f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert data["success"] is True, \
            f"Response success should be True, got: {data}"

        layout_configs = data.get("layout_configs", [])
        assert len(layout_configs) >= 1, \
            f"Expected ≥1 layout config, got {len(layout_configs)}"

        layer_types = {c.get("layerType") for c in layout_configs}
        assert "planning_zone" in layer_types, \
            f"planning_zone layer missing, got: {layer_types}"

        assert "conflicts" in data, "conflicts field missing"
        assert "metric_conflicts" in data["conflicts"]
        assert "constraint_violations" in data["conflicts"]

        assert "kg_built" in data, "kg_built field missing"
        assert data["kg_built"] is True, "KG should be built when reports available"

        assert "timing_ms" in data, "timing_ms field missing"
        assert data["timing_ms"] > 0

    def test_spatial_layout_endpoint_response_structure(self, client: TestClient):
        """验证响应结构完整。"""
        response = client.post(
            "/api/dev/gis/spatial-layout",
            json={"village_name": "金田村委会"},
        )

        assert response.status_code == 200
        data = response.json()

        required_fields = {"success", "layout_configs", "conflicts", "kg_built", "timing_ms"}
        for field in required_fields:
            assert field in data, f"Required field '{field}' missing in response"

        for cfg in data["layout_configs"]:
            assert "layerType" in cfg, "Each config should have layerType"
            assert "geojson" in cfg or cfg.get("features_count") is not None, \
                "Each config should have geojson or features_count"

    def test_spatial_layout_endpoint_planning_zone_has_assigned_zones(
        self, client: TestClient
    ):
        """planning_zone 图层的 features 应有 assigned_zone 属性。"""
        response = client.post(
            "/api/dev/gis/spatial-layout",
            json={"village_name": "金田村委会"},
        )

        assert response.status_code == 200
        data = response.json()

        planning_zone_layer = next(
            (c for c in data["layout_configs"] if c.get("layerType") == "planning_zone"),
            None,
        )
        assert planning_zone_layer is not None, "planning_zone layer missing"

        geojson = planning_zone_layer.get("geojson", {})
        features = geojson.get("features", [])
        assert len(features) > 0, "planning_zone should have features"

        assigned_zones = {
            f.get("properties", {}).get("assigned_zone", "")
            for f in features
        }
        expected_keywords = ["村", "农", "生态"]
        for kw in expected_keywords:
            assert any(kw in zt for zt in assigned_zones if zt), \
                f"assigned_zone should contain '{kw}', got: {assigned_zones}"
