"""GIS 数据自动获取封装

基于天地图 API 自动获取 WFS 数据，为 GIS 分析提供数据支撑。
"""

import re
from typing import Dict, Any, Tuple, Optional, List
from ..geocoding import TiandituProvider, WfsService, WFS_LAYERS
from ...utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 预编译正则表达式 - 地址层级解析
# ==========================================

_VILLAGE_PATTERN = re.compile(r'([^县市省镇]+村)(?![委会])')
_TOWN_PATTERN = re.compile(r'([^县市省]+镇)')
_COUNTY_PATTERN = re.compile(r'([^省市]+县)')
_CITY_PATTERN = re.compile(r'(.+市)')
_PROVINCE_PATTERN = re.compile(r'(.+省)')


class GISDataFetcher:
    """GIS 数据自动获取器"""

    def __init__(self):
        self.provider = TiandituProvider()

    def _get_wfs_service(self) -> WfsService:
        """获取 WFS 服务实例（使用 TiandituProvider 共享的实例）"""
        return self.provider.wfs_service

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
        # 解析地址层级，检测县级以下地址
        hierarchy = self.parse_location_hierarchy(location)
        has_village = hierarchy.get("village")
        has_town = hierarchy.get("town")

        # 县级以下地址：跳过边界 API，使用地理编码中心点
        if has_village or has_town:
            logger.info(f"[GISDataFetcher] 县级以下地址，跳过边界API: {location}")
            center, _ = self.get_village_center(location, buffer_km)
            if center:
                buffer_deg = buffer_km / 111.0
                return (center[0] - buffer_deg, center[1] - buffer_deg,
                        center[0] + buffer_deg, center[1] + buffer_deg)
            # fallback
            logger.warning(f"[GISDataFetcher] 无法获取县级以下中心，使用默认 bbox")
            return (100.0, 20.0, 120.0, 40.0)

        # 正常获取边界（省/市/县）
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

    def parse_location_hierarchy(self, location: str) -> Dict[str, str]:
        """解析地址层级

        从地址字符串中提取省、市、县、镇、村信息。
        支持格式:
        - "平远县泗水镇金田村"
        - "广东省梅州市平远县泗水镇金田村"
        - "金田村" (只有村名)

        Args:
            location: 地址字符串

        Returns:
            包含 province, city, county, town, village 的字典
        """
        hierarchy = {
            "province": "",
            "city": "",
            "county": "",
            "town": "",
            "village": ""
        }

        # 匹配村级地址模式（最后一个村名）
        village_match = _VILLAGE_PATTERN.search(location)
        if village_match:
            hierarchy["village"] = village_match.group(1)

        # 匹配镇级地址模式（最后一个镇名）
        town_match = _TOWN_PATTERN.search(location)
        if town_match:
            hierarchy["town"] = town_match.group(1)

        # 匹配县级地址模式（最后一个县名）
        county_match = _COUNTY_PATTERN.search(location)
        if county_match:
            hierarchy["county"] = county_match.group(1)

        # 匹配市级地址模式
        city_match = _CITY_PATTERN.search(location)
        if city_match:
            hierarchy["city"] = city_match.group(1)

        # 匹配省级地址模式
        province_match = _PROVINCE_PATTERN.search(location)
        if province_match:
            hierarchy["province"] = province_match.group(1)

        return hierarchy

    def is_village_level_location(self, location: str) -> bool:
        """检测是否为村级地址

        Args:
            location: 地址字符串

        Returns:
            是否为村级地址（包含村名）
        """
        return bool(_VILLAGE_PATTERN.search(location))

    def get_village_center(
        self,
        location: str,
        buffer_km: float = 2.0
    ) -> Tuple[Optional[Tuple[float, float]], Dict[str, Any]]:
        """获取村级中心坐标（分层定位策略）

        策略:
        1. 先获取县级边界作为参考
        2. 地理编码定位村级中心
        3. 失败则 POI 搜索定位
        4. 失败则使用县级中心参考

        Args:
            location: 地址字符串
            buffer_km: 缓冲半径

        Returns:
            (center_coordinates, metadata_dict)
        """
        hierarchy = self.parse_location_hierarchy(location)
        village_name = hierarchy.get("village", "")
        county_name = hierarchy.get("county", "")

        if not village_name:
            logger.warning(f"[GISDataFetcher] 未检测到村级地址: {location}")
            return None, {"success": False, "error": "未检测到村级地址"}

        metadata = {
            "location": location,
            "hierarchy": hierarchy,
            "strategy_used": None,
            "county_reference": None
        }

        # Step 1: 获取县级边界作为参考
        county_result = None
        if county_name:
            county_result = self.provider.get_boundary(county_name)
            if county_result.success:
                county_center = county_result.metadata.get("center")
                metadata["county_reference"] = {
                    "county": county_name,
                    "center": county_center
                }
                logger.info(f"[GISDataFetcher] 县级参考: {county_name} center={county_center}")

        # Step 2: 地理编码定位村级中心
        geocode_result = self.provider.geocode(location)
        if geocode_result.success:
            center = (geocode_result.data.get("lon"), geocode_result.data.get("lat"))
            metadata["strategy_used"] = "geocode"
            metadata["formatted_address"] = geocode_result.data.get("formatted_address")
            logger.info(f"[GISDataFetcher] 地理编码定位成功: {center}")
            return center, {"success": True, **metadata}

        # Step 3: POI 搜索定位
        poi_region = county_name if county_name else ""
        poi_result = self.provider.search_poi_in_region(village_name, poi_region, page_size=10)
        if poi_result.success and poi_result.data.get("pois"):
            first_poi = poi_result.data["pois"][0]
            center = (first_poi.get("lon"), first_poi.get("lat"))
            metadata["strategy_used"] = "poi_search"
            metadata["poi_name"] = first_poi.get("name")
            logger.info(f"[GISDataFetcher] POI 搜索定位成功: {center}")
            return center, {"success": True, **metadata}

        # Step 4: 使用县级中心作为参考
        if county_result and county_result.success:
            center = county_result.metadata.get("center")
            metadata["strategy_used"] = "county_fallback"
            metadata["warning"] = "使用县级中心作为参考，村级精度可能不足"
            logger.warning(f"[GISDataFetcher] 使用县级中心参考: {center}")
            return center, {"success": True, **metadata}

        # 全部失败
        metadata["strategy_used"] = "failed"
        metadata["error"] = "无法定位村级中心"
        logger.warning(f"[GISDataFetcher] 无法定位 {location}")
        return None, {"success": False, **metadata}

    def get_boundary_bbox_for_village(
        self,
        location: str,
        buffer_km: float = 2.0
    ) -> Tuple[float, float, float, float]:
        """获取村级边界 bbox（分层定位）

        Args:
            location: 村级地址
            buffer_km: 缓冲距离（村级默认 2km）

        Returns:
            bbox: (min_lon, min_lat, max_lon, max_lat)
        """
        center, metadata = self.get_village_center(location, buffer_km)

        if center is None:
            logger.warning(f"[GISDataFetcher] 无法获取村级中心，使用默认 bbox")
            return (100.0, 20.0, 120.0, 40.0)

        # 计算缓冲 bbox
        buffer_deg = buffer_km / 111.0
        bbox = (
            center[0] - buffer_deg,
            center[1] - buffer_deg,
            center[0] + buffer_deg,
            center[1] + buffer_deg
        )

        logger.info(f"[GISDataFetcher] 村级 bbox: {bbox}, strategy={metadata.get('strategy_used')}")

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
            include_points=False,  # HYDP 不存在于天地图 WFS 服务中
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

        自动检测地址层级，村级地址使用分层定位策略。

        Args:
            location: 行政区名称（支持村级地址）
            buffer_km: 缓冲距离（村级默认建议 2km）
            max_features: 各类要素最大数量

        Returns:
            包含所有数据的字典
        """
        # 检测是否为村级地址
        is_village = self.is_village_level_location(location)

        if is_village:
            # 村级地址使用分层定位策略
            logger.info(f"[GISDataFetcher] 检测到村级地址: {location}")

            center, location_metadata = self.get_village_center(location, buffer_km)

            # 直接用已获取的 center 计算 bbox，避免重复 API 调用
            if center:
                buffer_deg = buffer_km / 111.0
                bbox = (
                    center[0] - buffer_deg,
                    center[1] - buffer_deg,
                    center[0] + buffer_deg,
                    center[1] + buffer_deg
                )
            else:
                bbox = (100.0, 20.0, 120.0, 40.0)  # 默认 bbox

            # 使用村级 bbox 获取数据
            water_result = self._fetch_data_by_bbox("water", bbox, max_features)
            road_result = self._fetch_data_by_bbox("road", bbox, max_features)
            residential_result = self._fetch_data_by_bbox("residential", bbox, max_features)

            return {
                "location": location,
                "buffer_km": buffer_km,
                "is_village_level": True,
                "boundary": None,
                "center": center,
                "village_location_metadata": location_metadata,
                "water": water_result,
                "road": road_result,
                "residential": residential_result,
                "available_layers": WFS_LAYERS
            }
        else:
            # 非村级地址使用原有逻辑
            water_result = self.fetch_water_data(location, buffer_km, max_features)
            road_result = self.fetch_road_data(location, buffer_km, max_features)
            residential_result = self.fetch_residential_data(location, buffer_km, max_features)

            # 获取边界
            boundary_result = self.provider.get_boundary(location)

            return {
                "location": location,
                "buffer_km": buffer_km,
                "is_village_level": False,
                "boundary": boundary_result.data if boundary_result.success else None,
                "center": boundary_result.metadata.get("center") if boundary_result.success else None,
                "water": water_result,
                "road": road_result,
                "residential": residential_result,
                "available_layers": WFS_LAYERS
            }

    def _fetch_data_by_bbox(
        self,
        data_type: str,
        bbox: Tuple[float, float, float, float],
        max_features: int
    ) -> Dict[str, Any]:
        """根据 bbox 获取数据

        Args:
            data_type: 数据类型 (water/road/residential)
            bbox: 边界框
            max_features: 最大要素数量

        Returns:
            数据结果字典
        """
        wfs = self._get_wfs_service()

        if data_type == "water":
            result = wfs.get_water_features(
                bbox,
                include_areas=True,
                include_lines=True,
                include_points=False,  # HYDP 不存在于天地图 WFS 服务中
                max_features=max_features
            )
        elif data_type == "road":
            result = wfs.get_road_features(
                bbox,
                include_railways=True,
                include_roads=True,
                max_features=max_features
            )
        elif data_type == "residential":
            result = wfs.get_residential_features(
                bbox,
                include_areas=True,
                include_points=True,
                max_features=max_features
            )
        else:
            return {"success": False, "error": f"未知数据类型: {data_type}"}

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

    def get_layer_description(self, layer_type: str) -> str:
        """获取图层描述"""
        return WFS_LAYERS.get(layer_type, f"未知图层: {layer_type}")


# ==========================================
# 单例模式 - 全局 GISDataFetcher 实例
# ==========================================

_FETCHER_INSTANCE: Optional[GISDataFetcher] = None


def get_fetcher() -> GISDataFetcher:
    """获取 GISDataFetcher 单例实例

    使用单例模式避免重复创建 TiandituProvider 和 WfsService 实例。

    Returns:
        GISDataFetcher 实例（全局唯一）
    """
    global _FETCHER_INSTANCE
    if _FETCHER_INSTANCE is None:
        _FETCHER_INSTANCE = GISDataFetcher()
        logger.info("[GISDataFetcher] 创建全局单例实例")
    return _FETCHER_INSTANCE


__all__ = ["GISDataFetcher", "get_fetcher"]