"""
Geometry Utils - 几何计算工具模块

提供凸包、凹包、多边形化、裁剪等几何计算功能。
"""

# 从原始 vector_editor 导入功能（拆分迁移阶段）
from ..vector_editor import (
    compute_convex_hull,
    compute_concave_hull,
    polygonize_closed_regions,
    clip_boundary_with_lines,
    trim_polygon_with_lines,
)

__all__ = [
    'compute_convex_hull',
    'compute_concave_hull',
    'polygonize_closed_regions',
    'clip_boundary_with_lines',
    'trim_polygon_with_lines',
]