"""
GIS Spatial Overlay Analysis Core Logic

Provides spatial overlay operations (intersect, union, difference, clip)
and spatial query functions (contains, intersects, within, nearest).

Reference: GeoPandas-AI design patterns for planning-specific GIS operations.
"""

from typing import Dict, Any, List, Optional, Literal, Tuple
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Check geopandas availability
try:
    import geopandas as gpd
    import shapely.geometry as geom
    from shapely.ops import nearest_points
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[spatial_analysis] geopandas/shapely not available")


def geojson_to_geodataframe(geojson: Dict[str, Any]) -> Optional[gpd.GeoDataFrame]:
    """
    Convert GeoJSON FeatureCollection to GeoDataFrame

    Args:
        geojson: GeoJSON FeatureCollection dict

    Returns:
        GeoDataFrame or None if conversion fails
    """
    if not GEOPANDAS_AVAILABLE:
        return None

    try:
        features = geojson.get("features", [])
        if not features:
            return None

        geometries = []
        properties = []

        for feature in features:
            geom_data = feature.get("geometry", {})
            props = feature.get("properties", {})

            geom_type = geom_data.get("type", "")
            coords = geom_data.get("coordinates", [])

            try:
                if geom_type == "Point":
                    geometries.append(geom.Point(coords))
                elif geom_type == "LineString":
                    geometries.append(geom.LineString(coords))
                elif geom_type == "Polygon":
                    # Polygon coords is [shell, hole1, hole2, ...]
                    geometries.append(geom.Polygon(coords[0], coords[1:]))
                elif geom_type == "MultiPoint":
                    geometries.append(geom.MultiPoint(coords))
                elif geom_type == "MultiLineString":
                    geometries.append(geom.MultiLineString(coords))
                elif geom_type == "MultiPolygon":
                    geometries.append(geom.MultiPolygon(coords))
                else:
                    geometries.append(None)
            except Exception as e:
                logger.warning(f"[spatial_analysis] Failed to create geometry: {e}")
                geometries.append(None)

            properties.append(props)

        # Filter out None geometries
        valid_indices = [i for i, g in enumerate(geometries) if g is not None]
        if not valid_indices:
            return None

        geometries = [geometries[i] for i in valid_indices]
        properties = [properties[i] for i in valid_indices]

        gdf = gpd.GeoDataFrame(properties, geometry=geometries)
        if gdf.crs is None:
            gdf.set_crs("EPSG:4326", inplace=True)

        return gdf

    except Exception as e:
        logger.error(f"[spatial_analysis] GeoJSON conversion failed: {e}")
        return None


def geodataframe_to_geojson(gdf: gpd.GeoDataFrame) -> Dict[str, Any]:
    """
    Convert GeoDataFrame to GeoJSON FeatureCollection

    Args:
        gdf: GeoDataFrame

    Returns:
        GeoJSON FeatureCollection dict
    """
    features = []

    for idx, row in gdf.iterrows():
        geometry = row.geometry
        if geometry is None:
            continue

        geom_type = geometry.geom_type
        coords = _get_geometry_coords(geometry)

        props = {k: v for k, v in row.items() if k != 'geometry'}
        # Convert non-serializable values
        for k, v in props.items():
            if hasattr(v, '__iter__') and not isinstance(v, (str, list, dict)):
                props[k] = list(v) if hasattr(v, '__iter__') else str(v)

        feature = {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": geom_type,
                "coordinates": coords
            }
        }
        features.append(feature)

    return {"type": "FeatureCollection", "features": features}


def _get_geometry_coords(geometry) -> List:
    """Extract coordinates from shapely geometry"""
    import json
    return json.loads(json.dumps(geometry.__geo_interface__))["coordinates"]


