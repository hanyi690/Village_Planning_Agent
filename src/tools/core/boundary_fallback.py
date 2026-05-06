"""
Boundary Fallback Core Logic

Generates proxy boundary data when user-uploaded boundary is unavailable.
Follows strategy priority: user_uploaded -> isochrone -> polygonize_fusion
-> morphological_convex -> bbox_buffer.

Reference: GIS Planning Visualization Architecture - Boundary Fallback Mechanism
"""

from typing import Dict, Any, List, Optional, Tuple
from ...config.boundary_fallback import (
    BoundaryStrategy,
    BoundaryFallbackConfig,
    BOUNDARY_FALLBACK_CONFIG,
)
from ...utils.logger import get_logger

logger = get_logger(__name__)


def generate_proxy_boundary_with_fallback(
    center: Tuple[float, float],
    village_name: str,
    gis_data: Dict[str, Any],
    config: Optional[BoundaryFallbackConfig] = None,
    skip_user_upload: bool = False,
) -> Dict[str, Any]:
    """
    Generate proxy boundary using fallback strategies.

    Strategy priority:
    1. user_uploaded: Check GISDataManager cache
    2. isochrone: Generate 15-minute walking isochrone
    3. polygonize_fusion: Geometric stitching with road/water lines
    4. morphological_convex: Convex/concave hull from RESA features
    5. bbox_buffer: 2km buffer rectangle (always succeeds)

    Args:
        center: Village center coordinates (lon, lat)
        village_name: Village name for cache lookup
        gis_data: Dictionary with 'water', 'road', 'residential' layers
        config: Custom configuration (uses default if None)
        skip_user_upload: Skip user_uploaded strategy (for force_generate)

    Returns:
        Dict with:
        - success: bool
        - geojson: GeoJSON Polygon or None
        - strategy_used: Strategy name that succeeded
        - fallback_history: List of attempted strategies with results
        - warnings: List of warning messages
        - stats: Statistics about the generated boundary
    """
    if config is None:
        config = BOUNDARY_FALLBACK_CONFIG

    fallback_history: List[Dict[str, Any]] = []
    warnings: List[str] = []

    # Determine starting strategy
    start_idx = 0 if skip_user_upload else 0

    for strategy in config.strategy_priority[start_idx:]:
        if config.log_fallback_steps:
            logger.info(f"[boundary_fallback] Attempting strategy: {strategy}")

        strategy_result = _execute_strategy(
            strategy=strategy,
            center=center,
            village_name=village_name,
            gis_data=gis_data,
            config=config,
        )

        fallback_history.append({
            "strategy": strategy,
            "success": strategy_result.get("success", False),
            "reason": strategy_result.get("reason", ""),
            "stats": strategy_result.get("stats", {}),
        })

        if strategy_result.get("success"):
            if config.log_fallback_steps:
                logger.info(f"[boundary_fallback] Strategy {strategy} succeeded")

            return {
                "success": True,
                "geojson": strategy_result.get("geojson"),
                "strategy_used": strategy,
                "fallback_history": fallback_history,
                "warnings": warnings,
                "stats": strategy_result.get("stats", {}),
            }

        # Strategy failed, log reason and continue
        reason = strategy_result.get("reason", "Unknown error")
        if config.log_fallback_steps:
            logger.warning(f"[boundary_fallback] Strategy {strategy} failed: {reason}")
        warnings.append(f"{strategy}: {reason}")

        if not config.continue_on_failure:
            # Stop on first failure
            break

    # All strategies failed (should never reach here since bbox_buffer always succeeds)
    logger.error("[boundary_fallback] All strategies failed unexpectedly")
    return {
        "success": False,
        "geojson": None,
        "strategy_used": None,
        "fallback_history": fallback_history,
        "warnings": warnings,
        "stats": {},
        "error": "All boundary generation strategies failed",
    }


def _execute_strategy(
    strategy: BoundaryStrategy,
    center: Tuple[float, float],
    village_name: str,
    gis_data: Dict[str, Any],
    config: BoundaryFallbackConfig,
) -> Dict[str, Any]:
    """Execute a specific boundary generation strategy"""

    strategy_funcs = {
        "user_uploaded": _strategy_user_uploaded,
        "isochrone": _strategy_isochrone,
        "polygonize_fusion": _strategy_polygonize_fusion,
        "morphological_convex": _strategy_morphological,
        "bbox_buffer": _strategy_bbox_buffer,
    }

    func = strategy_funcs.get(strategy)
    if func is None:
        return {"success": False, "reason": f"Unknown strategy: {strategy}"}

    try:
        return func(center, village_name, gis_data, config)
    except Exception as e:
        logger.error(f"[boundary_fallback] Strategy {strategy} exception: {e}")
        return {"success": False, "reason": f"Exception: {str(e)}"}


