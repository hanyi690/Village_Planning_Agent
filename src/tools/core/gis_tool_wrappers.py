"""
GIS Tool Wrappers for ToolRegistry

Wraps GIS tool functions to match ToolRegistry.execute_tool signature.
ToolRegistry expects: tool_func(context: Dict[str, Any]) -> str

Architecture (分层设计):
- Layer 0: 基础数据层 (boundary_fallback, gis_data_fetch, gis_coverage)
- Layer 1: 空间分析层 (spatial_overlay, spatial_query, accessibility_analysis, landuse_change_analysis, hazard_buffer_generator)
- Layer 2: 规划决策层 (facility_validator, constraint_validator, ecological_sensitivity, spatial_layout_generator)
- Output: 渲染输出层 (map_renderer)

工具合并说明:
- isochrone_analysis 合入 accessibility_analysis (include_isochrone 参数)
- poi_search 合入 accessibility_analysis (include_poi 参数)
- planning_vectorizer 合入 spatial_layout_generator
- wfs_data_fetch 别名移除
- ecological_sensitivity 独立实现

新增工具:
- landuse_change_analysis: 用地变化分析 (landuse_current vs landuse_planned)
- constraint_validator: 保护约束验证 (农田/生态/历史保护红线)
- hazard_buffer_generator: 灾害缓冲区生成
- wrap_spatial_overlay: 空间叠加分析 wrapper
- wrap_spatial_query: 空间查询 wrapper
- wrap_map_renderer: 地图渲染 wrapper
"""

from typing import Dict, Any, List, Optional, Tuple
import json
from ...utils.logger import get_logger

logger = get_logger(__name__)


def _format_success_response(data_fields: Dict[str, Any]) -> str:
    """Format a success response with given data fields."""
    return json.dumps({"success": True, **data_fields}, ensure_ascii=False)


def _format_error_response(error: str) -> str:
    """Format an error response."""
    return json.dumps({"success": False, "error": error}, ensure_ascii=False)


def _ensure_tuple_coord(coord) -> Optional[Tuple[float, float]]:
    """Convert list coordinate to tuple if needed."""
    if coord is None:
        return None
    if isinstance(coord, list) and len(coord) == 2:
        return tuple(coord)
    return coord


def _wrap_tool_response(result: Dict[str, Any], success_fields: List[str]) -> str:
    """
    Common wrapper pattern: format result as JSON response.

    Args:
        result: Tool execution result dict with 'success' key
        success_fields: Field names to extract from data on success

    Returns:
        JSON string response
    """
    if result.get("success"):
        data = result.get("data", {})
        fields = {name: data.get(name) for name in success_fields if data.get(name) is not None}
        return _format_success_response(fields)
    else:
        return _format_error_response(result.get("error", "Unknown error"))


# ============================================
# Layer 0: 基础数据层
# ============================================

def wrap_boundary_fallback(context: Dict[str, Any]) -> str:
    """Wrapper for boundary fallback tool (Layer 0 基础)."""
    from .boundary_fallback import generate_proxy_boundary_with_fallback
    from ...config.boundary_fallback import BoundaryFallbackConfig

    center = _ensure_tuple_coord(context.get("center"))
    village_name = context.get("village_name", "")
    gis_data = context.get("gis_data", {})
    config = context.get("config")

    if config is None:
        config = BoundaryFallbackConfig()
    elif isinstance(config, dict):
        config = BoundaryFallbackConfig(**config)

    result = generate_proxy_boundary_with_fallback(
        center=center,
        village_name=village_name,
        gis_data=gis_data,
        config=config,
        skip_user_upload=context.get("skip_user_upload", False),
    )

    if result.get("success"):
        return _format_success_response({
            "geojson": result.get("geojson"),
            "strategy_used": result.get("strategy_used"),
            "fallback_history": result.get("fallback_history"),
            "stats": result.get("stats"),
        })
    return _format_error_response(result.get("error", "Boundary generation failed"))


