"""
Planning Module - 规划制图模块

提供规划矢量数据创建功能：功能区、设施点、发展轴、边界等。
"""

from .zone_editor import (
    create_function_zones,
    create_planning_boundary,
    generate_integrated_proxy_boundary,
    ZONE_TYPE_DEFINITIONS,
)

from .facility_editor import (
    create_facility_points,
    create_development_axis,
    merge_vector_layers,
    format_vector_result,
    FACILITY_STATUS,
)

from .geometry_utils import (
    compute_convex_hull,
    compute_concave_hull,
    polygonize_closed_regions,
    clip_boundary_with_lines,
    trim_polygon_with_lines,
)

__all__ = [
    # zone_editor
    'create_function_zones',
    'create_planning_boundary',
    'generate_integrated_proxy_boundary',
    'ZONE_TYPE_DEFINITIONS',
    # facility_editor
    'create_facility_points',
    'create_development_axis',
    'merge_vector_layers',
    'format_vector_result',
    'FACILITY_STATUS',
    # geometry_utils
    'compute_convex_hull',
    'compute_concave_hull',
    'polygonize_closed_regions',
    'clip_boundary_with_lines',
    'trim_polygon_with_lines',
]