def _strategy_user_uploaded(
    center: Tuple[float, float],
    village_name: str,
    gis_data: Dict[str, Any],
    config: BoundaryFallbackConfig,
) -> Dict[str, Any]:
    """Check for user-uploaded boundary in GISDataManager"""

    try:
        from ..gis.data_manager import GISDataManager

        cached = GISDataManager.get_user_data(village_name, "boundary")
        if cached and cached.geojson:
            features = cached.geojson.get("features", [])
            if features:
                # Return first polygon feature
                for feature in features:
                    geom = feature.get("geometry", {})
                    if geom.get("type") == "Polygon":
                        return {
                            "success": True,
                            "geojson": geom,
                            "reason": "",
                            "stats": {
                                "source": "user_upload",
                                "feature_count": len(features),
                            }
                        }

                # No polygon feature found
                return {
                    "success": False,
                    "reason": "User data contains no polygon geometry",
                }

        return {"success": False, "reason": "User did not upload boundary data"}

    except ImportError:
        return {"success": False, "reason": "GISDataManager not available"}


def _strategy_isochrone(
    center: Tuple[float, float],
    village_name: str,
    gis_data: Dict[str, Any],
    config: BoundaryFallbackConfig,
) -> Dict[str, Any]:
    """Generate boundary using isochrone analysis"""

    try:
        from .isochrone_analysis import generate_isochrones

        result = generate_isochrones(
            center=center,
            time_minutes=[config.isochrone_time_minutes],
            travel_mode=config.isochrone_travel_mode,
            sample_points=config.isochrone_sample_points,
            use_route_api=False,  # Use circular approximation for reliability
        )

        if result.get("success"):
            data = result.get("data", {})
            geojson = data.get("geojson", {})
            features = geojson.get("features", [])

            if features:
                # Return the isochrone polygon
                first_feature = features[0]
                geom = first_feature.get("geometry", {})

                isochrones = data.get("isochrones", [])
                stats = {}
                if isochrones:
                    iso = isochrones[0]
                    stats = {
                        "time_minutes": iso.get("time_minutes"),
                        "radius_km": iso.get("radius_km"),
                        "travel_mode": iso.get("travel_mode"),
                    }

                return {
                    "success": True,
                    "geojson": geom,
                    "reason": "",
                    "stats": stats,
                }

        return {
            "success": False,
            "reason": result.get("error", "Isochrone generation failed"),
        }

    except ImportError as e:
        return {"success": False, "reason": f"isochrone_analysis not available: {e}"}


def _strategy_polygonize_fusion(
    center: Tuple[float, float],
    village_name: str,
    gis_data: Dict[str, Any],
    config: BoundaryFallbackConfig,
) -> Dict[str, Any]:
    """
    Generate boundary using polygonize fusion (geometric stitching).

    Requires:
    - Isochrone boundary (as base)
    - Natural lines (road/water) >= polygonize_min_lines
    """

    try:
        from .vector_editor import trim_polygon_with_lines
        from .isochrone_analysis import generate_isochrones
        from shapely.geometry import Point, Polygon, shape

        # Step 1: Get isochrone as base polygon
        iso_result = generate_isochrones(
            center=center,
            time_minutes=[config.isochrone_time_minutes],
            travel_mode=config.isochrone_travel_mode,
            sample_points=config.isochrone_sample_points,
            use_route_api=False,
        )

        if not iso_result.get("success"):
            return {
                "success": False,
                "reason": "Isochrone generation failed for polygonize_fusion",
            }

        iso_geojson = iso_result.get("data", {}).get("geojson", {})
        iso_features = iso_geojson.get("features", [])
        if not iso_features:
            return {"success": False, "reason": "No isochrone features"}

        base_polygon = shape(iso_features[0].get("geometry", {}))
        if not isinstance(base_polygon, Polygon):
            return {"success": False, "reason": "Isochrone is not a polygon"}

        # Step 2: Collect natural lines (road + water)
        natural_lines = []

        for data_type in ["road", "water"]:
            layer_data = gis_data.get(data_type)
            if layer_data:
                features = layer_data.get("features", [])
                for feature in features:
                    geom = feature.get("geometry", {})
                    if geom.get("type") in ["LineString", "MultiLineString"]:
                        natural_lines.append(feature)

        # Check minimum line requirement
        if len(natural_lines) < config.polygonize_min_lines:
            return {
                "success": False,
                "reason": f"Insufficient lines: {len(natural_lines)} < {config.polygonize_min_lines}",
            }

        # Step 3: Apply trim_polygon_with_lines
        core_point = Point(center)
        trim_result = trim_polygon_with_lines(
            base_polygon=base_polygon,
            natural_lines=natural_lines,
            core_point=core_point,
            extend_lines=config.polygonize_extend_lines,
            min_area_km2=config.polygonize_min_area_km2,
            use_projection=True,
        )

        if trim_result.get("success") and trim_result.get("data", {}).get("trimmed"):
            data = trim_result.get("data", {})
            return {
                "success": True,
                "geojson": data.get("geojson"),
                "reason": "",
                "stats": {
                    "area_km2": data.get("area_km2"),
                    "perimeter_km": data.get("perimeter_km"),
                    "line_count": len(natural_lines),
                }
            }

        return {
            "success": False,
            "reason": trim_result.get("data", {}).get("reason", "Polygonize fusion failed"),
        }

    except ImportError as e:
        return {"success": False, "reason": f"vector_editor not available: {e}"}