def run_spatial_overlay(
    operation: Literal["intersect", "union", "difference", "clip"],
    layer_a: Dict[str, Any],
    layer_b: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    Execute spatial overlay analysis

    Args:
        operation: Overlay operation type
            - intersect: Returns geometry common to both layers
            - union: Returns geometry from both layers combined
            - difference: Returns geometry from layer_a not in layer_b
            - clip: Clips layer_a by layer_b boundary
        layer_a: First layer (GeoJSON FeatureCollection)
        layer_b: Second layer (GeoJSON FeatureCollection)
        **kwargs: Additional parameters
            - keep_attributes: Which layer's attributes to keep (default: 'a')

    Returns:
        Dict with success status and result GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "Spatial overlay requires geopandas. Install: pip install geopandas shapely"
        }

    try:
        gdf_a = geojson_to_geodataframe(layer_a)
        gdf_b = geojson_to_geodataframe(layer_b)

        if gdf_a is None or gdf_b is None:
            return {"success": False, "error": "Invalid GeoJSON input"}

        # Ensure same CRS
        if gdf_a.crs != gdf_b.crs:
            gdf_b = gdf_b.to_crs(gdf_a.crs)

        keep_attrs = kwargs.get("keep_attributes", "a")

        if operation == "intersect":
            result_gdf = gpd.overlay(gdf_a, gdf_b, how="intersection")
        elif operation == "union":
            result_gdf = gpd.overlay(gdf_a, gdf_b, how="union")
        elif operation == "difference":
            result_gdf = gpd.overlay(gdf_a, gdf_b, how="difference")
        elif operation == "clip":
            # Clip preserves attributes of layer_a
            result_gdf = gpd.clip(gdf_a, gdf_b)
        else:
            return {"success": False, "error": f"Unknown operation: {operation}"}

        # Calculate statistics
        total_area = 0
        if len(result_gdf) > 0:
            try:
                # Project to meters for accurate area calculation
                projected = result_gdf.to_crs(epsg=3857)
                total_area = projected.geometry.area.sum() / 1_000_000  # km2
            except Exception:
                pass

        result_geojson = geodataframe_to_geojson(result_gdf)

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "operation": operation,
                "feature_count": len(result_gdf),
                "total_area_km2": round(total_area, 4),
                "metadata": {
                    "layer_a_features": len(gdf_a),
                    "layer_b_features": len(gdf_b),
                }
            }
        }

    except Exception as e:
        logger.error(f"[spatial_analysis] Overlay failed: {e}")
        return {"success": False, "error": f"Spatial overlay failed: {str(e)}"}


def run_spatial_query(
    query_type: Literal["contains", "intersects", "within", "nearest"],
    geometry: Dict[str, Any],
    target_layer: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    Execute spatial query

    Args:
        query_type: Query type
            - contains: Find features that contain the query geometry
            - intersects: Find features that intersect the query geometry
            - within: Find features within the query geometry
            - nearest: Find nearest features to the query geometry
        geometry: Query geometry (GeoJSON geometry object)
        target_layer: Target layer to query (GeoJSON FeatureCollection)
        **kwargs: Additional parameters
            - max_distance: Maximum distance for nearest query (meters)
            - limit: Maximum number of results

    Returns:
        Dict with success status and matching features
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "Spatial query requires geopandas. Install: pip install geopandas shapely"
        }

    try:
        # Convert query geometry
        geom_type = geometry.get("type", "")
        coords = geometry.get("coordinates", [])

        if geom_type == "Point":
            query_geom = geom.Point(coords)
        elif geom_type == "LineString":
            query_geom = geom.LineString(coords)
        elif geom_type == "Polygon":
            query_geom = geom.Polygon(coords)
        elif geom_type == "MultiPolygon":
            query_geom = geom.MultiPolygon(coords)
        else:
            return {"success": False, "error": f"Unsupported geometry type: {geom_type}"}

        # Convert target layer
        target_gdf = geojson_to_geodataframe(target_layer)
        if target_gdf is None:
            return {"success": False, "error": "Invalid target layer GeoJSON"}

        limit = kwargs.get("limit", 100)
        max_distance = kwargs.get("max_distance", 1000)  # meters

        matching_indices = []

        if query_type == "contains":
            # Find features that contain the query geometry
            mask = target_gdf.geometry.contains(query_geom)
            matching_indices = target_gdf[mask].index.tolist()

        elif query_type == "intersects":
            # Find features that intersect the query geometry
            mask = target_gdf.geometry.intersects(query_geom)
            matching_indices = target_gdf[mask].index.tolist()

        elif query_type == "within":
            # Find features that are within the query geometry
            mask = target_gdf.geometry.within(query_geom)
            matching_indices = target_gdf[mask].index.tolist()

        elif query_type == "nearest":
            # Find nearest features
            # Calculate distances from query geometry to all features
            distances = target_gdf.geometry.distance(query_geom)
            # Filter by max_distance and sort
            within_distance = distances[distances <= max_distance / 1000]  # Convert to km for EPSG:4326
            sorted_indices = within_distance.sort_values().index.tolist()
            matching_indices = sorted_indices[:limit]

        else:
            return {"success": False, "error": f"Unknown query type: {query_type}"}

        # Extract matching features
        matching_gdf = target_gdf.loc[matching_indices[:limit]]
        result_geojson = geodataframe_to_geojson(matching_gdf)

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "query_type": query_type,
                "match_count": len(matching_indices),
                "returned_count": len(matching_gdf),
                "query_geometry": geometry,
                "metadata": {
                    "target_layer_features": len(target_gdf),
                    "limit": limit,
                }
            }
        }

    except Exception as e:
        logger.error(f"[spatial_analysis] Query failed: {e}")
        return {"success": False, "error": f"Spatial query failed: {str(e)}"}


