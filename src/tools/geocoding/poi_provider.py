"""POI 服务统一接口

提供高德优先策略的 POI 搜索服务：
1. 优先使用高德地图（30 QPS，POI 数据丰富）
2. 失败时回退天地图

公共服务设施搜索使用高德的类型码批量搜索功能。
"""
from typing import Dict, Any, Tuple, Optional, List

from .amap.provider import AmapProvider
from .amap.constants import POI_TYPES_PUBLIC_SERVICE
from .tianditu.provider import TiandituProvider
from ...utils.logger import get_logger

logger = get_logger(__name__)


class POIProvider:
    """POI 服务统一接口 - 高德优先策略"""

    _amap_instance: Optional[AmapProvider] = None
    _tianditu_instance: Optional[TiandituProvider] = None

    @classmethod
    def get_amap_provider(cls) -> AmapProvider:
        """获取高德 Provider 实例（单例）"""
        if cls._amap_instance is None:
            cls._amap_instance = AmapProvider()
        return cls._amap_instance

    @classmethod
    def get_tianditu_provider(cls) -> TiandituProvider:
        """获取天地图 Provider 实例（单例）"""
        if cls._tianditu_instance is None:
            cls._tianditu_instance = TiandituProvider()
        return cls._tianditu_instance

    @classmethod
    def search_poi_nearby(
        cls,
        keyword: str,
        center: Tuple[float, float],
        radius: int = 1000,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """周边 POI 搜索（高德优先）

        Args:
            keyword: 搜索关键词
            center: 中心坐标 (lon, lat)
            radius: 搜索半径（米）
            page_size: 每页结果数

        Returns:
            包含 pois、geojson、source 字段的结果字典
        """
        # 1. 优先高德（30 QPS，POI 数据丰富）
        amap = cls.get_amap_provider()
        result = amap.search_poi_nearby(keyword, center, radius, page_size)

        if result.success:
            logger.info(f"[POIProvider] 高德搜索成功: {keyword}, count={len(result.data.get('pois', []))}")
            return {
                "success": True,
                "pois": result.data.get("pois", []),
                "geojson": cls._build_geojson(result.data.get("pois", [])),
                "total_count": result.data.get("total", 0),
                "center": center,
                "radius": radius,
                "source": "amap",
            }

        logger.warning(f"[POIProvider] 高德搜索失败: {result.error}, 回退天地图")

        # 2. 回退天地图
        tianditu = cls.get_tianditu_provider()
        result = tianditu.search_poi(keyword, center, radius, page_size)

        if result.success:
            return {
                "success": True,
                "pois": result.data.get("pois", []),
                "geojson": result.data.get("geojson"),
                "total_count": result.metadata.get("total_count", 0),
                "center": center,
                "radius": radius,
                "source": "tianditu",
            }

        return {
            "success": False,
            "error": result.error or "POI 搜索失败",
            "source": "failed",
        }

    @classmethod
    def search_poi_in_region(
        cls,
        keyword: str,
        region: str,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """区域内 POI 搜索（高德优先）

        Args:
            keyword: 搜索关键词
            region: 区域名称（如城市名）
            page_size: 每页结果数

        Returns:
            POI 结果字典
        """
        # 高德区域内搜索
        amap = cls.get_amap_provider()
        result = amap.search_poi_keyword(keyword, city=region, citylimit=True, page_size=page_size)

        if result.success:
            return {
                "success": True,
                "pois": result.data.get("pois", []),
                "geojson": cls._build_geojson(result.data.get("pois", [])),
                "total_count": result.data.get("total", 0),
                "region": region,
                "source": "amap",
            }

        # 回退天地图
        tianditu = cls.get_tianditu_provider()
        result = tianditu.search_poi_in_region(keyword, region, page_size)

        if result.success:
            return {
                "success": True,
                "pois": result.data.get("pois", []),
                "geojson": result.data.get("geojson"),
                "total_count": result.metadata.get("total_count", 0),
                "region": region,
                "source": "tianditu",
            }

        return {
            "success": False,
            "error": result.error or "POI 搜索失败",
        }

    @classmethod
    def search_public_services(
        cls,
        center: Tuple[float, float],
        radius: int = 5000,
        categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """按类型码搜索公共服务设施（高德专用功能）

        Args:
            center: 中心坐标 (lon, lat)
            radius: 搜索半径（米）
            categories: 要搜索的设施类别列表，默认搜索主要类别
                如 ["幼儿园", "小学", "医院", "超市"]

        Returns:
            按类别组织的公共服务设施结果
        """
        if categories is None:
            # 默认搜索主要公共服务设施
            categories = ["幼儿园", "小学", "中学", "医院", "诊所", "超市", "银行", "公园"]

        amap = cls.get_amap_provider()
        all_pois = {}
        total_count = 0
        features = []

        for category in categories:
            type_code = POI_TYPES_PUBLIC_SERVICE.get(category)
            if not type_code:
                logger.warning(f"[POIProvider] 未知的公共服务类别: {category}")
                continue

            result = amap.search_poi_by_types(type_code, center, radius, page_size=20)

            if result.success:
                pois = result.data.get("pois", [])
                all_pois[category] = pois
                total_count += len(pois)

                # 构建 GeoJSON features
                for poi in pois:
                    features.append({
                        "type": "Feature",
                        "properties": {
                            "name": poi.get("name", ""),
                            "category": category,
                            "type_code": type_code,
                            "address": poi.get("address", ""),
                            "distance": poi.get("distance", 0),
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [poi.get("lon", 0), poi.get("lat", 0)]
                        }
                    })

                logger.info(f"[POIProvider] {category}: {len(pois)} 个结果")

        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        return {
            "success": total_count > 0,
            "pois_by_category": all_pois,
            "geojson": geojson,
            "total_count": total_count,
            "categories_searched": categories,
            "center": center,
            "radius": radius,
            "source": "amap",
        }

    @classmethod
    def search_by_type_codes(
        cls,
        type_codes: str,
        center: Tuple[float, float],
        radius: int = 1000,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """按类型码批量搜索（高德专用）

        Args:
            type_codes: POI 类型码，多个用 | 分隔（如 "141100|141200"）
            center: 中心坐标
            radius: 搜索半径（米）
            page_size: 每页结果数

        Returns:
            POI 结果字典
        """
        amap = cls.get_amap_provider()
        result = amap.search_poi_by_types(type_codes, center, radius, page_size)

        if result.success:
            return {
                "success": True,
                "pois": result.data.get("pois", []),
                "geojson": cls._build_geojson(result.data.get("pois", [])),
                "total_count": result.data.get("total", 0),
                "type_codes": type_codes,
                "center": center,
                "radius": radius,
                "source": "amap",
            }

        return {
            "success": False,
            "error": result.error,
        }

    @classmethod
    def _build_geojson(cls, pois: List[Dict]) -> Dict[str, Any]:
        """从 POI 列表构建 GeoJSON"""
        features = []
        for poi in pois:
            features.append({
                "type": "Feature",
                "properties": {
                    "name": poi.get("name", ""),
                    "address": poi.get("address", ""),
                    "category": poi.get("category", ""),
                    "distance": poi.get("distance", 0),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [poi.get("lon", 0), poi.get("lat", 0)]
                }
            })

        return {
            "type": "FeatureCollection",
            "features": features
        }


__all__ = ["POIProvider"]