"""
GIS Tool Wrappers for ToolRegistry

Wraps GIS tool functions to match ToolRegistry.execute_tool signature.
ToolRegistry expects: tool_func(context: Dict[str, Any]) -> str

These wrappers convert the context dict to function-specific parameters
and format the output as a string or JSON.

Standard Output Format:
- Success: {"success": True, ...data_fields}
- Failure: {"success": False, "error": "error_message"}

Each wrapper returns JSON with consistent structure for frontend parsing.
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


def _extract_result_fields(result: Dict[str, Any], field_names: List[str]) -> Dict[str, Any]:
    """Extract specified fields from result data."""
    data = result.get("data", {})
    return {name: data.get(name) for name in field_names if data.get(name) is not None}


def _ensure_tuple_coord(coord) -> Optional[Tuple[float, float]]:
    """Convert list coordinate to tuple if needed."""
    if coord is None:
        return None
    if isinstance(coord, list) and len(coord) == 2:
        return tuple(coord)
    return coord


def _count_geojson_features(result: Dict[str, Any], category: str) -> int:
    """Count features in a GeoJSON result for a given category."""
    if not result.get(category, {}).get("success", False):
        return 0
    geojson = result[category].get("geojson", {})
    return len(geojson.get("features", []))


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
        fields = _extract_result_fields(result, success_fields)
        return _format_success_response(fields)
    else:
        return _format_error_response(result.get("error", "Unknown error"))


def wrap_isochrone_analysis(context: Dict[str, Any]) -> str:
    """Wrapper for isochrone analysis tool."""
    from .isochrone_analysis import generate_isochrones

    center = _ensure_tuple_coord(context.get("center", [0, 0]))

    result = generate_isochrones(
        center=center,
        time_minutes=context.get("time_minutes", [5, 10, 15]),
        travel_mode=context.get("travel_mode", "walk")
    )

    return _wrap_tool_response(result, ["center", "travel_mode", "geojson"])


def wrap_planning_vectorizer(context: Dict[str, Any]) -> str:
    """Wrapper for planning vectorizer tool."""
    from .vector_editor import create_function_zones, create_facility_points

    zones = context.get("zones", [])
    facilities = context.get("facilities", [])
    village_center = _ensure_tuple_coord(context.get("village_center"))

    results = {}

    if zones:
        zone_result = create_function_zones(zones=zones, village_center=village_center)
        if zone_result.get("success"):
            results["zones"] = zone_result.get("data", {})

    if facilities:
        facility_result = create_facility_points(facilities=facilities)
        if facility_result.get("success"):
            results["facilities"] = facility_result.get("data", {})

    if results:
        return _format_success_response(results)
    return _format_error_response("No valid zones or facilities provided")


def wrap_facility_validator(context: Dict[str, Any]) -> str:
    """Wrapper for facility location validation tool."""
    from ..builtin.gis_validation import validate_facility_location

    location = _ensure_tuple_coord(context.get("location", [0, 0]))

    result = validate_facility_location(
        facility_type=context.get("facility_type", "公共服务设施"),
        location=location,
        analysis_params=context.get("analysis_params", {})
    )

    return _wrap_tool_response(result, [
        "facility_type", "overall_score", "suitability_level", "recommendations"
    ])


def wrap_ecological_sensitivity(context: Dict[str, Any]) -> str:
    """Wrapper for ecological sensitivity assessment tool."""
    from ..builtin.gis_validation import assess_ecological_sensitivity

    result = assess_ecological_sensitivity(
        study_area=context.get("study_area", {}),
        water_features=context.get("water_features"),
        slope_data=context.get("slope_data")
    )

    return _wrap_tool_response(result, [
        "study_area_km2", "sensitive_area_km2", "sensitivity_class",
        "sensitivity_zones", "recommendations"
    ])


def wrap_gis_data_fetch(context: Dict[str, Any]) -> str:
    """Wrapper for GIS data fetcher tool."""
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


def wrap_accessibility_analysis(context: Dict[str, Any]) -> str:
    """Wrapper for accessibility analysis tool."""
    from .accessibility_core import run_accessibility_analysis

    origin = _ensure_tuple_coord(context.get("origin"))
    center = _ensure_tuple_coord(context.get("center"))

    destinations = context.get("destinations", [])
    if destinations and isinstance(destinations[0], list):
        destinations = [tuple(d) if len(d) == 2 else d for d in destinations]

    result = run_accessibility_analysis(
        analysis_type=context.get("analysis_type", "service_coverage"),
        origin=origin,
        destinations=destinations,
        center=center,
        **{k: v for k, v in context.items()
           if k not in ["analysis_type", "origin", "destinations", "center"]}
    )

    if result.get("success"):
        data = result.get("data", {})
        summary = data.get("summary", {})
        return _format_success_response({
            "summary": summary,
            "coverage_rate": summary.get("coverage_rate", 0),
            "reachable_count": summary.get("reachable", 0),
            "geojson": data.get("geojson")
        })
    return _format_error_response(result.get("error", "Unknown error"))


def wrap_poi_search(context: Dict[str, Any]) -> str:
    """Wrapper for POI search tool (使用 POIProvider 高德优先策略)."""
    from ..geocoding import POIProvider

    keyword = context.get("keyword", "")
    region = context.get("region", "")
    page_size = context.get("page_size", 20)

    if region:
        result = POIProvider.search_poi_in_region(keyword, region, page_size)
    else:
        center = _ensure_tuple_coord(context.get("center")) or (0, 0)
        radius = context.get("radius", 1000)
        result = POIProvider.search_poi_nearby(keyword, center, radius, page_size)

    if result.get("success"):
        pois = result.get("pois", [])
        return _format_success_response({
            "pois": pois,
            "total_count": len(pois),
            "geojson": result.get("geojson"),
            "layer_type": "facility_point",
            "layer_name": "公共服务设施",
            "source": result.get("source", "unknown")
        })
    return _format_error_response(result.get("error", "POI search failed"))


def wrap_gis_coverage_calculator(context: Dict[str, Any]) -> str:
    """
    Wrapper for GIS coverage calculator tool.

    数据获取优先级：用户上传 > 会话缓存 > 自动获取（天地图 WFS）
    """
    from .gis_data_fetcher import get_fetcher
    from ..gis.data_manager import GISDataManager

    fetcher = get_fetcher()
    location = context.get("location") or context.get("village_name", "")
    buffer_km = context.get("buffer_km", 5.0)

    if not location:
        return _format_error_response("缺少 location 或 village_name 参数")

    # 数据来源追踪
    data_sources = {}

    # 优先检查用户上传数据
    user_boundary = GISDataManager.get_data("boundary", location, auto_fetch=False)
    user_water = GISDataManager.get_data("water", location, auto_fetch=False)
    user_road = GISDataManager.get_data("road", location, auto_fetch=False)
    user_residential = GISDataManager.get_data("residential", location, auto_fetch=False)

    # 如果有用户数据，优先使用
    if user_boundary or user_water or user_road or user_residential:
        logger.info(f"[GISCoverage] 使用用户上传数据: {location}")

    # 自动获取数据（仅在没有用户数据时）
    auto_result = fetcher.fetch_all_gis_data(location, buffer_km, max_features=100)

    # 合并数据源：用户数据覆盖自动获取数据
    def get_geojson_with_source(data_type: str, user_data: Optional[Dict], auto_data: Optional[Dict]) -> tuple[Optional[Dict], str]:
        """获取 GeoJSON 数据并标记来源"""
        if user_data:
            return user_data, "user_upload"
        if auto_data and auto_data.get("success") and auto_data.get("geojson"):
            return auto_data.get("geojson"), "auto_fetch"
        return None, "missing"

    boundary_geojson, boundary_source = get_geojson_with_source(
        "boundary", user_boundary, auto_result.get("boundary")
    )
    water_geojson, water_source = get_geojson_with_source(
        "water", user_water, auto_result.get("water")
    )
    road_geojson, road_source = get_geojson_with_source(
        "road", user_road, auto_result.get("road")
    )
    residential_geojson, residential_source = get_geojson_with_source(
        "residential", user_residential, auto_result.get("residential")
    )

    data_sources = {
        "boundary": boundary_source,
        "water": water_source,
        "road": road_source,
        "residential": residential_source,
    }

    # 统计可用数据和特征数
    water_success = water_geojson is not None
    road_success = road_geojson is not None
    residential_success = residential_geojson is not None
    boundary_success = boundary_geojson is not None

    water_count = len(water_geojson.get("features", [])) if water_geojson else 0
    road_count = len(road_geojson.get("features", [])) if road_geojson else 0
    residential_count = len(residential_geojson.get("features", [])) if residential_geojson else 0

    coverage_rate = sum([water_success, road_success, residential_success]) / 3

    layers = []
    type_mapping = {
        "boundary": {"layerType": "boundary", "layerName": "行政边界", "color": "#333333"},
        "water": {"layerType": "sensitivity_zone", "layerName": "水系", "color": "#87CEEB"},
        "road": {"layerType": "development_axis", "layerName": "道路", "color": "#FF6B6B"},
        "residential": {"layerType": "function_zone", "layerName": "居民地", "color": "#FFD700"},
    }

    # 添加边界层
    if boundary_success and boundary_geojson and boundary_geojson.get("features"):
        layers.append({
            "geojson": boundary_geojson,
            "layerType": "boundary",
            "layerName": "行政边界",
            "color": "#333333",
            "source": boundary_source,
        })

    # 添加其他图层
    for category, mapping in type_mapping.items():
        if category == "boundary":
            continue

        geojson = None
        source = data_sources.get(category, "missing")

        if category == "water":
            geojson = water_geojson
        elif category == "road":
            geojson = road_geojson
        elif category == "residential":
            geojson = residential_geojson

        if geojson and geojson.get("features"):
            layers.append({
                "geojson": geojson,
                "layerType": mapping["layerType"],
                "layerName": mapping["layerName"],
                "color": mapping["color"],
                "source": source,
            })

    return _format_success_response({
        "location": location,
        "coverage_rate": coverage_rate,
        "layers_available": {
            "water": water_success,
            "road": road_success,
            "residential": residential_success,
            "boundary": boundary_success,
        },
        "feature_counts": {
            "water": water_count,
            "road": road_count,
            "residential": residential_count,
        },
        "center": auto_result.get("center"),
        "layers": layers,
        "data_sources": data_sources,  # 添加数据来源信息
    })


def wrap_spatial_layout_generator(context: Dict[str, Any]) -> str:
    """Wrapper for spatial layout generator tool."""
    from .spatial_layout_generator import generate_spatial_layout_from_json
    from .planning_schema import VillagePlanningScheme

    village_boundary = context.get("village_boundary")
    road_network = context.get("road_network")
    planning_scheme_dict = context.get("planning_scheme")

    planning_scheme = None
    if planning_scheme_dict:
        try:
            if isinstance(planning_scheme_dict, dict):
                planning_scheme = VillagePlanningScheme(**planning_scheme_dict)
            else:
                planning_scheme = planning_scheme_dict
        except Exception as e:
            return _format_error_response(f"Invalid planning scheme: {str(e)}")

    if planning_scheme is None:
        return _format_error_response("Missing planning_scheme parameter")

    result = generate_spatial_layout_from_json(
        village_boundary=village_boundary,
        road_network=road_network,
        planning_scheme=planning_scheme,
        fallback_grid=context.get("fallback_grid", True),
        merge_threshold=context.get("merge_threshold", 0.01)
    )

    if result.get("success"):
        data = result.get("data", {})
        stats = data.get("statistics", {})
        return _format_success_response({
            "geojson": data.get("geojson"),
            "zones_geojson": data.get("zones_geojson"),
            "facilities_geojson": data.get("facilities_geojson"),
            "axes_geojson": data.get("axes_geojson"),
            "zone_count": stats.get("zone_count", 0),
            "facility_count": stats.get("facility_count", 0),
            "axis_count": stats.get("axis_count", 0),
            "total_area_km2": stats.get("total_area_km2", 0),
            "center": data.get("center"),
        })

    return _format_error_response(result.get("error", "Spatial layout generation failed"))


# Tool name to wrapper mapping
GIS_TOOL_WRAPPERS = {
    "isochrone_analysis": wrap_isochrone_analysis,
    "planning_vectorizer": wrap_planning_vectorizer,
    "facility_validator": wrap_facility_validator,
    "ecological_sensitivity": wrap_ecological_sensitivity,
    "gis_data_fetch": wrap_gis_data_fetch,
    "wfs_data_fetch": wrap_gis_data_fetch,
    "accessibility_analysis": wrap_accessibility_analysis,
    "poi_search": wrap_poi_search,
    "gis_coverage_calculator": wrap_gis_coverage_calculator,
    "spatial_layout_generator": wrap_spatial_layout_generator,
}


def get_gis_tool_wrapper(tool_name: str):
    """Get wrapper function for a GIS tool"""
    return GIS_TOOL_WRAPPERS.get(tool_name)


__all__ = [
    "GIS_TOOL_WRAPPERS",
    "get_gis_tool_wrapper",
    "wrap_isochrone_analysis",
    "wrap_planning_vectorizer",
    "wrap_facility_validator",
    "wrap_ecological_sensitivity",
    "wrap_gis_data_fetch",
    "wrap_accessibility_analysis",
    "wrap_poi_search",
    "wrap_gis_coverage_calculator",
    "wrap_spatial_layout_generator",
]