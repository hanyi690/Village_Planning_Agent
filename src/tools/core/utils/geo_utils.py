"""
Geo Utilities - 地理计算工具函数

提供距离计算、面积计算等地理计算工具。
"""

import math
from typing import Tuple, List, Any, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Check geopandas availability for area calculations
try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[geo_utils] geopandas not available, area calculations limited")


def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    计算两点之间的 Haversine 距离（米）

    Args:
        coord1: 第一个点的坐标 (lon, lat)
        coord2: 第二个点的坐标 (lon, lat)

    Returns:
        两点之间的距离（米）
    """
    lon1, lat1 = coord1
    lon2, lat2 = coord2

    R = 6371000  # 地球半径（米）

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def calculate_area_km2(geometry: Any) -> float:
    """
    计算几何对象的面积（平方公里）

    Args:
        geometry: Shapely 几何对象

    Returns:
        面积（平方公里）
    """
    if geometry is None:
        return 0.0

    try:
        if GEOPANDAS_AVAILABLE:
            # 使用投影坐标系进行精确计算
            gdf_temp = gpd.GeoDataFrame([{"geometry": geometry}], crs="EPSG:4326")
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            return gdf_proj.geometry.area.sum() / 1_000_000
        else:
            # 后备方案：使用近似计算
            return geometry.area * 111 * 111  # 约 111km/度
    except Exception as e:
        logger.warning(f"[geo_utils] Area calculation failed: {e}")
        # 后备方案
        try:
            return geometry.area * 111 * 111
        except:
            return 0.0


def calculate_areas_batch(geometries: List[Any]) -> List[float]:
    """
    批量计算多个几何对象的面积（平方公里）

    使用单次投影转换提高效率。

    Args:
        geometries: Shapely 几何对象列表

    Returns:
        面积列表（平方公里）
    """
    if not geometries:
        return []

    try:
        if GEOPANDAS_AVAILABLE:
            # 创建单个 GeoDataFrame 包含所有几何对象
            gdf_temp = gpd.GeoDataFrame(
                {"geometry": geometries},
                crs="EPSG:4326"
            )
            # 单次投影转换所有几何对象
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            return [area / 1_000_000 for area in gdf_proj.geometry.area.values]
        else:
            # 后备方案：逐个计算
            return [g.area * 111 * 111 if g else 0.0 for g in geometries]
    except Exception as e:
        logger.warning(f"[geo_utils] Batch area calculation failed: {e}")
        return [g.area * 111 * 111 if g else 0.0 for g in geometries]


__all__ = ['haversine_distance', 'calculate_area_km2', 'calculate_areas_batch']