def _strategy_morphological(
    center: Tuple[float, float],
    village_name: str,
    gis_data: Dict[str, Any],
    config: BoundaryFallbackConfig,
) -> Dict[str, Any]:
    """
    Generate boundary using morphological envelope (convex/concave hull).

    Requires RESA (residential) features >= morphological_min_features.
    """

    try:
        from .vector_editor import compute_convex_hull, compute_concave_hull

        # Get residential features
        residential_data = gis_data.get("residential")
        if not residential_data:
            return {"success": False, "reason": "No residential data available"}

        features = residential_data.get("features", [])
        if len(features) < config.morphological_min_features:
            return {
                "success": False,
                "reason": f"Insufficient features: {len(features)} < {config.morphological_min_features}",
            }

        # Prepare geometries for hull computation
        geometries = features  # Pass features directly, compute_*_hull handles parsing

        # Try concave hull first if enabled
        if config.morphological_use_concave:
            concave_result = compute_concave_hull(
                geometries=geometries,
                alpha=config.morphological_alpha,
                allow_holes=False,
            )

            if concave_result.get("success"):
                data = concave_result.get("data", {})
                return {
                    "success": True,
                    "geojson": data.get("geojson"),
                    "reason": "",
                    "stats": {
                        "geometry_type": "concave_hull",
                        "alpha": config.morphological_alpha,
                        "area_km2": data.get("area_km2"),
                        "input_count": data.get("input_point_count", len(features)),
                    }
                }

        # Fallback to convex hull
        convex_result = compute_convex_hull(geometries=geometries)

        if convex_result.get("success"):
            data = convex_result.get("data", {})
            return {
                "success": True,
                "geojson": data.get("geojson"),
                "reason": "",
                "stats": {
                    "geometry_type": "convex_hull",
                    "area_km2": data.get("area_km2"),
                    "input_count": data.get("input_count", len(features)),
                }
            }

        return {
            "success": False,
            "reason": convex_result.get("error", "Hull computation failed"),
        }

    except ImportError as e:
        return {"success": False, "reason": f"vector_editor not available: {e}"}


def _strategy_bbox_buffer(
    center: Tuple[float, float],
    village_name: str,
    gis_data: Dict[str, Any],
    config: BoundaryFallbackConfig,
) -> Dict[str, Any]:
    """
    Generate boundary using bbox buffer rectangle.

    This is the final fallback strategy and always succeeds.
    Creates a square buffer around the center point.
    """

    try:
        from shapely.geometry import Polygon
        import geopandas as gpd
    except ImportError:
        # Create polygon manually without geopandas
        buffer_km = config.bbox_buffer_km
        buffer_deg = buffer_km / 111.0  # Approximate degree conversion

        min_lon = center[0] - buffer_deg
        max_lon = center[0] + buffer_deg
        min_lat = center[1] - buffer_deg
        max_lat = center[1] + buffer_deg

        coords = [
            [min_lon, min_lat],
            [max_lon, min_lat],
            [max_lon, max_lat],
            [min_lon, max_lat],
            [min_lon, min_lat],  # Close polygon
        ]

        geojson = {"type": "Polygon", "coordinates": [coords]}
        area_km2 = (buffer_km * 2) ** 2  # Approximate area

        return {
            "success": True,
            "geojson": geojson,
            "reason": "",
            "stats": {
                "geometry_type": "bbox_buffer",
                "buffer_km": buffer_km,
                "area_km2": round(area_km2, 4),
            }
        }

    # With geopandas for accurate area calculation
    buffer_km = config.bbox_buffer_km
    buffer_deg = buffer_km / 111.0

    min_lon = center[0] - buffer_deg
    max_lon = center[0] + buffer_deg
    min_lat = center[1] - buffer_deg
    max_lat = center[1] + buffer_deg

    coords = [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lat, max_lat],
        [min_lon, min_lat],
    ]

    polygon = Polygon(coords)
    geojson = {"type": "Polygon", "coordinates": [coords]}

    # Calculate accurate area
    try:
        gdf_temp = gpd.GeoDataFrame([{"geometry": polygon}], crs="EPSG:4326")
        gdf_proj = gdf_temp.to_crs(epsg=3857)
        area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
    except Exception:
        area_km2 = (buffer_km * 2) ** 2

    return {
        "success": True,
        "geojson": geojson,
        "reason": "",
        "stats": {
            "geometry_type": "bbox_buffer",
            "buffer_km": buffer_km,
            "area_km2": round(area_km2, 4),
        }
    }


__all__ = [
    "generate_proxy_boundary_with_fallback",
]