def wrap_gis_data_fetch(context: Dict[str, Any]) -> str:
    """Wrapper for GIS data fetcher tool (Layer 0 基础)."""
    from .gis_data_fetcher import get_fetcher

    fetcher = get_fetcher()
    result = fetcher.fetch_all_gis_data(
        location=context.get("location", ""),
        buffer_km=context.get("buffer_km", 5.0),
        max_features=context.get("max_features", 500)
    )

    has_data = any([
        result.get("water", {}).get("success"),
        result.get("road", {}).get("success"),
        result.get("residential", {}).get("success")
    ])

    if has_data:
        return json.dumps({
            "success": True,
            "location": result.get("location"),
            "center": result.get("center"),
            "water": result.get("water", {}).get("geojson") is not None,
            "road": result.get("road", {}).get("geojson") is not None,
            "residential": result.get("residential", {}).get("geojson") is not None,
            "data": result
        }, ensure_ascii=False, default=str)
    return json.dumps({
        "success": False,
        "error": "Failed to fetch GIS data",
        "location": context.get("location", "")
    }, ensure_ascii=False)


def wrap_gis_coverage_calculator(context: Dict[str, Any]) -> str:
    """Wrapper for GIS coverage calculator tool (Layer 0 基础)."""
    from .gis_data_fetcher import get_fetcher

    fetcher = get_fetcher()
    location = context.get("location") or context.get("village_name", "")
    buffer_km = context.get("buffer_km", 5.0)

    if not location:
        return _format_error_response("缺少 location 或 village_name 参数")

    user_uploaded_data = context.get("user_uploaded_data", {})

    auto_result = fetcher.fetch_all_gis_data(location, buffer_km, max_features=100)

    def get_geojson_with_source(data_type: str, user_data: Optional[Dict], auto_data: Optional[Dict]) -> tuple:
        if user_data:
            return user_data, "user_upload"
        if auto_data and auto_data.get("success") and auto_data.get("geojson"):
            return auto_data.get("geojson"), "auto_fetch"
        return None, "missing"

    boundary_geojson, boundary_source = get_geojson_with_source(
        "boundary", user_uploaded_data.get("boundary"), auto_result.get("boundary")
    )
    water_geojson, water_source = get_geojson_with_source(
        "water", user_uploaded_data.get("water"), auto_result.get("water")
    )
    road_geojson, road_source = get_geojson_with_source(
        "road", user_uploaded_data.get("road"), auto_result.get("road")
    )
    residential_geojson, residential_source = get_geojson_with_source(
        "residential", user_uploaded_data.get("residential"), auto_result.get("residential")
    )

    water_count = len(water_geojson.get("features", [])) if water_geojson else 0
    road_count = len(road_geojson.get("features", [])) if road_geojson else 0
    residential_count = len(residential_geojson.get("features", [])) if residential_geojson else 0

    coverage_rate = sum([water_geojson is not None, road_geojson is not None, residential_geojson is not None]) / 3

    return _format_success_response({
        "location": location,
        "coverage_rate": coverage_rate,
        "layers_available": {
            "water": water_geojson is not None,
            "road": road_geojson is not None,
            "residential": residential_geojson is not None,
            "boundary": boundary_geojson is not None,
        },
        "feature_counts": {
            "water": water_count,
            "road": road_count,
            "residential": residential_count,
        },
        "center": auto_result.get("center"),
        "data_sources": {
            "boundary": boundary_source,
            "water": water_source,
            "road": road_source,
            "residential": residential_source,
        },
    })


# ============================================
# Layer 1: 空间分析层
# ============================================

def wrap_spatial_overlay(context: Dict[str, Any]) -> str:
    """Wrapper for spatial overlay analysis (Layer 1 分析)."""
    from .spatial_analysis import run_spatial_overlay

    operation = context.get("operation", "intersect")
    layer_a = context.get("layer_a", {})
    layer_b = context.get("layer_b", {})

    if not layer_a or not layer_b:
        return _format_error_response("缺少 layer_a 或 layer_b 参数")

    result = run_spatial_overlay(
        operation=operation,
        layer_a=layer_a,
        layer_b=layer_b,
        keep_attributes=context.get("keep_attributes", "a")
    )

    return _wrap_tool_response(result, ["geojson", "operation", "feature_count", "total_area_km2"])