def calculate_buffer_zones(
    layer: Dict[str, Any],
    buffer_distance: float,
    **kwargs
) -> Dict[str, Any]:
    """
    Create buffer zones around features

    Args:
        layer: Input layer (GeoJSON FeatureCollection)
        buffer_distance: Buffer distance in meters
        **kwargs: Additional parameters
            - dissolve: Whether to dissolve overlapping buffers (default: False)
            - cap_style: Buffer cap style (1=round, 2=flat, 3=square)

    Returns:
        Dict with success status and buffer GeoJSON
    """
    if not GEOPANDAS_AVAILABLE:
        return {
            "success": False,
            "error": "Buffer requires geopandas. Install: pip install geopandas shapely"
        }

    try:
        gdf = geojson_to_geodataframe(layer)
        if gdf is None:
            return {"success": False, "error": "Invalid GeoJSON input"}

        # Project to meters for accurate buffer
        original_crs = gdf.crs
        gdf_projected = gdf.to_crs(epsg=3857) if original_crs.to_epsg() == 4326 else gdf

        dissolve = kwargs.get("dissolve", False)
        cap_style = kwargs.get("cap_style", 1)  # round

        # Create buffers
        buffered = gdf_projected.copy()
        buffered["geometry"] = gdf_projected.geometry.buffer(
            buffer_distance,
            cap_style=cap_style
        )

        if dissolve:
            # Dissolve overlapping buffers into single geometry
            buffered = buffered.dissolve()

        # Convert back to original CRS
        buffered = buffered.to_crs(original_crs)

        result_geojson = geodataframe_to_geojson(buffered)

        # Calculate total buffer area
        total_area_km2 = 0
        try:
            projected_buffer = buffered.to_crs(epsg=3857)
            total_area_km2 = projected_buffer.geometry.area.sum() / 1_000_000
        except Exception:
            pass

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "buffer_distance_m": buffer_distance,
                "dissolved": dissolve,
                "feature_count": len(buffered),
                "total_area_km2": round(total_area_km2, 4),
                "metadata": {
                    "input_features": len(gdf),
                    "cap_style": cap_style,
                }
            }
        }

    except Exception as e:
        logger.error(f"[spatial_analysis] Buffer failed: {e}")
        return {"success": False, "error": f"Buffer calculation failed: {str(e)}"}


def format_spatial_analysis_result(result: Dict[str, Any]) -> str:
    """Format spatial analysis result to string"""
    if not result.get("success"):
        return f"Spatial analysis failed: {result.get('error', 'Unknown error')}"

    data = result.get("data", {})
    operation = data.get("operation", data.get("query_type", "unknown"))
    lines = [f"Spatial Analysis Result ({operation}):"]

    if "feature_count" in data:
        lines.append(f"- Result features: {data['feature_count']}")
    if "match_count" in data:
        lines.append(f"- Matching features: {data['match_count']}")
    if "total_area_km2" in data:
        lines.append(f"- Total area: {data['total_area_km2']} km2")
    if "buffer_distance_m" in data:
        lines.append(f"- Buffer distance: {data['buffer_distance_m']} m")

    return "\n".join(lines)


__all__ = [
    "run_spatial_overlay",
    "run_spatial_query",
    "calculate_buffer_zones",
    "geojson_to_geodataframe",
    "geodataframe_to_geojson",
    "format_spatial_analysis_result",
]