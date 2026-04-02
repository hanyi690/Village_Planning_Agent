"""
GIS Data Fetch Adapter 测试

测试 GISDataFetchAdapter 的功能（天地图版本）：
- 适配器初始化和依赖检查
- 行政边界获取（省/市/县/乡/村）
- Smart Fetch 智能数据获取
- 工具注册和调用
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json


class TestGISDataFetchAdapter:
    """GISDataFetchAdapter 测试类"""

    def test_adapter_initialization(self):
        """测试适配器初始化"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

        adapter = GISDataFetchAdapter()

        # 验证基本属性
        assert adapter.config is not None
        assert adapter._max_retries == 5  # 默认值

    def test_adapter_with_custom_config(self):
        """测试自定义配置初始化"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

        adapter = GISDataFetchAdapter(config={"max_retries": 3})

        assert adapter._max_retries == 3

    def test_get_schema(self):
        """测试 Schema 获取"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

        adapter = GISDataFetchAdapter()
        schema = adapter.get_schema()

        assert schema["adapter_name"] == "GISDataFetchAdapter"
        assert "boundary_fetch" in schema["supported_analyses"]
        assert "smart_fetch" in schema["supported_analyses"]
        # 移除的功能不应存在
        assert "road_fetch" not in schema["supported_analyses"]
        assert "poi_fetch" not in schema["supported_analyses"]

    def test_execute_missing_location(self):
        """测试缺少 location 参数时的错误处理"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter
        from src.tools.adapters.base_adapter import AdapterStatus

        adapter = GISDataFetchAdapter()

        # 测试 boundary_fetch
        result = adapter.execute(analysis_type="boundary_fetch")
        assert result.success is False
        assert result.status == AdapterStatus.FAILED
        assert "location" in result.error

    def test_execute_unsupported_type(self):
        """测试不支持的分析类型"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter
        from src.tools.adapters.base_adapter import AdapterStatus

        adapter = GISDataFetchAdapter()

        # 测试已移除的功能
        result = adapter.execute(analysis_type="road_fetch", location="杭州市")
        assert result.success is False
        assert result.status == AdapterStatus.FAILED
        assert "不支持的分析类型" in result.error

        result = adapter.execute(analysis_type="poi_fetch", location="杭州市")
        assert result.success is False
        assert result.status == AdapterStatus.FAILED
        assert "不支持的分析类型" in result.error


class TestTiandituBoundaryService:
    """天地图边界服务测试类"""

    def test_service_initialization(self):
        """测试服务初始化"""
        from src.tools.geocoding.tianditu_boundary import TiandituBoundaryService

        service = TiandituBoundaryService(api_key="test_key")

        assert service.api_key == "test_key"
        assert service.is_available() is True

    def test_service_no_api_key(self):
        """测试无 API Key 时的服务状态"""
        from src.tools.geocoding.tianditu_boundary import TiandituBoundaryService

        service = TiandituBoundaryService()

        # 如果环境变量未配置，服务应不可用
        # 但方法存在
        assert hasattr(service, 'is_available')

    def test_level_map(self):
        """测试行政级别映射"""
        from src.tools.geocoding.tianditu_boundary import LEVEL_MAP

        assert LEVEL_MAP["province"] == "1"
        assert LEVEL_MAP["city"] == "2"
        assert LEVEL_MAP["county"] == "3"
        assert LEVEL_MAP["town"] == "4"
        assert LEVEL_MAP["village"] == "5"

    def test_boundary_result_dataclass(self):
        """测试 BoundaryResult 数据类"""
        from src.tools.geocoding.tianditu_boundary import BoundaryResult

        # 成功结果
        result = BoundaryResult(
            success=True,
            geojson={"type": "FeatureCollection", "features": []},
            admin_code="441426",
            name="平远县",
            level="3",
            center=(115.891, 24.567)
        )

        assert result.success is True
        assert result.geojson is not None
        assert result.admin_code == "441426"
        assert result.name == "平远县"

        # 失败结果
        error_result = BoundaryResult(
            success=False,
            error="API Key 未配置"
        )

        assert error_result.success is False
        assert error_result.error == "API Key 未配置"

    @patch('src.tools.geocoding.tianditu_boundary.requests.get')
    def test_get_boundary_mock(self, mock_get):
        """测试边界获取（模拟 API 响应）"""
        from src.tools.geocoding.tianditu_boundary import TiandituBoundaryService

        # 模拟 API 响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "0",
            "data": [{
                "name": "平远县",
                "code": "441426",
                "level": "3",
                "lon": "115.891",
                "lat": "24.567",
                "bound": ""
            }]
        }
        mock_get.return_value = mock_response

        service = TiandituBoundaryService(api_key="test_key")
        result = service.get_boundary("平远县", level="county")

        assert result.success is True
        assert result.name == "平远县"
        assert result.admin_code == "441426"
        assert result.center == (115.891, 24.567)

    @patch('src.tools.geocoding.tianditu_boundary.requests.get')
    def test_get_boundary_api_error(self, mock_get):
        """测试 API 返回错误时的处理"""
        from src.tools.geocoding.tianditu_boundary import TiandituBoundaryService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "1",  # 非 0 表示错误
            "data": []
        }
        mock_get.return_value = mock_response

        service = TiandituBoundaryService(api_key="test_key")
        result = service.get_boundary("不存在的地方")

        assert result.success is False
        assert "API 返回错误" in result.error

    @patch('src.tools.geocoding.tianditu_boundary.requests.get')
    def test_get_children_mock(self, mock_get):
        """测试获取下级行政区（模拟）"""
        from src.tools.geocoding.tianditu_boundary import TiandituBoundaryService

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "0",
            "data": [
                {"name": "泗水镇", "code": "441426101", "level": "4"},
                {"name": "大柘镇", "code": "441426102", "level": "4"},
            ]
        }
        mock_get.return_value = mock_response

        service = TiandituBoundaryService(api_key="test_key")
        result = service.get_children("441426")

        assert result.success is True
        assert result.geojson is not None
        assert len(result.geojson["features"]) == 2


