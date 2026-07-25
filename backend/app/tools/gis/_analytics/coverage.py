"""
Coverage Calculator - GIS coverage via DataCatalog.

Calculates GIS data availability from local data sources.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.modules.data.catalog.catalog import DataCatalog
from app.utils.logger import get_logger

logger = get_logger(__name__)


def calculate_gis_coverage(
    location: str,
    buffer_km: float = 5.0,
    user_uploaded_data: Optional[Dict[str, Any]] = None,
    max_features: int = 100
) -> Dict[str, Any]:
    """Calculate GIS data coverage for a village.

    Data source priority: user uploaded > local file (DataCatalog).

    Args:
        location: Village name.
        buffer_km: Buffer radius in km (unused for local data).
        user_uploaded_data: User-uploaded GeoJSON dict.
        max_features: Max features (unused for local data).

    Returns:
        Coverage calculation result.
    """
    if not location:
        return {"success": False, "error": "missing location"}

    user_uploaded_data = user_uploaded_data or {}
    user_boundary = user_uploaded_data.get("boundary")
    user_water = user_uploaded_data.get("water")
    user_road = user_uploaded_data.get("road")
    user_residential = user_uploaded_data.get("residential")

    if user_boundary or user_water or user_road or user_residential:
        logger.info("[CoverageCalculator] Using user-uploaded data: %s", location)

    # Load from DataCatalog
    try:
        catalog = DataCatalog()
        bundle = catalog.load_village_bundle(location)
        has_boundary = bundle.boundary is not None
        has_landuse = len(bundle.polygons.landuse_current) > 0
        has_planned = len(bundle.polygons.landuse_planned) > 0
        has_roads = len(bundle.lines.roads_current) + len(bundle.lines.roads_planned) > 0
    except Exception as e:
        logger.warning("[CoverageCalculator] DataCatalog failed: %s", e)
        has_boundary = False
        has_landuse = False
        has_planned = False
        has_roads = False

    boundary_success = bool(user_boundary) or has_boundary
    water_success = bool(user_water)  # water data not in current bundle
    road_success = bool(user_road) or has_roads
    residential_success = bool(user_residential)

    coverage_rate = sum([water_success, road_success, residential_success]) / 3

    return {
        "success": True,
        "data": {
            "location": location,
            "coverage_rate": coverage_rate,
            "layers_available": {
                "water": water_success,
                "road": road_success,
                "residential": residential_success,
                "boundary": boundary_success,
            },
            "feature_counts": {
                "water": len(user_water.get("features", [])) if user_water else 0,
                "road": len(user_road.get("features", [])) if user_road else 0,
                "residential": len(user_residential.get("features", [])) if user_residential else 0,
            },
            "center": None,
            "layers": [],
            "data_sources": {
                "boundary": "user_upload" if user_boundary else ("local" if has_boundary else "missing"),
                "water": "user_upload" if user_water else "missing",
                "road": "user_upload" if user_road else ("local" if has_roads else "missing"),
                "residential": "user_upload" if user_residential else "missing",
            },
        }
    }


def format_coverage_result(result: Dict[str, Any]) -> str:
    """Format coverage calculation result to string."""
    if not result.get("success"):
        return f"Coverage calculation failed: {result.get('error', 'unknown error')}"

    data = result.get("data", {})
    lines = ["GIS data coverage:"]
    lines.append(f"- Location: {data.get('location')}")
    lines.append(f"- Coverage: {data.get('coverage_rate', 0):.2%}")

    layers = data.get("layers_available", {})
    lines.append("- Layer availability:")
    for layer, available in layers.items():
        status = "✓" if available else "✗"
        lines.append(f"  * {layer}: {status}")

    data_sources = data.get("data_sources", {})
    lines.append("- Data sources:")
    for layer, source in data_sources.items():
        lines.append(f"  * {layer}: {source}")

    return "\n".join(lines)


__all__ = ['calculate_gis_coverage', 'format_coverage_result']