def wrap_spatial_query(context: Dict[str, Any]) -> str:
    """Wrapper for spatial query (Layer 1 分析)."""
    from .spatial_analysis import run_spatial_query

    query_type = context.get("query_type", "intersects")
    geometry = context.get("geometry", {})
    target_layer = context.get("target_layer", {})

    if not geometry or not target_layer:
        return _format_error_response("缺少 geometry 或 target_layer 参数")

    result = run_spatial_query(
        query_type=query_type,
        geometry=geometry,
        target_layer=target_layer,
        max_distance=context.get("max_distance", 1000),
        limit=context.get("limit", 100)
    )

    return _wrap_tool_response(result, ["geojson", "query_type", "match_count", "returned_count"])


def wrap_accessibility_analysis(context: Dict[str, Any]) -> str:
    """
    Wrapper for accessibility analysis (Layer 1 分析).

    合并功能:
    - isochrone_analysis: include_isochrone=True
    - poi_search: include_poi=True
    """
    from .accessibility_core import run_accessibility_analysis
    from .isochrone_analysis import generate_isochrones
    from ..geocoding import POIProvider

    analysis_type = context.get("analysis_type", "service_coverage")
    include_isochrone = context.get("include_isochrone", False)
    include_poi = context.get("include_poi", False)

    results = {}

    # Isochrone 分析（合并）
    if include_isochrone or analysis_type == "isochrone":
        center = _ensure_tuple_coord(context.get("center", [0, 0]))
        iso_result = generate_isochrones(
            center=center,
            time_minutes=context.get("time_minutes", [5, 10, 15]),
            travel_mode=context.get("travel_mode", "walk")
        )
        if iso_result.get("success"):
            results["isochrone"] = iso_result.get("data", {}).get("geojson")

    # POI 搜索（合并）
    if include_poi:
        keyword = context.get("keyword", "")
        region = context.get("region", "")
        center = _ensure_tuple_coord(context.get("center")) or (0, 0)
        radius = context.get("radius", 1000)

        if region:
            poi_result = POIProvider.search_poi_in_region(keyword, region, context.get("page_size", 20))
        else:
            poi_result = POIProvider.search_poi_nearby(keyword, center, radius, context.get("page_size", 20))

        if poi_result.get("success"):
            results["poi"] = {
                "pois": poi_result.get("pois", []),
                "geojson": poi_result.get("geojson"),
            }

    # Accessibility 分析
    origin = _ensure_tuple_coord(context.get("origin"))
    center = _ensure_tuple_coord(context.get("center"))
    destinations = context.get("destinations", [])
    if destinations and isinstance(destinations[0], list):
        destinations = [tuple(d) if len(d) == 2 else d for d in destinations]

    if analysis_type != "isochrone":
        result = run_accessibility_analysis(
            analysis_type=analysis_type,
            origin=origin,
            destinations=destinations,
            center=center,
            **{k: v for k, v in context.items()
               if k not in ["analysis_type", "origin", "destinations", "center", "include_isochrone", "include_poi"]}
        )

        if result.get("success"):
            data = result.get("data", {})
            summary = data.get("summary", {})
            results["accessibility"] = {
                "summary": summary,
                "coverage_rate": summary.get("coverage_rate", 0),
                "geojson": data.get("geojson")
            }

    if results:
        return _format_success_response(results)
    return _format_error_response("Accessibility analysis failed")


