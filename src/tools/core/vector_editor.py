"""
Vector Editor Core Logic

Creates vector data for planning: function zones, development axes,
facility points. Supports planning digitization workflow.

Reference: Planning workflow requires converting planning decisions
to GIS-compatible vector formats.
"""

from typing import Dict, Any, List, Optional, Tuple, Literal
import math
from ...utils.logger import get_logger

logger = get_logger(__name__)

try:
    import geopandas as gpd
    import shapely.geometry as geom
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[vector_editor] geopandas/shapely not available")


# Planning zone type definitions
ZONE_TYPE_DEFINITIONS = {
    "居住用地": {
        "code": "R",
        "color": "#FFD700",
        "description": "Residential land",
        "min_area_ha": 0.5,
    },
    "产业用地": {
        "code": "M",
        "color": "#FF6B6B",
        "description": "Industrial/production land",
        "min_area_ha": 1.0,
    },
    "公共服务用地": {
        "code": "C",
        "color": "#4A90D9",
        "description": "Public service land",
        "min_area_ha": 0.2,
    },
    "生态绿地": {
        "code": "G",
        "color": "#90EE90",
        "description": "Ecological green space",
        "min_area_ha": 0.1,
    },
    "交通用地": {
        "code": "T",
        "color": "#808080",
        "description": "Transportation land",
        "min_area_ha": 0.05,
    },
    "水域": {
        "code": "W",
        "color": "#87CEEB",
        "description": "Water body",
        "min_area_ha": 0.01,
    },
    "农业用地": {
        "code": "A",
        "color": "#8B4513",
        "description": "Agricultural land",
        "min_area_ha": 1.0,
    },
    "商业用地": {
        "code": "B",
        "color": "#FFA500",
        "description": "Commercial land",
        "min_area_ha": 0.1,
    },
}

# Facility status definitions
FACILITY_STATUS = {
    "现状保留": {"icon": "home", "color": "green", "description": "Existing to preserve"},
    "规划新建": {"icon": "plus", "color": "blue", "description": "Planned new facility"},
    "规划改扩建": {"icon": "edit", "color": "orange", "description": "Planned expansion"},
    "规划迁建": {"icon": "move", "color": "purple", "description": "Planned relocation"},
}


def create_function_zones(
    zones: List[Dict[str, Any]],
    village_center: Optional[Tuple[float, float]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Create function zone vector layer (polygon features)

    Each zone is defined by name, type, and boundary coordinates.
    Supports both explicit coordinates and relative positioning.

    Args:
        zones: List of zone definitions
            [{"name": str, "type": str, "coordinates": [[lon,lat], ...],
              "area_ha": float (optional), "properties": dict (optional)}, ...]
        village_center: Optional village center for relative positioning
        **kwargs: Additional parameters
            - crs: Target CRS (default: EPSG:4326)
            - validate_geometry: Whether to validate geometries

    Returns:
        Dict with success status and GeoJSON FeatureCollection
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "Vector creation requires geopandas. Install: pip install geopandas"
        }

    try:
        features = []
        total_area = 0
        crs = kwargs.get("crs", "EPSG:4326")
        validate = kwargs.get("validate_geometry", True)

        for zone in zones:
            zone_name = zone.get("name", "Unnamed Zone")
            zone_type = zone.get("type", "未分类")
            coords = zone.get("coordinates", [])
            properties = zone.get("properties", {})

            # Get zone type definition
            type_def = ZONE_TYPE_DEFINITIONS.get(zone_type, {
                "code": "X",
                "color": "#CCCCCC",
            })

            if not coords:
                logger.warning(f"[vector_editor] Zone '{zone_name}' missing coordinates")
                continue

            # Create polygon geometry
            try:
                # Ensure polygon is closed
                if coords[0] != coords[-1]:
                    coords.append(coords[0])

                polygon = geom.Polygon(coords)

                if validate and not polygon.is_valid:
                    # Try to fix invalid polygon
                    polygon = polygon.buffer(0)

                if not polygon.is_valid:
                    logger.warning(f"[vector_editor] Invalid polygon for '{zone_name}'")
                    continue

            except Exception as e:
                logger.warning(f"[vector_editor] Geometry creation failed for '{zone_name}': {e}")
                continue

            # Calculate area
            area_ha = zone.get("area_ha")
            if area_ha is None:
                try:
                    # Project for accurate area
                    gdf_temp = gpd.GeoDataFrame([{"geometry": polygon}], crs=crs)
                    gdf_proj = gdf_temp.to_crs(epsg=3857)
                    area_ha = gdf_proj.geometry.area.sum() / 10_000
                except Exception:
                    area_ha = 0

            total_area += area_ha

            # Create feature
            feature = {
                "type": "Feature",
                "properties": {
                    "name": zone_name,
                    "zone_type": zone_type,
                    "zone_code": type_def.get("code", "X"),
                    "color": type_def.get("color", "#CCCCCC"),
                    "area_ha": round(area_ha, 2),
                    "description": properties.get("description", type_def.get("description", "")),
                    **properties,
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords],
                }
            }
            features.append(feature)

        result_geojson = {"type": "FeatureCollection", "features": features}

        # Zone type summary
        zone_summary = {}
        for feature in features:
            z_type = feature["properties"]["zone_type"]
            zone_summary[z_type] = zone_summary.get(z_type, 0) + feature["properties"]["area_ha"]

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "feature_count": len(features),
                "total_area_ha": round(total_area, 2),
                "zone_summary": {k: round(v, 2) for k, v in zone_summary.items()},
                "metadata": {
                    "crs": crs,
                    "validate_geometry": validate,
                }
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Function zone creation failed: {e}")
        return {"success": False, "error": f"Function zone creation failed: {str(e)}"}


