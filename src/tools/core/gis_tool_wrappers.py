"""
GIS Tool Wrappers for ToolRegistry

Wraps GIS tool functions to match ToolRegistry.execute_tool signature.
ToolRegistry expects: tool_func(context: Dict[str, Any]) -> str

These wrappers convert the context dict to function-specific parameters
and format the output as a string or JSON.
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


def wrap_spatial_overlay(context: Dict[str, Any]) -> str:
    """Wrapper for spatial overlay analysis tool."""
    from .spatial_analysis import run_spatial_overlay

    result = run_spatial_overlay(
        operation=context.get("operation", "intersect"),
        layer_a=context.get("layer_a", {}),
        layer_b=context.get("layer_b", {})
    )

    if result.get("success"):
        data = result.get("data", {})
        return _format_success_response({
            "feature_count": data.get("feature_count", 0),
            "total_area_km2": data.get("total_area_km2", 0),
            "geojson": data.get("geojson")
        })
    return _format_error_response(result.get("error", "Unknown error"))


def wrap_spatial_query(context: Dict[str, Any]) -> str:
    """Wrapper for spatial query tool."""
    from .spatial_analysis import run_spatial_query

    result = run_spatial_query(
        query_type=context.get("query_type", "intersects"),
        geometry=context.get("geometry", {}),
        target_layer=context.get("target_layer", {}),
        max_distance=context.get("max_distance", 1000),
        limit=context.get("limit", 100)
    )

    return _wrap_tool_response(result, ["match_count", "returned_count", "geojson"])


def wrap_isochrone_analysis(context: Dict[str, Any]) -> str:
    """Wrapper for isochrone analysis tool."""
    from .isochrone_analysis import generate_isochrones

    center = context.get("center", [0, 0])
    if isinstance(center, list) and len(center) == 2:
        center = tuple(center)

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
    village_center = context.get("village_center")
    if isinstance(village_center, list) and len(village_center) == 2:
        village_center = tuple(village_center)

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

    location = context.get("location", [0, 0])
    if isinstance(location, list) and len(location) == 2:
        location = tuple(location)

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


def wrap_map_renderer(context: Dict[str, Any]) -> str:
    """Wrapper for map rendering tool."""
    from .map_renderer import render_planning_map

    center = context.get("center")
    if isinstance(center, list) and len(center) == 2:
        center = tuple(center)

    result = render_planning_map(
        layers=context.get("layers", []),
        title=context.get("title", "村庄规划图"),
        center=center
    )

    if result.get("success"):
        data = result.get("data", {})
        return _format_success_response({
            "map_html_length": len(data.get("map_html", "")),
            "layer_info": data.get("layer_info", []),
            "center": data.get("center")
        })
    return _format_error_response(result.get("error", "Unknown error"))


def wrap_gis_data_fetch(context: Dict[str, Any]) -> str:
    """Wrapper for GIS data fetcher tool."""
    from .gis_data_fetcher import GISDataFetcher

    fetcher = GISDataFetcher()
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


# Tool name to wrapper mapping
GIS_TOOL_WRAPPERS = {
    "spatial_overlay": wrap_spatial_overlay,
    "spatial_query": wrap_spatial_query,
    "isochrone_analysis": wrap_isochrone_analysis,
    "planning_vectorizer": wrap_planning_vectorizer,
    "facility_validator": wrap_facility_validator,
    "ecological_sensitivity": wrap_ecological_sensitivity,
    "map_renderer": wrap_map_renderer,
    "gis_data_fetch": wrap_gis_data_fetch,
}


def get_gis_tool_wrapper(tool_name: str):
    """Get wrapper function for a GIS tool"""
    return GIS_TOOL_WRAPPERS.get(tool_name)


__all__ = [
    "GIS_TOOL_WRAPPERS",
    "get_gis_tool_wrapper",
    "wrap_spatial_overlay",
    "wrap_spatial_query",
    "wrap_isochrone_analysis",
    "wrap_planning_vectorizer",
    "wrap_facility_validator",
    "wrap_ecological_sensitivity",
    "wrap_map_renderer",
    "wrap_gis_data_fetch",
]