def wrap_landuse_change_analysis(context: Dict[str, Any]) -> str:
    """
    Wrapper for landuse change analysis (Layer 1 分析).

    分析现状用地 vs 规划用地的变化。
    输入: landuse_current.geojson, landuse_planned.geojson
    输出: 变化统计、变化热力图、新增/减少用地
    """
    try:
        from .spatial_analysis import run_spatial_overlay, geojson_to_geodataframe, geodataframe_to_geojson
        from shapely.geometry import shape
        import geopandas as gpd
    except ImportError:
        return _format_error_response("landuse_change_analysis 需要 geopandas 和 shapely")

    current_landuse = context.get("current_landuse", {})
    planned_landuse = context.get("planned_landuse", {})

    if not current_landuse or not planned_landuse:
        return _format_error_response("缺少 current_landuse 或 planned_landuse 参数")

    try:
        gdf_current = geojson_to_geodataframe(current_landuse)
        gdf_planned = geojson_to_geodataframe(planned_landuse)

        if gdf_current is None or gdf_planned is None:
            return _format_error_response("GeoJSON 数据转换失败")

        # 统计现状用地类型
        current_types = {}
        for idx, row in gdf_current.iterrows():
            type_name = row.get("用地类型", row.get("type", row.get("landuse_type", "unknown")))
            current_types[type_name] = current_types.get(type_name, 0) + 1

        # 统计规划用地类型
        planned_types = {}
        for idx, row in gdf_planned.iterrows():
            type_name = row.get("用地类型", row.get("type", row.get("landuse_type", "unknown")))
            planned_types[type_name] = planned_types.get(type_name, 0) + 1

        # 计算变化
        all_types = set(current_types.keys()) | set(planned_types.keys())
        change_stats = {}
        for t in all_types:
            current_count = current_types.get(t, 0)
            planned_count = planned_types.get(t, 0)
            change_stats[t] = {
                "current": current_count,
                "planned": planned_count,
                "change": planned_count - current_count,
                "change_rate": (planned_count - current_count) / max(current_count, 1) * 100
            }

        # 计算面积变化
        try:
            gdf_current_proj = gdf_current.to_crs(epsg=3857)
            gdf_planned_proj = gdf_planned.to_crs(epsg=3857)
            current_area_km2 = gdf_current_proj.geometry.area.sum() / 1_000_000
            planned_area_km2 = gdf_planned_proj.geometry.area.sum() / 1_000_000
        except Exception:
            current_area_km2 = 0
            planned_area_km2 = 0

        return _format_success_response({
            "change_statistics": change_stats,
            "total_current_area_km2": round(current_area_km2, 4),
            "total_planned_area_km2": round(planned_area_km2, 4),
            "area_change_km2": round(planned_area_km2 - current_area_km2, 4),
            "current_feature_count": len(gdf_current),
            "planned_feature_count": len(gdf_planned),
        })

    except Exception as e:
        return _format_error_response(f"用地变化分析失败: {str(e)}")


def wrap_hazard_buffer_generator(context: Dict[str, Any]) -> str:
    """
    Wrapper for hazard buffer generator (Layer 1 分析).

    生成地质灾害缓冲区。
    输入: geological_hazard_points.geojson
    输出: 缓冲区范围、受影响面积、安全区
    """
    from .spatial_analysis import calculate_buffer_zones, geojson_to_geodataframe, geodataframe_to_geojson

    hazard_points = context.get("hazard_points", {})
    buffer_meters = context.get("buffer_meters", 200)

    if not hazard_points:
        return _format_error_response("缺少 hazard_points 参数")

    result = calculate_buffer_zones(
        layer=hazard_points,
        buffer_distance=buffer_meters,
        dissolve=context.get("dissolve", True),
    )

    if result.get("success"):
        data = result.get("data", {})
        return _format_success_response({
            "buffer_zones": data.get("geojson"),
            "buffer_distance_m": buffer_meters,
            "total_area_km2": data.get("total_area_km2", 0),
            "feature_count": data.get("feature_count", 0),
        })
    return _format_error_response(result.get("error", "缓冲区生成失败"))


# ============================================
# Layer 2: 规划决策层
# ============================================