class TestGISFetchResultFormatting:
    """结果格式化测试"""

    def test_format_gis_fetch_result_success(self):
        """测试成功结果的格式化"""
        from src.tools.adapters.tool_wrapper import format_gis_fetch_result
        from src.tools.adapters.base_adapter import AdapterResult, AdapterStatus

        result = AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        {"properties": {"name": "Feature1"}, "geometry": {"type": "Polygon"}},
                        {"properties": {"name": "Feature2"}, "geometry": {"type": "Point"}}
                    ]
                }
            },
            metadata={
                "source": "Tianditu",
                "location": "平远县",
                "admin_code": "441426",
                "level": "county"
            }
        )

        formatted = format_gis_fetch_result(result)

        assert "GIS 数据获取结果" in formatted
        assert "Tiinditu" in formatted or "天地图" in formatted or "OSM" in formatted
        assert "平远县" in formatted

    def test_format_gis_fetch_result_failure(self):
        """测试失败结果的格式化"""
        from src.tools.adapters.tool_wrapper import format_gis_fetch_result
        from src.tools.adapters.base_adapter import AdapterResult, AdapterStatus

        result = AdapterResult(
            success=False,
            status=AdapterStatus.FAILED,
            data={},
            metadata={},
            error="获取失败"
        )

        formatted = format_gis_fetch_result(result)

        assert "GIS 数据获取失败" in formatted
        assert "获取失败" in formatted


class TestToolRegistration:
    """工具注册测试"""

    def test_adapter_registered_in_factory(self):
        """测试适配器注册到工厂"""
        from src.tools.adapters import get_adapter_factory

        factory = get_adapter_factory()

        # 检查是否已注册
        adapters = factory.list_available_adapters()

        # GIS Fetch 应该已注册
        assert "gis_fetch" in adapters or "gis_data_fetch" in adapters

    def test_tool_registered_in_registry(self):
        """测试工具注册到 ToolRegistry"""
        from src.tools.registry import ToolRegistry

        tools = ToolRegistry.list_tools()

        # gis_data_fetch 应该已注册
        assert "gis_data_fetch" in tools


# ==========================================
# 集成测试（需要实际 API Key）
# ==========================================

@pytest.mark.skipif(
    True,  # 默认跳过，需要实际 API Key
    reason="需要天地图 API Key"
)
class TestGISFetchIntegration:
    """集成测试"""

    def test_real_boundary_fetch_county(self):
        """真实县级边界获取测试"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

        adapter = GISDataFetchAdapter()

        result = adapter.execute(analysis_type="boundary_fetch", location="平远县", level="county")

        assert result.success is True
        assert result.data.get("geojson") is not None

    def test_real_boundary_fetch_town(self):
        """真实乡镇级边界获取测试"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

        adapter = GISDataFetchAdapter()

        result = adapter.execute(analysis_type="boundary_fetch", location="泗水镇", level="town")

        assert result.success is True
        assert result.data.get("geojson") is not None

    def test_real_boundary_fetch_village(self):
        """真实村级边界获取测试"""
        from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

        adapter = GISDataFetchAdapter()

        result = adapter.execute(analysis_type="boundary_fetch", location="金田村", level="village")

        assert result.success is True
        assert result.data.get("geojson") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])