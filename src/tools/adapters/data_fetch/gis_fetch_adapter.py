"""
GIS 数据获取适配器

继承 BaseAdapter，调用 TiandituProvider 获取 GIS 数据
"""

from typing import Dict, Any, Tuple, Optional

from ..base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...geocoding import TiandituProvider
from ....utils.logger import get_logger

logger = get_logger(__name__)


class GISDataFetchAdapter(BaseAdapter):
    """GIS 数据获取适配器"""

    def __init__(self):
        super().__init__()
        self._provider = None

    def validate_dependencies(self) -> bool:
        """检查 requests 库和 API Key"""
        try:
            import requests  # noqa: F401
            from src.core.config import TIANDITU_API_KEY
            return bool(TIANDITU_API_KEY)
        except ImportError:
            logger.warning("[GISDataFetchAdapter] requests 库未安装")
            return False

    def initialize(self) -> bool:
        """初始化 TiandituProvider"""
        try:
            self._provider = TiandituProvider()
            self._status = AdapterStatus.READY
            return True
        except Exception as e:
            self._error_message = str(e)
            logger.error(f"[GISDataFetchAdapter] 初始化失败: {e}")
            return False

    def execute(self, analysis_type: str = "boundary_fetch", **kwargs) -> AdapterResult:
        """执行数据获取"""
        # 确保 Provider 已初始化
        if not self._provider:
            try:
                self._provider = TiandituProvider()
            except Exception as e:
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error=f"Provider 初始化失败: {e}"
                )

        # 根据 analysis_type 分发
        try:
            if analysis_type == "boundary_fetch":
                result = self._boundary_fetch(**kwargs)
            elif analysis_type == "poi_fetch":
                result = self._poi_fetch(**kwargs)
            elif analysis_type == "geocode":
                result = self._geocode(**kwargs)
            elif analysis_type == "reverse_geocode":
                result = self._reverse_geocode(**kwargs)
            elif analysis_type == "wfs_fetch":
                result = self._wfs_fetch(**kwargs)
            elif analysis_type == "route_fetch":
                result = self._route_fetch(**kwargs)
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error=f"未知分析类型: {analysis_type}"
                )

            return AdapterResult(
                success=result.success,
                status=AdapterStatus.SUCCESS if result.success else AdapterStatus.FAILED,
                data=result.data,
                metadata=result.metadata,
                error=result.error
            )

        except Exception as e:
            logger.error(f"[GISDataFetchAdapter] 执行异常: {e}")
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=str(e)
            )

    def _boundary_fetch(self, location: str, level: str = "county", **kwargs) -> Any:
        """获取行政边界"""
        return self._provider.get_boundary(location, level)

    def _poi_fetch(
        self,
        keyword: str,
        center: Tuple[float, float],
        radius: int = 1000,
        region: Optional[str] = None,
        **kwargs
    ) -> Any:
        """POI 搜索"""
        if region:
            return self._provider.search_poi_in_region(keyword, region)
        return self._provider.search_poi(keyword, center, radius)

    def _geocode(self, address: str, **kwargs) -> Any:
        """地理编码"""
        return self._provider.geocode(address)

    def _reverse_geocode(self, lon: float, lat: float, **kwargs) -> Any:
        """逆地理编码"""
        return self._provider.reverse_geocode(lon, lat)

    def _wfs_fetch(
        self,
        layer_type: str,
        bbox: Tuple[float, float, float, float],
        **kwargs
    ) -> Any:
        """WFS 图层获取"""
        return self._provider.get_wfs_data(layer_type, bbox)

    def _route_fetch(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        route_type: str = "driving",
        **kwargs
    ) -> Any:
        """路径规划"""
        return self._provider.plan_route(origin, destination, route_type)

    def get_schema(self) -> Dict[str, Any]:
        """输出 Schema"""
        return {
            "type": "object",
            "properties": {
                "geojson": {"type": "object"},
                "pois": {"type": "array"},
                "center": {"type": "array"},
                "formatted_address": {"type": "string"}
            }
        }


__all__ = ["GISDataFetchAdapter"]