def wrap_facility_validator(context: Dict[str, Any]) -> str:
    """
    Wrapper for facility location validation (Layer 2 决策).

    增强: 加入保护约束检查和灾害区域检查。
    """
    from ..builtin.gis_validation import validate_facility_location

    location = _ensure_tuple_coord(context.get("location", [0, 0]))
    check_protection_constraints = context.get("check_protection_constraints", False)
    check_hazard_zones = context.get("check_hazard_zones", False)

    analysis_params = context.get("analysis_params", {})

    # 添加约束检查参数
    if check_protection_constraints:
        analysis_params["protection_zones"] = context.get("protection_zones", {})
    if check_hazard_zones:
        analysis_params["hazard_zones"] = context.get("hazard_zones", {})

    result = validate_facility_location(
        facility_type=context.get("facility_type", "公共服务设施"),
        location=location,
        analysis_params=analysis_params
    )

    return _wrap_tool_response(result, [
        "facility_type", "overall_score", "suitability_level", "recommendations"
    ])


def wrap_constraint_validator(context: Dict[str, Any]) -> str:
    """
    Wrapper for constraint validator (Layer 2 决策).

    验证规划方案是否符合保护约束。
    输入: 规划方案 + 保护红线 + 建设区
    输出: 冲突检测、合规评分
    """
    from .spatial_analysis import run_spatial_overlay, geojson_to_geodataframe, geodataframe_to_geojson

    planning_zones = context.get("planning_zones", {})
    farmland_protection = context.get("farmland_protection", {})
    ecological_protection = context.get("ecological_protection", {})
    historical_protection = context.get("historical_protection", {})
    construction_zone = context.get("construction_zone", {})

    if not planning_zones:
        return _format_error_response("缺少 planning_zones 参数")

    conflicts = []
    total_checks = 0
    passed_checks = 0

    protection_layers = {
        "farmland": farmland_protection,
        "ecological": ecological_protection,
        "historical": historical_protection,
    }

    for zone_name, protection_geojson in protection_layers.items():
        if protection_geojson and protection_geojson.get("features"):
            total_checks += 1
            # 检查规划方案与保护区的交集
            intersect_result = run_spatial_overlay(
                operation="intersect",
                layer_a=planning_zones,
                layer_b=protection_geojson,
            )
            if intersect_result.get("success"):
                intersect_features = intersect_result.get("data", {}).get("feature_count", 0)
                if intersect_features > 0:
                    conflicts.append({
                        "zone_type": zone_name,
                        "conflict_count": intersect_features,
                        "severity": "high" if zone_name == "farmland" else "medium",
                    })
                else:
                    passed_checks += 1

    # 检查建设区合规
    if construction_zone and construction_zone.get("features"):
        total_checks += 1
        clip_result = run_spatial_overlay(
            operation="clip",
            layer_a=planning_zones,
            layer_b=construction_zone,
        )
        if clip_result.get("success"):
            clip_features = clip_result.get("data", {}).get("feature_count", 0)
            original_features = len(planning_zones.get("features", []))
            if clip_features < original_features:
                conflicts.append({
                    "zone_type": "construction_boundary",
                    "conflict_count": original_features - clip_features,
                    "severity": "low",
                })
            else:
                passed_checks += 1

    compliance_score = passed_checks / max(total_checks, 1)

    return _format_success_response({
        "compliance_score": round(compliance_score, 2),
        "passed_checks": passed_checks,
        "total_checks": total_checks,
        "conflicts": conflicts,
        "is_valid": len(conflicts) == 0,
    })


