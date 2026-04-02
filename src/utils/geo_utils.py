"""
地理计算工具函数

提供常用的地理空间计算功能。
"""

import math
from typing import Tuple


def haversine_distance(
    point1: Tuple[float, float],
    point2: Tuple[float, float]
) -> float:
    """
    使用 Haversine 公式计算两点间的球面距离

    Args:
        point1: 坐标点 (lon, lat)
        point2: 坐标点 (lon, lat)

    Returns:
        距离（米）
    """
    lon1, lat1 = point1
    lon2, lat2 = point2

    earth_radius = 6371000  # 地球半径（米）

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat / 2) ** 2 + \
        math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius * c


def calculate_total_distance(points: list) -> float:
    """
    计算路径总距离

    Args:
        points: 坐标点列表 [(lon, lat), ...]

    Returns:
        总距离（米）
    """
    if len(points) < 2:
        return 0.0

    total = 0.0
    for i in range(len(points) - 1):
        total += haversine_distance(points[i], points[i + 1])

    return total


__all__ = ["haversine_distance", "calculate_total_distance"]