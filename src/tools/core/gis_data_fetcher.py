"""GIS 数据自动获取封装

基于天地图 API 自动获取 WFS 数据，为 GIS 分析提供数据支撑。
"""

from typing import Dict, Any, Tuple, Optional, List
from ..geocoding import TiandituProvider, WfsService, WFS_LAYERS
from ...utils.logger import get_logger

logger = get_logger(__name__)


class GISDataFetcher:
    """GIS 数据自动获取器"""

    def __init__(self):
        self.provider = TiandituProvider()

    def _get_wfs_service(self) -> WfsService:
        """获取 WFS 服务实例"""
        return WfsService(self.provider.api_key)

    def get_boundary_bbox(
        self,
        location: str,
        buffer_km: float = 5.0
    ) -> Tuple[float, float, float, float]:
        """获取行政边界及扩展 bbox

        Args:
            location: 行政区名称
            buffer_km: 边界缓冲距离（公里）

        Returns:
            bbox: (min_lon, min_lat, max_lon, max_lat)
        """
        result = self.provider.get_boundary(location)

        if not result.success:
            logger.warning(f"[GISDataFetcher] 获取边界失败: {result.error}")
            # 返回默认 bbox（中国中部）
            return (100.0, 20.0, 120.0, 40.0)

        center = result.metadata.get("center", (116.4, 39.9))

        # 计算缓冲 bbox
        buffer_deg = buffer_km / 111.0  # 纬度约 111km/度
        bbox = (
            center[0] - buffer_deg,
            center[1] - buffer_deg,
            center[0] + buffer_deg,
            center[1] + buffer_deg
        )

        return bbox

    def fetch_water_data(
        self,
        location: str,
        buffer_km: float = 5.0,
        max_features: int = 500
    ) -> Dict[str, Any]:
        """获取水系数据

        Args:
            location: 行政区名称
            buffer_km: 缓冲距离
            max_features: 最大要素数量

        Returns:
            水系 GeoJSON 数据
        """
        bbox = self.get_boundary_bbox(location, buffer_km)

        result = self._get_wfs_service().get_water_features(
            bbox,
            include_areas=True,
            include_lines=True,
            include_points=True,
            max_features=max_features
        )

        if not result.success:
            return {
                "success": False,
                "error": result.error,
                "data": None
            }

        return {
            "success": True,
            "geojson": result.data.get("geojson"),
            "metadata": result.metadata
        }

    def fetch_road_data(
        self,
        location: str,
        buffer_km: float = 5.0,
        max_features: int = 500
    ) -> Dict[str, Any]:
        """获取道路数据

        Args:
            location: 行政区名称
            buffer_km: 缓冲距离
            max_features: 最大要素数量

        Returns:
            道路 GeoJSON 数据
        """
        bbox = self.get_boundary_bbox(location, buffer_km)

        result = self._get_wfs_service().get_road_features(
            bbox,
            include_railways=True,
            include_roads=True,
            max_features=max_features
        )

        if not result.success:
            return {
                "success": False,
                "error": result.error,
                "data": None
            }

        return {
            "success": True,
            "geojson": result.data.get("geojson"),
            "metadata": result.metadata
        }

    def fetch_residential_data(
        self,
        location: str,
        buffer_km: float = 5.0,
        max_features: int = 500
    ) -> Dict[str, Any]:
        """获取居民地数据

        Args:
            location: 行政区名称
            buffer_km: 缓冲距离
            max_features: 最大要素数量

        Returns:
            居民地 GeoJSON 数据
        """
        bbox = self.get_boundary_bbox(location, buffer_km)

        result = self._get_wfs_service().get_residential_features(
            bbox,
            include_areas=True,
            include_points=True,
            max_features=max_features
        )

        if not result.success:
            return {
                "success": False,
                "error": result.error,
                "data": None
            }

        return {
            "success": True,
            "geojson": result.data.get("geojson"),
            "metadata": result.metadata
        }

    def fetch_all_gis_data(
        self,
        location: str,
        buffer_km: float = 5.0,
        max_features: int = 500
    ) -> Dict[str, Any]:
        """获取所有 GIS 数据

        Args:
            location: 行政区名称
            buffer_km: 缓冲距离
            max_features: 各类要素最大数量

        Returns:
            包含所有数据的字典
        """
        water_result = self.fetch_water_data(location, buffer_km, max_features)
        road_result = self.fetch_road_data(location, buffer_km, max_features)
        residential_result = self.fetch_residential_data(location, buffer_km, max_features)

        # 获取边界
        boundary_result = self.provider.get_boundary(location)

        return {
            "location": location,
            "buffer_km": buffer_km,
            "boundary": boundary_result.data if boundary_result.success else None,
            "center": boundary_result.metadata.get("center") if boundary_result.success else None,
            "water": water_result,
            "road": road_result,
            "residential": residential_result,
            "available_layers": WFS_LAYERS
        }

    def get_layer_description(self, layer_type: str) -> str:
        """获取图层描述"""
        return WFS_LAYERS.get(layer_type, f"未知图层: {layer_type}")


__all__ = ["GISDataFetcher"]