def wrap_ecological_sensitivity(context: Dict[str, Any]) -> str:
    """
    Wrapper for ecological sensitivity assessment (Layer 2 决策).

    独立实现，合并地质灾害点数据。
    """
    from .spatial_analysis import geojson_to_geodataframe, geodataframe_to_geojson, calculate_buffer_zones
    from ..builtin.gis_validation import assess_ecological_sensitivity

    study_area = context.get("study_area", {})
    water_features = context.get("water_features")
    slope_data = context.get("slope_data")
    hazard_points = context.get("hazard_points")  # 新增地质灾害点

    # 基础生态敏感性评估
    result = assess_ecological_sensitivity(
        study_area=study_area,
        water_features=water_features,
        slope_data=slope_data
    )

    if not result.get("success"):
        return _format_error_response(result.get("error", "生态敏感性评估失败"))

    data = result.get("data", {})

    # 增加地质灾害敏感区
    if hazard_points and hazard_points.get("features"):
        hazard_buffer = calculate_buffer_zones(
            layer=hazard_points,
            buffer_distance=200,
            dissolve=True,
        )
        if hazard_buffer.get("success"):
            data["hazard_sensitive_zones"] = hazard_buffer.get("data", {}).get("geojson")
            data["hazard_area_km2"] = hazard_buffer.get("data", {}).get("total_area_km2", 0)

    return _format_success_response({
        "study_area_km2": data.get("study_area_km2"),
        "sensitive_area_km2": data.get("sensitive_area_km2"),
        "sensitivity_class": data.get("sensitivity_class"),
        "sensitivity_zones": data.get("sensitivity_zones"),
        "hazard_sensitive_zones": data.get("hazard_sensitive_zones"),
        "recommendations": data.get("recommendations", []),
    })


def wrap_spatial_layout_generator(context: Dict[str, Any]) -> str:
    """
    Wrapper for spatial layout generator (Layer 2 决策).

    合并: planning_vectorizer 功能
    增强: 加入约束避让参数
    """
    from .spatial_layout_generator import generate_spatial_layout_from_json
    from .planning_schema import VillagePlanningScheme
    from .vector_editor import create_function_zones, create_facility_points

    village_boundary = context.get("village_boundary")
    road_network = context.get("road_network")
    planning_scheme_dict = context.get("planning_scheme")
    constraint_zones = context.get("constraint_zones", {})  # 新增约束参数

    results = {}

    # Planning vectorizer 功能（合并）
    if context.get("zones") or context.get("facilities"):
        zones = context.get("zones", [])
        facilities = context.get("facilities", [])
        village_center = _ensure_tuple_coord(context.get("village_center"))

        if zones:
            zone_result = create_function_zones(zones=zones, village_center=village_center)
            if zone_result.get("success"):
                results["zones_geojson"] = zone_result.get("data", {}).get("geojson")

        if facilities:
            facility_result = create_facility_points(facilities=facilities)
            if facility_result.get("success"):
                results["facilities_geojson"] = facility_result.get("data", {}).get("geojson")

    # Spatial layout generator 功能
    if planning_scheme_dict:
        try:
            if isinstance(planning_scheme_dict, dict):
                planning_scheme = VillagePlanningScheme(**planning_scheme_dict)
            else:
                planning_scheme = planning_scheme_dict
        except Exception as e:
            return _format_error_response(f"Invalid planning scheme: {str(e)}")

        layout_result = generate_spatial_layout_from_json(
            village_boundary=village_boundary,
            road_network=road_network,
            planning_scheme=planning_scheme,
            constraint_zones=constraint_zones,  # 传递约束
            fallback_grid=context.get("fallback_grid", True),
            merge_threshold=context.get("merge_threshold", 0.01)
        )

        if layout_result.get("success"):
            data = layout_result.get("data", {})
            stats = data.get("statistics", {})
            results["geojson"] = data.get("geojson")
            results["zone_count"] = stats.get("zone_count", 0)
            results["facility_count"] = stats.get("facility_count", 0)
            results["total_area_km2"] = stats.get("total_area_km2", 0)
            results["center"] = data.get("center")

    if results:
        return _format_success_response(results)
    return _format_error_response("Spatial layout generation failed")


# ============================================
# Output: 渲染输出层
# ============================================

def wrap_map_renderer(context: Dict[str, Any]) -> str:
    """Wrapper for map renderer (Output 渲染)."""
    from .map_renderer import render_planning_map

    layers = context.get("layers", [])
    if not layers:
        return _format_error_response("缺少 layers 参数")

    result = render_planning_map(
        layers=layers,
        title=context.get("title", "规划专题图"),
        center=_ensure_tuple_coord(context.get("center")),
        zoom=context.get("zoom", 12),
        output_format=context.get("output_format", "html"),
    )

    return _wrap_tool_response(result, ["map_html", "layer_info", "center", "zoom"])


