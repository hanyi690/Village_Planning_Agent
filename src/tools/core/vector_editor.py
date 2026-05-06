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
    from shapely.ops import unary_union, polygonize, nearest_points
    from shapely.geometry import Point, Polygon, LineString, MultiLineString, shape, mapping
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[vector_editor] geopandas/shapely not available")

try:
    import alphashape
    ALPHASHAPE_AVAILABLE = True
except ImportError:
    ALPHASHAPE_AVAILABLE = False


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


def compute_convex_hull(
    geometries: List[Any],
    **kwargs
) -> Dict[str, Any]:
    """Compute convex hull from a list of geometries

    Uses shapely.unary_union + .convex_hull to create minimum bounding polygon.

    Args:
        geometries: List of shapely geometry objects or GeoJSON features
        **kwargs: Additional parameters
            - crs: Target CRS (default: EPSG:4326)

    Returns:
        Dict with success status and convex hull GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "Vector creation requires geopandas/shapely"}

    try:
        crs = kwargs.get("crs", "EPSG:4326")
        shapely_geoms = []

        for g in geometries:
            if isinstance(g, dict) and "geometry" in g:
                # GeoJSON feature
                geom_data = g["geometry"]
                if geom_data["type"] == "Point":
                    shapely_geoms.append(Point(geom_data["coordinates"]))
                elif geom_data["type"] == "Polygon":
                    shapely_geoms.append(Polygon(geom_data["coordinates"][0]))
                elif geom_data["type"] == "LineString":
                    shapely_geoms.append(LineString(geom_data["coordinates"]))
                elif geom_data["type"] == "MultiPolygon":
                    for poly_coords in geom_data["coordinates"]:
                        shapely_geoms.append(Polygon(poly_coords[0]))
            elif hasattr(g, "geometry"):
                # GeoDataFrame row
                shapely_geoms.append(g.geometry)
            else:
                # Shapely geometry
                shapely_geoms.append(g)

        if not shapely_geoms:
            return {"success": False, "error": "No valid geometries provided"}

        # Union all geometries and compute convex hull
        union_geom = unary_union(shapely_geoms)
        convex_hull = union_geom.convex_hull

        if convex_hull.is_empty or not convex_hull.is_valid:
            return {"success": False, "error": "Failed to compute convex hull"}

        # Calculate area
        try:
            gdf_temp = gpd.GeoDataFrame([{"geometry": convex_hull}], crs=crs)
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000
        except Exception:
            area_km2 = 0
            perimeter_km = 0

        # Convert to GeoJSON
        coords = list(convex_hull.exterior.coords)
        geojson = {
            "type": "Polygon",
            "coordinates": [coords]
        }

        return {
            "success": True,
            "data": {
                "geojson": geojson,
                "geometry_type": "convex_hull",
                "input_count": len(shapely_geoms),
                "area_km2": round(area_km2, 4),
                "perimeter_km": round(perimeter_km, 4),
                "centroid": [convex_hull.centroid.x, convex_hull.centroid.y],
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Convex hull computation failed: {e}")
        return {"success": False, "error": f"Convex hull computation failed: {str(e)}"}


def compute_concave_hull(
    geometries: List[Any],
    alpha: float = 0.5,
    **kwargs
) -> Dict[str, Any]:
    """Compute concave hull (alpha shape) from a list of geometries

    Uses alphashape library to create tighter boundary around point distribution.

    Args:
        geometries: List of shapely geometry objects or GeoJSON features
        alpha: Alpha parameter (0-1, lower = more concave, default: 0.5)
        **kwargs: Additional parameters
            - crs: Target CRS (default: EPSG:4326)
            - allow_holes: Whether to allow holes in hull (default: False)

    Returns:
        Dict with success status and concave hull GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "Vector creation requires geopandas/shapely"}

    if not ALPHASHAPE_AVAILABLE:
        return {"success": False, "error": "Concave hull requires alphashape. Install: pip install alphashape"}

    try:
        crs = kwargs.get("crs", "EPSG:4326")
        allow_holes = kwargs.get("allow_holes", False)

        # Extract point coordinates from geometries
        points = []
        for g in geometries:
            if isinstance(g, dict) and "geometry" in g:
                geom_data = g["geometry"]
                if geom_data["type"] == "Point":
                    points.append(tuple(geom_data["coordinates"]))
                elif geom_data["type"] == "Polygon":
                    for coord in geom_data["coordinates"][0]:
                        points.append(tuple(coord))
                elif geom_data["type"] == "MultiPolygon":
                    for poly_coords in geom_data["coordinates"]:
                        for coord in poly_coords[0]:
                            points.append(tuple(coord))
            elif hasattr(g, "geometry"):
                geom_obj = g.geometry
                if geom_obj.geom_type == "Point":
                    points.append((geom_obj.x, geom_obj.y))
                elif geom_obj.geom_type in ["Polygon", "MultiPolygon"]:
                    for coord in geom_obj.exterior.coords:
                        points.append(coord)
            elif isinstance(g, Point):
                points.append((g.x, g.y))
            elif hasattr(g, "exterior"):
                for coord in g.exterior.coords:
                    points.append(coord)

        if len(points) < 4:
            logger.warning(f"[vector_editor] Not enough points for concave hull: {len(points)}")
            # Fallback to convex hull
            return compute_convex_hull(geometries, **kwargs)

        # Compute alpha shape
        concave_hull = alphashape.alphashape(points, alpha)

        if concave_hull.is_empty:
            # Try with lower alpha
            concave_hull = alphashape.alphashape(points, 0.0)

        if concave_hull.is_empty or not isinstance(concave_hull, Polygon):
            return {"success": False, "error": "Failed to compute concave hull"}

        # Remove holes if not allowed
        if not allow_holes and concave_hull.interiors:
            concave_hull = Polygon(concave_hull.exterior)

        # Calculate area
        try:
            gdf_temp = gpd.GeoDataFrame([{"geometry": concave_hull}], crs=crs)
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000
        except Exception:
            area_km2 = 0
            perimeter_km = 0

        # Convert to GeoJSON
        coords = list(concave_hull.exterior.coords)
        geojson = {
            "type": "Polygon",
            "coordinates": [coords]
        }

        return {
            "success": True,
            "data": {
                "geojson": geojson,
                "geometry_type": "concave_hull",
                "alpha": alpha,
                "input_point_count": len(points),
                "area_km2": round(area_km2, 4),
                "perimeter_km": round(perimeter_km, 4),
                "centroid": [concave_hull.centroid.x, concave_hull.centroid.y],
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Concave hull computation failed: {e}")
        return {"success": False, "error": f"Concave hull computation failed: {str(e)}"}


def polygonize_closed_regions(
    lines: List[Any],
    center: Point,
    **kwargs
) -> Dict[str, Any]:
    """Polygonize closed regions from line geometries and select nearest to center

    Uses shapely.ops.polygonize to convert line network into polygon regions,
    then selects the polygon containing or nearest to the center point.

    Args:
        lines: List of LineString geometries or GeoJSON line features
        center: Center point (shapely Point or [lon, lat] tuple)
        **kwargs: Additional parameters
            - max_distance_km: Maximum distance from center (default: 2.0)
            - crs: Target CRS (default: EPSG:4326)

    Returns:
        Dict with success status and selected polygon GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "Vector creation requires geopandas/shapely"}

    try:
        crs = kwargs.get("crs", "EPSG:4326")
        max_distance_km = kwargs.get("max_distance_km", 2.0)

        # Parse center point
        if isinstance(center, (list, tuple)):
            center_point = Point(center)
        else:
            center_point = center

        # Extract line geometries
        shapely_lines = []
        for line in lines:
            if isinstance(line, dict) and "geometry" in line:
                geom_data = line["geometry"]
                if geom_data["type"] == "LineString":
                    shapely_lines.append(LineString(geom_data["coordinates"]))
                elif geom_data["type"] == "MultiLineString":
                    for line_coords in geom_data["coordinates"]:
                        shapely_lines.append(LineString(line_coords))
            elif hasattr(line, "geometry"):
                shapely_lines.append(line.geometry)
            elif isinstance(line, LineString):
                shapely_lines.append(line)
            elif isinstance(line, MultiLineString):
                for geom in line.geoms:
                    shapely_lines.append(geom)

        if not shapely_lines:
            return {"success": False, "error": "No valid line geometries provided"}

        # Polygonize the line network
        polygons = list(polygonize(shapely_lines))

        if not polygons:
            # Try with buffer to close gaps
            buffered_lines = [line.buffer(0.001) for line in shapely_lines]
            union_buffered = unary_union(buffered_lines)
            polygons = [union_buffered] if union_buffered.geom_type == "Polygon" else []

        if not polygons:
            return {"success": False, "error": "Failed to polygonize lines"}

        # Find polygon containing or nearest to center
        containing_polygon = None
        nearest_polygon = None
        min_distance = float("inf")

        for poly in polygons:
            if not isinstance(poly, Polygon) or poly.is_empty:
                continue

            if poly.contains(center_point):
                containing_polygon = poly
                break

            distance = poly.distance(center_point)
            if distance < min_distance:
                min_distance = distance
                nearest_polygon = poly

        selected_polygon = containing_polygon or nearest_polygon

        if selected_polygon is None:
            return {"success": False, "error": "No polygon found near center"}

        # Check distance constraint
        if min_distance > max_distance_km * 1000 / 111320:  # Approximate degree conversion
            logger.warning(f"[vector_editor] Nearest polygon is {min_distance:.4f} degrees from center")

        # Calculate area
        try:
            gdf_temp = gpd.GeoDataFrame([{"geometry": selected_polygon}], crs=crs)
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000
        except Exception:
            area_km2 = 0
            perimeter_km = 0

        # Convert to GeoJSON
        coords = list(selected_polygon.exterior.coords)
        geojson = {
            "type": "Polygon",
            "coordinates": [coords]
        }

        return {
            "success": True,
            "data": {
                "geojson": geojson,
                "geometry_type": "natural_boundary",
                "input_line_count": len(shapely_lines),
                "polygon_count": len(polygons),
                "area_km2": round(area_km2, 4),
                "perimeter_km": round(perimeter_km, 4),
                "centroid": [selected_polygon.centroid.x, selected_polygon.centroid.y],
                "contains_center": containing_polygon is not None,
                "distance_to_center_deg": round(min_distance, 6) if min_distance != float("inf") else 0,
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Polygonization failed: {e}")
        return {"success": False, "error": f"Polygonization failed: {str(e)}"}


def generate_integrated_proxy_boundary(
    center: Tuple[float, float],
    isochrone_boundary: Optional[Dict] = None,
    morphological_core: Optional[Dict] = None,
    natural_lines: Optional[List] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate integrated proxy boundary using weighted hierarchy fusion.

    Fusion Strategies:
    - 'hierarchy' (default): Core -> Constraint -> Boundary weighted hierarchy
    - 'polygonize_fusion': Geometric stitching - break isochrone boundary into segments,
      merge with road/water lines, polygonize and select polygon containing core point

    Args:
        center: Village center (lon, lat)
        isochrone_boundary: Isochrone boundary GeoJSON (acts as ceiling)
        morphological_core: Morphological envelope GeoJSON (acts as seed)
        natural_lines: List of natural line features (roads/water)
        **kwargs:
            - clip_tolerance_km: Distance tolerance for clipping (default: 0.5)
            - min_core_coverage: Minimum core coverage threshold (default: 0.8)
            - fusion_strategy: 'hierarchy' or 'polygonize_fusion' (default: 'hierarchy')
            - use_projection: Use projected CRS for operations (default: True)
            - crs: Target CRS (default: EPSG:4326)

    Returns:
        Dict with success status and fused boundary GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "Vector creation requires geopandas/shapely"}

    try:
        crs = kwargs.get("crs", "EPSG:4326")
        clip_tolerance_km = kwargs.get("clip_tolerance_km", 0.5)
        min_core_coverage = kwargs.get("min_core_coverage", 0.8)
        fusion_strategy = kwargs.get("fusion_strategy", "hierarchy")
        use_projection = kwargs.get("use_projection", True)

        center_point = Point(center)

        # Step 1: Establish Isochrone as Ceiling (Soft Upper Bound)
        ceiling_poly = None
        if isochrone_boundary and isochrone_boundary.get("success"):
            iso_geojson = isochrone_boundary.get("geojson") or isochrone_boundary.get("data", {}).get("geojson")
            if iso_geojson:
                ceiling_poly = shape(iso_geojson)

        # Step 2: Establish Morphological Core (Seed - Absolute Safe Zone)
        core_poly = None
        if morphological_core and morphological_core.get("success"):
            # Prefer concave hull over convex
            core_geojson = morphological_core.get("concave", {}).get("geojson") or \
                          morphological_core.get("convex", {}).get("geojson")
            if core_geojson:
                core_poly = shape(core_geojson)

        # Step 3: Process Natural Lines for Clipping
        constraint_polys = []
        if natural_lines:
            shapely_lines = []
            for line in natural_lines:
                if isinstance(line, dict) and "geometry" in line:
                    geom_data = line["geometry"]
                    if geom_data["type"] == "LineString":
                        shapely_lines.append(LineString(geom_data["coordinates"]))
                    elif geom_data["type"] == "MultiLineString":
                        for line_coords in geom_data["coordinates"]:
                            shapely_lines.append(LineString(line_coords))
                elif isinstance(line, LineString):
                    shapely_lines.append(line)

            if shapely_lines and ceiling_poly:
                # Only keep lines within ceiling (prevent runaway polygonization)
                clipped_lines = []
                for line in shapely_lines:
                    if line.intersects(ceiling_poly):
                        clipped_lines.append(line)

                if clipped_lines:
                    # Try to polygonize lines within ceiling
                    line_union = unary_union(clipped_lines)
                    if line_union.intersects(ceiling_poly):
                        # Use ceiling intersection to create constraint regions
                        ceiling_buffered = ceiling_poly.buffer(clip_tolerance_km / 111.32)  # km to degrees
                        # Find lines that form partial boundaries
                        potential_polys = list(polygonize(clipped_lines))
                        for poly in potential_polys:
                            if poly.contains(center_point) and ceiling_poly.contains(poly.centroid):
                                constraint_polys.append(poly)

        # Step 4: Fusion Logic - Weighted Hierarchy Integration
        final_boundary = None
        fusion_method = "unknown"

        # NEW: Polygonize Fusion Strategy - Geometric Stitching
        if fusion_strategy == "polygonize_fusion" and ceiling_poly and natural_lines:
            logger.info("[vector_editor] Using polygonize_fusion strategy")

            # Determine core point for selection (use morphological centroid or isochrone center)
            core_point_for_selection = center_point
            if core_poly:
                core_point_for_selection = core_poly.centroid

            # Build natural lines list
            shapely_lines = []
            for line in natural_lines:
                if isinstance(line, dict) and "geometry" in line:
                    geom_data = line["geometry"]
                    if geom_data["type"] == "LineString":
                        shapely_lines.append(LineString(geom_data["coordinates"]))
                    elif geom_data["type"] == "MultiLineString":
                        for line_coords in geom_data["coordinates"]:
                            shapely_lines.append(LineString(line_coords))
                elif isinstance(line, LineString):
                    shapely_lines.append(line)
                elif isinstance(line, MultiLineString):
                    for ls in line.geoms:
                        shapely_lines.append(ls)

            # Call trim_polygon_with_lines for geometric stitching
            trim_result = trim_polygon_with_lines(
                base_polygon=ceiling_poly,
                natural_lines=shapely_lines,
                core_point=core_point_for_selection,
                use_projection=use_projection,
                min_area_km2=0.1,
                crs=crs
            )

            if trim_result.get("success") and trim_result.get("data", {}).get("trimmed"):
                final_boundary = shape(trim_result["data"]["geojson"])
                fusion_method = "polygonize_fusion"
                logger.info(f"[vector_editor] Polygonize fusion succeeded, area={trim_result['data']['area_km2']} km2")
            else:
                # Fallback to hierarchy strategy if polygonize_fusion fails
                logger.warning("[vector_editor] Polygonize fusion failed, falling back to hierarchy")
                fusion_strategy = "hierarchy"

        # Case A: Have ceiling (isochrone) - use as base (hierarchy strategy)
        if fusion_strategy == "hierarchy" and ceiling_poly:
            final_boundary = ceiling_poly
            fusion_method = "isochrone_base"

            # If we have core inside ceiling, expand to include core
            if core_poly:
                # Core should be inside boundary (coverage check)
                core_in_ceiling = ceiling_poly.intersection(core_poly)
                core_coverage = core_in_ceiling.area / core_poly.area if core_poly.area > 0 else 0

                if core_coverage >= min_core_coverage:
                    # Core is well-covered by ceiling, ceiling is good
                    pass
                else:
                    # Core extends outside ceiling, need to expand
                    # Union ceiling with core (but capped at reasonable extent)
                    logger.info(f"[vector_editor] Core coverage: {core_coverage:.2f}, expanding boundary")
                    final_boundary = unary_union([ceiling_poly, core_poly])

            # Apply natural constraint clipping if available
            if constraint_polys:
                # Find the smallest constraint poly that contains center
                smallest_constraint = None
                for cp in constraint_polys:
                    if cp.contains(center_point):
                        if smallest_constraint is None or cp.area < smallest_constraint.area:
                            smallest_constraint = cp

                if smallest_constraint and smallest_constraint.area < final_boundary.area:
                    # Clip final boundary to constraint if it's smaller and contains center
                    intersection = final_boundary.intersection(smallest_constraint)
                    if not intersection.is_empty and intersection.contains(center_point):
                        final_boundary = intersection
                        fusion_method = "isochrone_natural_clip"

        # Case B: No ceiling or hierarchy strategy failed, use core as base
        if final_boundary is None and core_poly:
            final_boundary = core_poly
            fusion_method = "morphological_core"

            # Expand core slightly to account for edge effects
            buffer_deg = clip_tolerance_km / 111.32
            final_boundary = final_boundary.buffer(buffer_deg)

        # Case C: No data and no boundary set, return error
        if final_boundary is None:
            return {"success": False, "error": "No valid boundary components provided"}

        # Validate final boundary
        if final_boundary is None or final_boundary.is_empty:
            return {"success": False, "error": "Fusion produced empty boundary"}

        # Ensure it's a Polygon (not MultiPolygon)
        if final_boundary.geom_type == "MultiPolygon":
            # Select the polygon containing center
            for poly in final_boundary.geoms:
                if poly.contains(center_point):
                    final_boundary = poly
                    break
            if final_boundary.geom_type == "MultiPolygon":
                # Fallback: select largest polygon
                final_boundary = max(final_boundary.geoms, key=lambda p: p.area)

        # Calculate statistics
        try:
            gdf_temp = gpd.GeoDataFrame([{"geometry": final_boundary}], crs=crs)
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000
        except Exception:
            area_km2 = 0
            perimeter_km = 0

        # Convert to GeoJSON
        coords = list(final_boundary.exterior.coords)
        geojson = {
            "type": "Polygon",
            "coordinates": [coords]
        }

        return {
            "success": True,
            "data": {
                "geojson": geojson,
                "geometry_type": "integrated_fusion",
                "fusion_method": fusion_method,
                "area_km2": round(area_km2, 4),
                "perimeter_km": round(perimeter_km, 4),
                "centroid": [final_boundary.centroid.x, final_boundary.centroid.y],
                "components": {
                    "has_ceiling": ceiling_poly is not None,
                    "has_core": core_poly is not None,
                    "has_constraints": len(constraint_polys) > 0,
                    "constraint_count": len(constraint_polys)
                }
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Integrated boundary fusion failed: {e}")
        return {"success": False, "error": f"Integrated boundary fusion failed: {str(e)}"}


def clip_boundary_with_lines(
    boundary: Polygon,
    lines: List[Any],
    center: Point,
    max_clip_km: float = 1.0,
    **kwargs
) -> Dict[str, Any]:
    """
    Clip boundary polygon using nearby natural lines (roads/water).

    This function finds lines that intersect with the boundary and uses them
    to create a tighter boundary around the center point.

    Args:
        boundary: Boundary polygon to clip
        lines: List of LineString features (roads/water)
        center: Center point (village location)
        max_clip_km: Maximum clipping distance from center (km)
        **kwargs:
            - crs: Target CRS (default: EPSG:4326)

    Returns:
        Dict with clipped boundary GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "Vector creation requires geopandas/shapely"}

    try:
        crs = kwargs.get("crs", "EPSG:4326")

        # Convert max_clip_km to degrees (approximate)
        max_clip_deg = max_clip_km / 111.32

        # Extract line geometries
        shapely_lines = []
        for line in lines:
            if isinstance(line, dict) and "geometry" in line:
                geom_data = line["geometry"]
                if geom_data["type"] == "LineString":
                    shapely_lines.append(LineString(geom_data["coordinates"]))
                elif geom_data["type"] == "MultiLineString":
                    for line_coords in geom_data["coordinates"]:
                        shapely_lines.append(LineString(line_coords))
            elif isinstance(line, LineString):
                shapely_lines.append(line)

        if not shapely_lines:
            return {"success": False, "error": "No valid lines provided"}

        # Find lines near boundary edge
        boundary_buffered = boundary.buffer(-max_clip_deg)  # Inner buffer
        edge_lines = []

        for line in shapely_lines:
            # Lines that are near boundary edge (inside boundary, not too close to center)
            if line.intersects(boundary) and not line.intersects(boundary_buffered):
                # Line is near the edge of boundary
                edge_lines.append(line)

        if not edge_lines:
            # No suitable clipping lines found
            logger.info("[vector_editor] No edge lines found for clipping")
            return {
                "success": True,
                "data": {
                    "geojson": mapping(boundary),
                    "clipped": False,
                    "reason": "No edge lines found"
                }
            }

        # Create clipping mask from edge lines
        line_union = unary_union(edge_lines)

        # Buffer lines to create cutting regions
        line_buffer = line_union.buffer(max_clip_deg / 2)

        # Subtract line buffer from boundary
        clipped_boundary = boundary.difference(line_buffer)

        # If clipping removed center, use intersection instead
        if clipped_boundary.is_empty or (isinstance(clipped_boundary, Polygon) and not clipped_boundary.contains(center)):
            # Try smaller buffer
            smaller_buffer = line_union.buffer(max_clip_deg / 4)
            clipped_boundary = boundary.difference(smaller_buffer)

        # If still fails, return original
        if clipped_boundary.is_empty:
            clipped_boundary = boundary
            clipped = False
        else:
            clipped = True

        # Handle MultiPolygon result
        if clipped_boundary.geom_type == "MultiPolygon":
            for poly in clipped_boundary.geoms:
                if poly.contains(center):
                    clipped_boundary = poly
                    break

        # Calculate stats
        try:
            gdf_temp = gpd.GeoDataFrame([{"geometry": clipped_boundary}], crs=crs)
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000
        except Exception:
            area_km2 = 0
            perimeter_km = 0

        return {
            "success": True,
            "data": {
                "geojson": mapping(clipped_boundary),
                "clipped": clipped,
                "edge_line_count": len(edge_lines),
                "area_km2": round(area_km2, 4),
                "perimeter_km": round(perimeter_km, 4)
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Boundary clipping failed: {e}")
        return {"success": False, "error": f"Boundary clipping failed: {str(e)}"}


def trim_polygon_with_lines(
    base_polygon: Polygon,
    natural_lines: List[Any],
    core_point: Point,
    **kwargs
) -> Dict[str, Any]:
    """
    Trim base polygon boundary using natural lines (roads/water) via geometric stitching.

    Core logic:
    1. Break base polygon boundary into individual line segments
    2. Clip natural_lines to inside of base_polygon
    3. Merge all segments and use polygonize() to generate closed regions
    4. Select the polygon containing the core_point

    Args:
        base_polygon: Base polygon (e.g., isochrone boundary)
        natural_lines: List of LineString features (roads/water from WFS)
        core_point: Core point (morphological envelope centroid)
        **kwargs:
            - extend_lines: Whether to extend lines to boundary (default: True)
            - min_area_km2: Minimum polygon area threshold (default: 0.1)
            - crs: Target CRS (default: EPSG:4326)
            - use_projection: Whether to use projected CRS for operations (default: True)

    Returns:
        Dict with trimmed boundary GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {"success": False, "error": "Vector creation requires geopandas/shapely"}

    try:
        crs = kwargs.get("crs", "EPSG:4326")
        extend_lines = kwargs.get("extend_lines", True)
        min_area_km2 = kwargs.get("min_area_km2", 0.1)
        use_projection = kwargs.get("use_projection", True)

        # Step 1: Project to EPSG:3857 for accurate operations if enabled
        if use_projection:
            try:
                from pyproj import Transformer
                from shapely.ops import transform

                transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
                base_polygon_proj = transform(transformer.transform, base_polygon)
                core_point_proj = transform(transformer.transform, core_point)

                inverse_transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
            except ImportError:
                logger.warning("[vector_editor] pyproj not available, using degrees")
                use_projection = False
                base_polygon_proj = base_polygon
                core_point_proj = core_point
        else:
            base_polygon_proj = base_polygon
            core_point_proj = core_point

        # Step 2: Break base polygon boundary into individual line segments
        boundary_segments = []
        exterior_coords = list(base_polygon_proj.exterior.coords)
        for i in range(len(exterior_coords) - 1):
            segment = LineString([exterior_coords[i], exterior_coords[i + 1]])
            boundary_segments.append(segment)

        # Handle interior rings (holes) if present
        if hasattr(base_polygon_proj, "interiors"):
            for interior in base_polygon_proj.interiors:
                interior_coords = list(interior.coords)
                for i in range(len(interior_coords) - 1):
                    segment = LineString([interior_coords[i], interior_coords[i + 1]])
                    boundary_segments.append(segment)

        logger.info(f"[trim_polygon] Broken boundary into {len(boundary_segments)} segments")

        # Step 3: Extract and clip natural lines to inside of base polygon
        clipped_lines = []
        for line in natural_lines:
            if isinstance(line, dict) and "geometry" in line:
                geom_data = line["geometry"]
                line_geom = None
                if geom_data["type"] == "LineString":
                    line_geom = LineString(geom_data["coordinates"])
                elif geom_data["type"] == "MultiLineString":
                    # Flatten MultiLineString to individual LineStrings
                    for line_coords in geom_data["coordinates"]:
                        line_geom = LineString(line_coords)
                        # Project line if needed
                        if use_projection:
                            line_geom = transform(transformer.transform, line_geom)
                        # Clip line to inside of base polygon
                        if line_geom.intersects(base_polygon_proj):
                            clipped_part = line_geom.intersection(base_polygon_proj)
                            if clipped_part.geom_type == "LineString":
                                clipped_lines.append(clipped_part)
                            elif clipped_part.geom_type == "MultiLineString":
                                for part in clipped_part.geoms:
                                    clipped_lines.append(part)
                if line_geom and geom_data["type"] == "LineString":
                    # Project line if needed
                    if use_projection:
                        line_geom = transform(transformer.transform, line_geom)
                    # Clip line to inside of base polygon
                    if line_geom.intersects(base_polygon_proj):
                        clipped_part = line_geom.intersection(base_polygon_proj)
                        if clipped_part.geom_type == "LineString":
                            clipped_lines.append(clipped_part)
                        elif clipped_part.geom_type == "MultiLineString":
                            for part in clipped_part.geoms:
                                clipped_lines.append(part)
            elif isinstance(line, LineString):
                line_geom = line
                if use_projection:
                    line_geom = transform(transformer.transform, line_geom)
                if line_geom.intersects(base_polygon_proj):
                    clipped_part = line_geom.intersection(base_polygon_proj)
                    if clipped_part.geom_type == "LineString":
                        clipped_lines.append(clipped_part)
                    elif clipped_part.geom_type == "MultiLineString":
                        for part in clipped_part.geoms:
                            clipped_lines.append(part)
            elif isinstance(line, MultiLineString):
                for line_geom in line.geoms:
                    if use_projection:
                        line_geom = transform(transformer.transform, line_geom)
                    if line_geom.intersects(base_polygon_proj):
                        clipped_part = line_geom.intersection(base_polygon_proj)
                        if clipped_part.geom_type == "LineString":
                            clipped_lines.append(clipped_part)
                        elif clipped_part.geom_type == "MultiLineString":
                            for part in clipped_part.geoms:
                                clipped_lines.append(part)

        logger.info(f"[trim_polygon] Clipped {len(clipped_lines)} natural line segments")

        # Step 4: Optionally extend lines to boundary for better closure
        if extend_lines and clipped_lines:
            extended_lines = []
            for line in clipped_lines:
                if line.length > 0:
                    # Check if line endpoints are close to boundary
                    start_point = Point(line.coords[0])
                    end_point = Point(line.coords[-1])

                    # If endpoints are not on boundary, try to extend
                    if not base_polygon_proj.boundary.contains(start_point):
                        # Find nearest point on boundary
                        nearest_on_boundary = nearest_points(start_point, base_polygon_proj.boundary)[1]
                        if nearest_on_boundary.distance(start_point) < 500:  # 500m threshold in projected coords
                            extended_segment = LineString([nearest_on_boundary.coords[0], line.coords[0]])
                            extended_lines.append(extended_segment)

                    if not base_polygon_proj.boundary.contains(end_point):
                        nearest_on_boundary = nearest_points(end_point, base_polygon_proj.boundary)[1]
                        if nearest_on_boundary.distance(end_point) < 500:
                            extended_segment = LineString([line.coords[-1], nearest_on_boundary.coords[0]])
                            extended_lines.append(extended_segment)

            clipped_lines.extend(extended_lines)
            logger.info(f"[trim_polygon] Extended {len(extended_lines)} line segments")

        # Step 5: Merge boundary segments with natural lines
        all_segments = boundary_segments + clipped_lines

        if not all_segments:
            return {
                "success": True,
                "data": {
                    "geojson": mapping(base_polygon),
                    "trimmed": False,
                    "reason": "No segments to polygonize"
                }
            }

        # Step 6: Use polygonize to generate closed regions
        merged_union = unary_union(all_segments)
        potential_polys = list(polygonize(all_segments))

        logger.info(f"[trim_polygon] Polygonize produced {len(potential_polys)} polygons")

        if not potential_polys:
            # Fallback: return original polygon
            logger.warning("[trim_polygon] No polygons from polygonize, returning original")
            return {
                "success": True,
                "data": {
                    "geojson": mapping(base_polygon),
                    "trimmed": False,
                    "reason": "Polygonize failed to produce polygons"
                }
            }

        # Step 7: Select polygon containing core point
        selected_poly = None
        for poly in potential_polys:
            if poly.contains(core_point_proj):
                selected_poly = poly
                break

        # If no polygon contains core point, find nearest
        if selected_poly is None:
            min_dist = float("inf")
            for poly in potential_polys:
                dist = poly.distance(core_point_proj)
                if dist < min_dist:
                    min_dist = dist
                    selected_poly = poly
            if selected_poly:
                logger.warning(f"[trim_polygon] No polygon contains core point, using nearest (dist={min_dist:.1f}m)")

        # Step 8: Filter by minimum area
        if selected_poly and use_projection:
            poly_area_km2 = selected_poly.area / 1_000_000
            if poly_area_km2 < min_area_km2:
                logger.warning(f"[trim_polygon] Selected polygon too small ({poly_area_km2} km2), returning original")
                return {
                    "success": True,
                    "data": {
                        "geojson": mapping(base_polygon),
                        "trimmed": False,
                        "reason": f"Polygon too small: {poly_area_km2} km2"
                    }
                }

        # Step 9: Convert back to EPSG:4326 if projection was used
        if use_projection and selected_poly:
            selected_poly = transform(inverse_transformer.transform, selected_poly)

        # Calculate statistics
        try:
            gdf_temp = gpd.GeoDataFrame([{"geometry": selected_poly or base_polygon}], crs=crs)
            gdf_proj = gdf_temp.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000
        except Exception:
            area_km2 = 0
            perimeter_km = 0

        if selected_poly:
            coords = list(selected_poly.exterior.coords)
            geojson = {
                "type": "Polygon",
                "coordinates": [coords]
            }
        else:
            geojson = mapping(base_polygon)

        return {
            "success": True,
            "data": {
                "geojson": geojson,
                "trimmed": selected_poly is not None,
                "polygon_count": len(potential_polys),
                "boundary_segments": len(boundary_segments),
                "natural_segments": len(clipped_lines),
                "area_km2": round(area_km2, 4),
                "perimeter_km": round(perimeter_km, 4)
            }
        }

    except Exception as e:
        logger.error(f"[vector_editor] Polygon trimming failed: {e}")
        return {"success": False, "error": f"Polygon trimming failed: {str(e)}"}


__all__ = [
    "create_function_zones",
    "create_development_axis",
    "create_facility_points",
    "create_planning_boundary",
    "merge_vector_layers",
    "format_vector_result",
    "compute_convex_hull",
    "compute_concave_hull",
    "polygonize_closed_regions",
    "generate_integrated_proxy_boundary",
    "clip_boundary_with_lines",
    "trim_polygon_with_lines",
    "ZONE_TYPE_DEFINITIONS",
    "FACILITY_STATUS",
]