def create_development_axis(
    axis_data: List[Dict[str, Any]],
    **kwargs
) -> Dict[str, Any]:
    """
    Create development axis vector layer (line features)

    Development axes represent major growth corridors or transportation links.

    Args:
        axis_data: List of axis definitions
            [{"name": str, "axis_type": str, "coordinates": [[lon,lat], ...],
              "properties": dict (optional)}, ...]
        **kwargs: Additional parameters
            - width_m: Axis width for buffer (optional)

    Returns:
        Dict with success status and GeoJSON FeatureCollection
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "Vector creation requires geopandas"
        }

    try:
        features = []
        total_length = 0

        for axis in axis_data:
            axis_name = axis.get("name", "Unnamed Axis")
            axis_type = axis.get("axis_type", "发展主轴")
            coords = axis.get("coordinates", [])
            properties = axis.get("properties", {})

            if len(coords) < 2:
                logger.warning(f"[vector_editor] Axis '{axis_name}' needs at least 2 points")
                continue

            # Create line geometry
            try:
                line = geom.LineString(coords)
            except Exception as e:
                logger.warning(f"[vector_editor] Line creation failed for '{axis_name}': {e}")
                continue

            # Calculate length
            try:
                gdf_temp = gpd.GeoDataFrame([{"geometry": line}], crs="EPSG:4326")
                gdf_proj = gdf_temp.to_crs(epsg=3857)
                length_km = gdf_proj.geometry.length.sum() / 1000
            except Exception:
                length_km = 0

            total_length += length_km

            # Create feature
            feature = {
                "type": "Feature",
                "properties": {
                    "name": axis_name,
                    "axis_type": axis_type,
                    "length_km": round(length_km, 2),
                    "color": "#FF0000" if axis_type == "发展主轴" else "#00FF00",
                    **properties,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                }
            }
            features.append(feature)

        result_geojson = {"type": "FeatureCollection", "features": features}

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "feature_count": len(features),
                "total_length_km": round(total_length, 2),
                "metadata": {
                    "axis_count": len(axis_data),
                }
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Development axis creation failed: {e}")
        return {"success": False, "error": f"Development axis creation failed: {str(e)}"}


def create_facility_points(
    facilities: List[Dict[str, Any]],
    **kwargs
) -> Dict[str, Any]:
    """
    Create facility point vector layer (point features)

    Each facility is defined by name, type, coordinates, and status.

    Args:
        facilities: List of facility definitions
            [{"name": str, "facility_type": str, "coordinates": [lon, lat],
              "status": str, "properties": dict (optional)}, ...]
        **kwargs: Additional parameters

    Returns:
        Dict with success status and GeoJSON FeatureCollection
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "Vector creation requires geopandas"
        }

    try:
        features = []
        facility_by_type = {}

        for facility in facilities:
            facility_name = facility.get("name", "Unnamed Facility")
            facility_type = facility.get("facility_type", "其他")
            coords = facility.get("coordinates", [0, 0])
            status = facility.get("status", "规划新建")
            properties = facility.get("properties", {})

            if len(coords) < 2:
                logger.warning(f"[vector_editor] Facility '{facility_name}' missing coordinates")
                continue

            # Get status definition
            status_def = FACILITY_STATUS.get(status, {
                "icon": "circle",
                "color": "gray",
            })

            # Create point geometry
            point = geom.Point(coords)

            # Create feature
            feature = {
                "type": "Feature",
                "properties": {
                    "name": facility_name,
                    "facility_type": facility_type,
                    "status": status,
                    "icon": status_def.get("icon", "circle"),
                    "color": status_def.get("color", "gray"),
                    "description": status_def.get("description", ""),
                    **properties,
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": coords,
                }
            }
            features.append(feature)

            # Count by type
            facility_by_type[facility_type] = facility_by_type.get(facility_type, 0) + 1

        result_geojson = {"type": "FeatureCollection", "features": features}

        # Status summary
        status_summary = {}
        for feature in features:
            status = feature["properties"]["status"]
            status_summary[status] = status_summary.get(status, 0) + 1

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "feature_count": len(features),
                "facility_by_type": facility_by_type,
                "status_summary": status_summary,
                "metadata": {
                    "input_count": len(facilities),
                }
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Facility point creation failed: {e}")
        return {"success": False, "error": f"Facility point creation failed: {str(e)}"}


