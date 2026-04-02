"""
GIS Visualization Adapter 测试

测试 GISVisualizationAdapter 的功能：
- 适配器初始化和依赖检查
- 交互地图渲染
- 分级统计图渲染
- 热力图渲染
- 静态图表渲染
- 智能可视化
- 工具注册和调用
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile


class TestGISVisualizationAdapter:
    """GISVisualizationAdapter 测试类"""

    def test_adapter_initialization(self):
        """测试适配器初始化"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

        adapter = GISVisualizationAdapter()

        # 验证基本属性
        assert adapter.config is not None
        assert adapter._max_retries == 5  # 默认值

    def test_adapter_with_custom_config(self):
        """测试自定义配置初始化"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

        adapter = GISVisualizationAdapter(config={"max_retries": 3})

        assert adapter._max_retries == 3

    def test_get_schema(self):
        """测试 Schema 获取"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

        adapter = GISVisualizationAdapter()
        schema = adapter.get_schema()

        assert schema["adapter_name"] == "GISVisualizationAdapter"
        assert "interactive_map" in schema["supported_analyses"]
        assert "choropleth" in schema["supported_analyses"]
        assert "heatmap" in schema["supported_analyses"]
        assert "static_map" in schema["supported_analyses"]
        assert "smart_visualize" in schema["supported_analyses"]

    def test_execute_missing_data(self):
        """测试缺少数据参数时的错误处理"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter
        from src.tools.adapters.base_adapter import AdapterStatus

        adapter = GISVisualizationAdapter()

        # 测试 interactive_map
        result = adapter.execute(analysis_type="interactive_map")
        assert result.success is False
        assert result.status == AdapterStatus.FAILED
        assert "data" in result.error or "geojson" in result.error

    def test_execute_missing_points_for_heatmap(self):
        """测试热力图缺少 points 参数"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter
        from src.tools.adapters.base_adapter import AdapterStatus

        adapter = GISVisualizationAdapter()

        result = adapter.execute(analysis_type="heatmap")
        assert result.success is False
        assert "points" in result.error

    def test_execute_missing_value_column_for_choropleth(self):
        """测试分级统计图缺少 value_column 参数"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter
        from src.tools.adapters.base_adapter import AdapterStatus

        adapter = GISVisualizationAdapter()

        result = adapter.execute(
            analysis_type="choropleth",
            geojson={"type": "FeatureCollection", "features": []}
        )
        assert result.success is False
        assert "value_column" in result.error

    def test_execute_unsupported_type(self):
        """测试不支持的分析类型"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter
        from src.tools.adapters.base_adapter import AdapterStatus

        adapter = GISVisualizationAdapter()

        result = adapter.execute(analysis_type="unknown_type", data={})
        assert result.success is False
        assert result.status == AdapterStatus.FAILED
        assert "不支持的分析类型" in result.error


class TestFoliumRenderer:
    """FoliumRenderer 测试类"""

    def test_renderer_initialization(self):
        """测试渲染器初始化"""
        from src.tools.adapters.visualization.gis_visualization_adapter import FoliumRenderer

        renderer = FoliumRenderer()

        # 检查可用性（可能因环境而异）
        assert hasattr(renderer, 'is_available')
        assert hasattr(renderer, 'render')
        assert hasattr(renderer, 'render_choropleth')
        assert hasattr(renderer, 'render_heatmap')

    @patch('src.tools.adapters.visualization.gis_visualization_adapter.FoliumRenderer._check_dependencies')
    def test_render_mock(self, mock_check):
        """测试渲染（模拟）"""
        from src.tools.adapters.visualization.gis_visualization_adapter import FoliumRenderer, VisualizationResult
        import sys

        mock_check.return_value = None
        renderer = FoliumRenderer()
        renderer._available = True

        # 模拟 folium
        mock_map = MagicMock()
        mock_map.get_root.return_value.render.return_value = "<html><body>test</body></html>"

        mock_folium = MagicMock()
        mock_folium.Map.return_value = mock_map
        mock_folium.GeoJson = MagicMock()
        mock_folium.GeoJsonTooltip = MagicMock(return_value=None)

        with patch.dict(sys.modules, {'folium': mock_folium}):
            with patch.object(renderer, '_calculate_center', return_value=[30.0, 120.0]):
                with patch.object(renderer, '_has_fields', return_value=False):
                    result = renderer.render({"geojson": {"features": []}})

                    assert result.success is True
                    assert result.format == "html"
                    assert result.content is not None

    def test_render_not_available(self):
        """测试渲染器不可用"""
        from src.tools.adapters.visualization.gis_visualization_adapter import FoliumRenderer

        renderer = FoliumRenderer()
        renderer._available = False

        result = renderer.render({"features": []})

        assert result.success is False
        assert "folium" in result.error

    def test_calculate_center_mock(self):
        """测试中心计算（模拟）"""
        from src.tools.adapters.visualization.gis_visualization_adapter import FoliumRenderer
        import sys

        renderer = FoliumRenderer()

        # 简单 GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "geometry": {
                        "type": "Point",
                        "coordinates": [120.0, 30.0]
                    }
                }
            ]
        }

        # 模拟 geopandas
        mock_gdf = MagicMock()
        mock_geom = MagicMock()
        mock_geom.centroid = MagicMock(y=30.0, x=120.0)
        mock_gdf.geometry.union_all.return_value = mock_geom

        mock_gpd = MagicMock()
        mock_gpd.read_file.return_value = mock_gdf

        with patch.dict(sys.modules, {'geopandas': mock_gpd}):
            center = renderer._calculate_center(geojson)

            assert isinstance(center, list)
            assert len(center) == 2


