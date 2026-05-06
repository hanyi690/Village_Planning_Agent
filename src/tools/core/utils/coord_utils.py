"""
Coordinate Utilities - 坐标处理工具函数

提供坐标格式转换工具。
"""

from typing import Tuple, Optional, List, Any


def ensure_tuple_coord(coord: Any) -> Optional[Tuple[float, float]]:
    """
    将列表坐标转换为元组坐标（如果需要）

    Args:
        coord: 坐标（可能是列表或元组）

    Returns:
        元组坐标 (lon, lat) 或 None
    """
    if coord is None:
        return None
    if isinstance(coord, tuple) and len(coord) == 2:
        return coord
    if isinstance(coord, list) and len(coord) == 2:
        return tuple(coord)
    return None


def coords_list_to_tuples(coords: List[List[float]]) -> List[Tuple[float, float]]:
    """
    将坐标列表转换为元组列表

    Args:
        coords: 坐标列表 [[lon, lat], ...]

    Returns:
        元组列表 [(lon, lat), ...]
    """
    return [tuple(c) if len(c) == 2 else c for c in coords]


__all__ = ['ensure_tuple_coord', 'coords_list_to_tuples']