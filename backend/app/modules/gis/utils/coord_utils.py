"""
Coordinate Utilities - 坐标处理工具函数

提供坐标格式转换和 CRS 投影转换工具。
"""

from typing import Tuple, Optional, List, Any


def ensure_tuple_coord(coord: Any) -> Optional[Tuple[float, float]]:
    """将列表坐标转换为元组坐标（如果需要）"""
    if coord is None:
        return None
    if isinstance(coord, tuple) and len(coord) == 2:
        return coord
    if isinstance(coord, list) and len(coord) == 2:
        return tuple(coord)
    return None


def coords_list_to_tuples(coords: List[List[float]]) -> List[Tuple[float, float]]:
    """将坐标列表转换为元组列表"""
    return [tuple(c) if len(c) == 2 else c for c in coords]


def transform_coord(lon: float, lat: float, target_crs: str) -> Tuple[float, float]:
    """将单个 WGS-84 坐标投影到目标 CRS。

    Uses crs_engine for professional CGCS2000 Gauss-Kruger projection.
    """
    from .crs_engine import _project_point
    return _project_point(lon, lat, target_crs)


def transform_coords_batch(
    coords: List[Tuple[float, float]],
    target_crs: str,
) -> List[Tuple[float, float]]:
    """批量投影 WGS-84 坐标到目标 CRS。"""
    from .crs_engine import _project_point
    return [_project_point(lon, lat, target_crs) for lon, lat in coords]


__all__ = [
    'ensure_tuple_coord', 'coords_list_to_tuples',
    'transform_coord', 'transform_coords_batch',
]