class TestMatplotlibRenderer:
    """MatplotlibRenderer 测试类"""

    def test_renderer_initialization(self):
        """测试渲染器初始化"""
        from src.tools.adapters.visualization.gis_visualization_adapter import MatplotlibRenderer

        renderer = MatplotlibRenderer()

        assert hasattr(renderer, 'is_available')
        assert hasattr(renderer, 'render')

    def test_render_not_available(self):
        """测试渲染器不可用"""
        from src.tools.adapters.visualization.gis_visualization_adapter import MatplotlibRenderer

        renderer = MatplotlibRenderer()
        renderer._available = False

        result = renderer.render({"features": []})

        assert result.success is False
        assert "matplotlib" in result.error


class TestSmartVisualize:
    """智能可视化测试"""

    def test_analyze_data_characteristics_mock(self):
        """测试数据特征分析（模拟）"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter
        import sys

        adapter = GISVisualizationAdapter()

        # 模拟 GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [120.0, 30.0]},
                    "properties": {"name": "test", "value": 100}
                }
            ]
        }

        # 模拟 geopandas
        mock_gdf = MagicMock()
        mock_gdf.geometry.geom_type.unique.return_value = ['Point']
        mock_gdf.select_dtypes.return_value.columns.tolist.return_value = ['value']
        mock_gdf.__len__ = MagicMock(return_value=1)

        mock_gpd = MagicMock()
        mock_gpd.read_file.return_value = mock_gdf

        with patch.dict(sys.modules, {'geopandas': mock_gpd}):
            analysis = adapter._analyze_data_characteristics(geojson)

            assert analysis["feature_count"] == 1
            assert "Point" in analysis["geometry_types"]

    def test_determine_visualization_type(self):
        """测试可视化类型判断"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

        adapter = GISVisualizationAdapter()

        # 根据提示判断
        assert adapter._determine_visualization_type({}, "热力图") == "heatmap"
        assert adapter._determine_visualization_type({}, "分级统计") == "choropleth"
        assert adapter._determine_visualization_type({}, "静态图表") == "static_map"
        assert adapter._determine_visualization_type({}, "交互地图") == "interactive_map"

        # 根据数据特征判断
        analysis_with_numeric = {"has_numeric_fields": True}
        assert adapter._determine_visualization_type(analysis_with_numeric, "") == "choropleth"

        analysis_with_points = {"has_points": True, "feature_count": 200}
        assert adapter._determine_visualization_type(analysis_with_points, "") == "heatmap"

        # 默认
        assert adapter._determine_visualization_type({}, "") == "interactive_map"

    def test_extract_points_from_geojson(self):
        """测试从 GeoJSON 提取点数据"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

        adapter = GISVisualizationAdapter()

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [120.0, 30.0]}
                },
                {
                    "geometry": {"type": "Point", "coordinates": [121.0, 31.0]}
                }
            ]
        }

        points = adapter._extract_points_from_geojson(geojson)

        assert len(points) == 2
        assert points[0][0] == 30.0  # lat
        assert points[0][1] == 120.0  # lon


class TestVisualizationResultFormatting:
    """结果格式化测试"""

    def test_format_visualization_result_success_html(self):
        """测试 HTML 成功结果的格式化"""
        from src.tools.adapters.tool_wrapper import format_visualization_result
        from src.tools.adapters.base_adapter import AdapterResult, AdapterStatus

        result = AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
                "format": "html",
                "content": "<html>test</html>",
                "file_path": None
            },
            metadata={
                "renderer": "folium",
                "center": [30.0, 120.0],
                "zoom": 10
            }
        )

        formatted = format_visualization_result(result)

        assert "GIS 可视化结果" in formatted
        assert "html" in formatted
        assert "folium" in formatted
        assert "HTML 长度" in formatted
        assert "地图中心" in formatted

    def test_format_visualization_result_success_png(self):
        """测试 PNG 成功结果的格式化"""
        from src.tools.adapters.tool_wrapper import format_visualization_result
        from src.tools.adapters.base_adapter import AdapterResult, AdapterStatus

        result = AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
                "format": "png",
                "content": None,
                "file_path": "/tmp/test.png"
            },
            metadata={
                "renderer": "matplotlib",
                "title": "Test Map"
            }
        )

        formatted = format_visualization_result(result)

        assert "png" in formatted
        assert "matplotlib" in formatted
        assert "/tmp/test.png" in formatted
        assert "Test Map" in formatted

    def test_format_visualization_result_failure(self):
        """测试失败结果的格式化"""
        from src.tools.adapters.tool_wrapper import format_visualization_result
        from src.tools.adapters.base_adapter import AdapterResult, AdapterStatus

        result = AdapterResult(
            success=False,
            status=AdapterStatus.FAILED,
            data={},
            metadata={},
            error="渲染失败"
        )

        formatted = format_visualization_result(result)

        assert "可视化生成失败" in formatted
        assert "渲染失败" in formatted


class TestToolRegistration:
    """工具注册测试"""

    def test_adapter_registered_in_factory(self):
        """测试适配器注册到工厂"""
        from src.tools.adapters import get_adapter_factory

        factory = get_adapter_factory()

        adapters = factory.list_available_adapters()

        # GIS Visualization 应该已注册
        assert "gis_visualization" in adapters or "gis_viz" in adapters

    def test_tool_registered_in_registry(self):
        """测试工具注册到 ToolRegistry"""
        from src.tools.registry import ToolRegistry

        tools = ToolRegistry.list_tools()

        # gis_visualization 应该已注册
        assert "gis_visualization" in tools

    def test_tool_execution_mock(self):
        """测试工具执行（模拟）"""
        from src.tools.registry import ToolRegistry

        # 获取工具（如果存在）
        tool_func = ToolRegistry.get_tool("gis_visualization")
        if tool_func:
            # 模拟执行
            with patch('src.tools.adapters.visualization.gis_visualization_adapter.GISVisualizationAdapter') as mock_adapter:
                mock_instance = MagicMock()
                mock_adapter.return_value = mock_instance

                mock_result = MagicMock()
                mock_result.success = True
                mock_result.data = {"format": "html", "content": "<html>test</html>"}
                mock_result.metadata = {"renderer": "folium"}
                mock_instance.run.return_value = mock_result

                result = tool_func({
                    "data": {"features": []},
                    "analysis_type": "interactive_map"
                })
                assert result is not None


# ==========================================
# 集成测试（需要实际依赖）
# ==========================================

@pytest.mark.skipif(
    True,  # 默认跳过，需要实际环境
    reason="需要 folium 和 geopandas 实际安装"
)
class TestGISVisualizationIntegration:
    """集成测试"""

    def test_real_interactive_map(self):
        """真实交互地图测试"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

        adapter = GISVisualizationAdapter()

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [120.0, 30.0]},
                    "properties": {"name": "Test Point"}
                }
            ]
        }

        result = adapter.run(analysis_type="interactive_map", data=geojson)

        assert result.success is True
        assert result.data.get("format") == "html"
        assert result.data.get("content") is not None

    def test_real_smart_visualize(self):
        """真实智能可视化测试"""
        from src.tools.adapters.visualization.gis_visualization_adapter import GISVisualizationAdapter

        adapter = GISVisualizationAdapter()

        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "geometry": {"type": "Polygon", "coordinates": [[[120, 30], [121, 30], [121, 31], [120, 31], [120, 30]]]},
                    "properties": {"name": "Test Area", "value": 100}
                }
            ]
        }

        result = adapter.run(analysis_type="smart_visualize", data=geojson)

        assert result.success is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])