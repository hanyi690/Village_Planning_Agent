"""
工具核心模块

提供核心分析逻辑的统一导出。

模块结构：
- utils/: 公共工具函数
- schemas/: 数据模型和样式定义
- analysis/: 分析功能（可达性、空间分析）
- planning/: 规划制图功能
- data/: 数据层（获取、覆盖率计算）
- wrappers/: 工具适配层
"""

# 原有导出（向后兼容）
from .gis_core import run_gis_analysis, format_gis_result
from .network_core import run_network_analysis, format_network_result
from .population_core import run_population_analysis, format_population_result
from .accessibility_core import run_accessibility_analysis, format_accessibility_result
from .gis_data_fetcher import GISDataFetcher
from .geo_analysis_agent import GeoAnalysisAgent
from .spatial_analysis import run_spatial_overlay, run_spatial_query, calculate_buffer_zones
from .isochrone_analysis import generate_isochrones, calculate_isochrone_coverage
from .vector_editor import (
    create_function_zones,
    create_facility_points,
    create_development_axis,
    compute_convex_hull,
    compute_concave_hull,
    polygonize_closed_regions,
    generate_integrated_proxy_boundary,
    clip_boundary_with_lines,
)
from .map_renderer import render_planning_map, PLANNING_STYLES
from .gis_tool_wrappers import GIS_TOOL_WRAPPERS, get_gis_tool_wrapper
from .planning_schema import (
    VillagePlanningScheme,
    PlanningZone,
    FacilityPoint,
    DevelopmentAxis,
    get_zone_color,
    get_zone_code,
    get_facility_color,
)
from .spatial_layout_generator import generate_spatial_layout_from_json

# 新模块导出
from .utils import (
    haversine_distance,
    calculate_area_km2,
    geojson_to_geodataframe,
    geodataframe_to_geojson,
    ensure_tuple_coord,
)
from .schemas import (
    PLANNING_STYLES as PLANNING_STYLES_SCHEMA,
    LAYER_GEOMETRY_TYPES,
    get_style_for_layer,
    get_style_for_feature,
    VillagePlanningScheme,
    PlanningZone,
    FacilityPoint as FacilityPointSchema,
    DevelopmentAxis as DevelopmentAxisSchema,
)
from .analysis import (
    run_accessibility_analysis as run_accessibility_analysis_merged,
    generate_isochrones as generate_isochrones_merged,
    run_gis_analysis as run_gis_analysis_merged,
    format_accessibility_result as format_accessibility_merged,
    format_isochrone_result,
    SERVICE_RADIUS_STANDARDS,
    TRAVEL_SPEEDS,
)
from .planning import (
    create_function_zones as create_function_zones_planning,
    create_facility_points as create_facility_points_planning,
    create_development_axis as create_development_axis_planning,
    compute_convex_hull as compute_convex_hull_planning,
    compute_concave_hull as compute_concave_hull_planning,
    ZONE_TYPE_DEFINITIONS,
    FACILITY_STATUS,
)
from .wrappers import (
    BaseToolWrapper,
    format_success_response,
    format_error_response,
    wrap_tool_response,
)
from .data import (
    get_fetcher,
    calculate_gis_coverage,
)

__all__ = [
    # 原有导出（向后兼容）
    "run_gis_analysis",
    "format_gis_result",
    "run_network_analysis",
    "format_network_result",
    "run_population_analysis",
    "format_population_result",
    "run_accessibility_analysis",
    "format_accessibility_result",
    "GISDataFetcher",
    "GeoAnalysisAgent",
    "run_spatial_overlay",
    "run_spatial_query",
    "calculate_buffer_zones",
    "generate_isochrones",
    "calculate_isochrone_coverage",
    "create_function_zones",
    "create_facility_points",
    "create_development_axis",
    "compute_convex_hull",
    "compute_concave_hull",
    "polygonize_closed_regions",
    "generate_integrated_proxy_boundary",
    "clip_boundary_with_lines",
    "render_planning_map",
    "PLANNING_STYLES",
    "GIS_TOOL_WRAPPERS",
    "get_gis_tool_wrapper",
    "VillagePlanningScheme",
    "PlanningZone",
    "FacilityPoint",
    "DevelopmentAxis",
    "get_zone_color",
    "get_zone_code",
    "get_facility_color",
    "generate_spatial_layout_from_json",
    # 新模块导出
    "haversine_distance",
    "calculate_area_km2",
    "geojson_to_geodataframe",
    "geodataframe_to_geojson",
    "ensure_tuple_coord",
    "LAYER_GEOMETRY_TYPES",
    "get_style_for_layer",
    "get_style_for_feature",
    "FacilityPointSchema",
    "DevelopmentAxisSchema",
    "SERVICE_RADIUS_STANDARDS",
    "TRAVEL_SPEEDS",
    "ZONE_TYPE_DEFINITIONS",
    "FACILITY_STATUS",
    "BaseToolWrapper",
    "format_success_response",
    "format_error_response",
    "wrap_tool_response",
    "get_fetcher",
    "calculate_gis_coverage",
]