def create_planning_boundary(
    boundary_coords: List[List[float]],
    boundary_name: str = "规划范围",
    **kwargs
) -> Dict[str, Any]:
    """
    Create planning boundary polygon

    Args:
        boundary_coords: Boundary coordinates [[lon, lat], ...]
        boundary_name: Boundary name
        **kwargs: Additional parameters

    Returns:
        Dict with success status and GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "Vector creation requires geopandas"}

    try:
        # Ensure polygon is closed
        if boundary_coords[0] != boundary_coords[-1]:
            boundary_coords.append(boundary_coords[0])

        polygon = geom.Polygon(boundary_coords)

        # Calculate area
        try:
            gdf_temp = gpd.GeoDataFrame([{"geometry": polygon}], crs="EPSG:4326")
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000
        except Exception:
            area_km2 = 0
            perimeter_km = 0

        feature = {
            "type": "Feature",
            "properties": {
                "name": boundary_name,
                "area_km2": round(area_km2, 2),
                "perimeter_km": round(perimeter_km, 2),
                "boundary_type": "规划范围",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [boundary_coords],
            }
        }

        result_geojson = {"type": "FeatureCollection", "features": [feature]}

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "area_km2": round(area_km2, 2),
                "perimeter_km": round(perimeter_km, 2),
                "centroid": [polygon.centroid.x, polygon.centroid.y],
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Boundary creation failed: {e}")
        return {"success": False, "error": f"Boundary creation failed: {str(e)}"}


def create_planning_layers_from_text(
    planning_text: str,
    village_center: Tuple[float, float],
    **kwargs
) -> Dict[str, Any]:
    """
    Create vector layers from planning text description

    Parses planning text to extract zone/facility definitions and creates
    corresponding vector layers. This is a placeholder for LLM-based parsing.

    Args:
        planning_text: Planning description text
        village_center: Village center coordinates for positioning
        **kwargs: Additional parameters

    Returns:
        Dict with success status and created layers
    """
    # This function would use LLM to parse planning text
    # For now, return placeholder
    return {
        "success": True,
        "data": {
            "note": "LLM-based text parsing not yet implemented",
            "planning_text_length": len(planning_text),
            "village_center": village_center,
        },
        "implementation_needed": "Integrate with LLM for text-to-vector conversion"
    }


def merge_vector_layers(
    layers: List[Dict[str, Any]],
    **kwargs
) -> Dict[str, Any]:
    """
    Merge multiple vector layers into one GeoJSON

    Args:
        layers: List of GeoJSON FeatureCollections
        **kwargs: Additional parameters

    Returns:
        Dict with merged GeoJSON
    """
    try:
        all_features = []

        for layer in layers:
            features = layer.get("features", [])
            all_features.extend(features)

        merged_geojson = {"type": "FeatureCollection", "features": all_features}

        return {
            "success": True,
            "data": {
                "geojson": merged_geojson,
                "feature_count": len(all_features),
                "layer_count": len(layers),
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Layer merge failed: {e}")
        return {"success": False, "error": f"Layer merge failed: {str(e)}"}


def format_vector_result(result: Dict[str, Any]) -> str:
    """Format vector creation result to string"""
    if not result.get("success"):
        return f"Vector creation failed: {result.get('error', 'Unknown error')}"

    data = result.get("data", {})
    lines = ["Vector Creation Result:"]

    if "feature_count" in data:
        lines.append(f"- Features created: {data['feature_count']}")

    if "total_area_ha" in data:
        lines.append(f"- Total area: {data['total_area_ha']} ha")

    if "total_length_km" in data:
        lines.append(f"- Total length: {data['total_length_km']} km")

    if "zone_summary" in data:
        lines.append("- Zone breakdown:")
        for z_type, area in data["zone_summary"].items():
            lines.append(f"  * {z_type}: {area} ha")

    if "facility_by_type" in data:
        lines.append("- Facility breakdown:")
        for f_type, count in data["facility_by_type"].items():
            lines.append(f"  * {f_type}: {count}")

    return "\n".join(lines)


__all__ = [
    "create_function_zones",
    "create_development_axis",
    "create_facility_points",
    "create_planning_boundary",
    "create_planning_layers_from_text",
    "merge_vector_layers",
    "format_vector_result",
    "ZONE_TYPE_DEFINITIONS",
    "FACILITY_STATUS",
]