# ============================================
# Tool Registry Mapping (分层架构)
# ============================================

GIS_TOOL_WRAPPERS = {
    # Layer 0: 基础数据层
    "boundary_fallback": wrap_boundary_fallback,
    "gis_data_fetch": wrap_gis_data_fetch,
    "gis_coverage_calculator": wrap_gis_coverage_calculator,

    # Layer 1: 空间分析层
    "spatial_overlay": wrap_spatial_overlay,
    "spatial_query": wrap_spatial_query,
    "accessibility_analysis": wrap_accessibility_analysis,
    "isochrone_analysis": wrap_accessibility_analysis,  # 别名，合并到 accessibility
    "poi_search": wrap_accessibility_analysis,  # 别名，合并到 accessibility
    "landuse_change_analysis": wrap_landuse_change_analysis,
    "hazard_buffer_generator": wrap_hazard_buffer_generator,

    # Layer 2: 规划决策层
    "facility_validator": wrap_facility_validator,
    "constraint_validator": wrap_constraint_validator,
    "ecological_sensitivity": wrap_ecological_sensitivity,
    "spatial_layout_generator": wrap_spatial_layout_generator,
    "planning_vectorizer": wrap_spatial_layout_generator,  # 别名，合并到 spatial_layout

    # Output: 渲染输出层
    "map_renderer": wrap_map_renderer,
}

# 工具执行顺序（分层依赖）
GIS_TOOL_EXECUTION_ORDER = {
    "layer_0": ["boundary_fallback", "gis_data_fetch", "gis_coverage_calculator"],
    "layer_1": ["spatial_overlay", "spatial_query", "accessibility_analysis", "landuse_change_analysis", "hazard_buffer_generator"],
    "layer_2": ["facility_validator", "constraint_validator", "ecological_sensitivity", "spatial_layout_generator"],
    "output": ["map_renderer"],
}


def get_gis_tool_wrapper(tool_name: str):
    """Get wrapper function for a GIS tool"""
    return GIS_TOOL_WRAPPERS.get(tool_name)


def get_tool_layer(tool_name: str) -> Optional[str]:
    """Get the layer number for a tool"""
    for layer, tools in GIS_TOOL_EXECUTION_ORDER.items():
        if tool_name in tools:
            return layer
    return None


def check_dependencies(tool_name: str, context: Dict[str, Any]) -> bool:
    """
    Check if tool dependencies are satisfied before execution.

    Args:
        tool_name: Tool name to check
        context: Execution context

    Returns:
        True if dependencies are satisfied
    """
    layer = get_tool_layer(tool_name)

    if layer == "layer_1":
        # Layer 1 工具需要边界数据
        return context.get("boundary") is not None or context.get("center") is not None
    if layer == "layer_2":
        # Layer 2 工具需要分析结果或边界数据
        return context.get("spatial_analysis") is not None or context.get("boundary") is not None
    if layer == "output":
        # Output 工具需要规划输出
        return context.get("planning_output") is not None or context.get("layers") is not None
    return True


__all__ = [
    "GIS_TOOL_WRAPPERS",
    "GIS_TOOL_EXECUTION_ORDER",
    "get_gis_tool_wrapper",
    "get_tool_layer",
    "check_dependencies",
    # Layer 0
    "wrap_boundary_fallback",
    "wrap_gis_data_fetch",
    "wrap_gis_coverage_calculator",
    # Layer 1
    "wrap_spatial_overlay",
    "wrap_spatial_query",
    "wrap_accessibility_analysis",
    "wrap_landuse_change_analysis",
    "wrap_hazard_buffer_generator",
    # Layer 2
    "wrap_facility_validator",
    "wrap_constraint_validator",
    "wrap_ecological_sensitivity",
    "wrap_spatial_layout_generator",
    # Output
    "wrap_map_renderer",
]