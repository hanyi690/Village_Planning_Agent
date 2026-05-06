"""
Village Boundary Proxy Verification Script

Verifies three proxy boundary estimation approaches:
1. Isochrone-based boundary (walking accessibility)
2. Morphological envelope (RESA distribution hull)
3. Natural boundary (HYDL + LRDL polygonization)

Output directory: output/boundary_proxy/
"""

import os
import sys
import json
import geopandas as gpd
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List
from shapely.geometry import Polygon, Point, shape, mapping
from shapely.ops import polygonize, unary_union

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Project imports
from src.tools.core.isochrone_analysis import generate_isochrones
from src.tools.core.vector_editor import (
    compute_convex_hull,
    compute_concave_hull,
    polygonize_closed_regions,
    generate_integrated_proxy_boundary,
    clip_boundary_with_lines,
    trim_polygon_with_lines,
)
from src.tools.core.spatial_analysis import geojson_to_geodataframe, geodataframe_to_geojson
from src.tools.geocoding.tianditu.wfs import WfsService
from src.tools.geocoding.tianditu import TiandituProvider
from src.core.config import TIANDITU_API_KEY
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Test location: Jintian Village, Meizhou (approximate center)
JINTIAN_CENTER = (115.891, 24.567)  # lon, lat

# Buffer radius for WFS queries (5km around center)
BUFFER_RADIUS_KM = 5.0

# Output directory
OUTPUT_DIR = "output/boundary_proxy"

# Actual boundary file path
ACTUAL_BOUNDARY_FILE = "docs/gis/jintian_boundary/admin_boundary_line.geojson"


def load_actual_boundary(filepath: str, center: Tuple[float, float]) -> Dict[str, Any]:
    """
    Load actual boundary data and find polygon containing the center point

    Steps:
    1. Read GeoJSON file
    2. Filter features with 界线说明="村界"
    3. Use shapely.ops.polygonize to convert LineString to Polygon
    4. Find polygon containing the center point

    Args:
        filepath: Path to GeoJSON file
        center: (lon, lat) tuple for village center

    Returns:
        Dict with success status, geometry, and stats
    """
    logger.info("=" * 50)
    logger.info("Loading actual boundary from GeoJSON")

    result = {
        "name": "Actual Boundary",
        "method": "Official village boundary",
        "success": False,
        "geojson": None,
        "stats": {}
    }

    try:
        # Load GeoJSON
        gdf = gpd.read_file(filepath)
        logger.info(f"  Loaded {len(gdf)} features")

        # Filter village boundaries
        village_bounds = gdf[gdf["界线说明"] == "村界"]
        logger.info(f"  Village boundaries: {len(village_bounds)}")

        if len(village_bounds) == 0:
            result["error"] = "No village boundary found"
            return result

        # Collect all line geometries for polygonization
        lines = []
        for geom in village_bounds.geometry:
            if geom.geom_type == "LineString":
                lines.append(geom)
            elif geom.geom_type == "MultiLineString":
                for line in geom.geoms:
                    lines.append(line)

        logger.info(f"  Total lines for polygonization: {len(lines)}")

        # Polygonize
        polygons = list(polygonize(lines))
        logger.info(f"  Polygonized regions: {len(polygons)}")

        if not polygons:
            # Try merging lines first
            merged_lines = unary_union(lines)
            polygons = list(polygonize([merged_lines]))

        if not polygons:
            result["error"] = "Failed to polygonize lines"
            return result

        # Find polygon containing center
        center_point = Point(center)
        containing_polygon = None

        for poly in polygons:
            if poly.contains(center_point):
                containing_polygon = poly
                break

        if containing_polygon is None:
            # Find nearest polygon
            min_dist = float("inf")
            for poly in polygons:
                dist = poly.distance(center_point)
                if dist < min_dist:
                    min_dist = dist
                    containing_polygon = poly
            logger.warning(f"  Center not contained in any polygon, using nearest (dist={min_dist:.4f})")

        if containing_polygon is None:
            result["error"] = "No polygon found near center"
            return result

        # Calculate area in projected CRS
        gdf_single = gpd.GeoDataFrame([{"geometry": containing_polygon}], crs="EPSG:4326")
        gdf_proj = gdf_single.to_crs(epsg=3857)
        area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
        perimeter_km = gdf_proj.geometry.length.sum() / 1000

        result["success"] = True
        result["geometry"] = containing_polygon
        result["geojson"] = mapping(containing_polygon)
        result["stats"] = {
            "area_km2": round(area_km2, 4),
            "perimeter_km": round(perimeter_km, 4),
            "source": filepath,
            "line_count": len(lines),
            "polygon_count": len(polygons),
            "contains_center": containing_polygon.contains(center_point)
        }

        # Save actual boundary
        actual_fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "name": "Actual Village Boundary",
                    "method": "Official boundary",
                    **result["stats"]
                },
                "geometry": result["geojson"]
            }]
        }
        save_geojson(actual_fc, "actual_boundary.geojson")

        logger.info(f"  Success: area={result['stats']['area_km2']} km²")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  Failed: {e}")

    return result


def compare_boundaries(proxy_boundary: Polygon, actual_boundary: Polygon) -> Dict[str, float]:
    """
    Calculate comparison metrics between proxy and actual boundaries

    Metrics:
    - area_diff_km2: Area difference (proxy - actual)
    - area_ratio: Area ratio (proxy / actual)
    - iou: Intersection over Union
    - coverage_rate: Proxy coverage of actual
    - actual_coverage_rate: Actual coverage of proxy

    Args:
        proxy_boundary: Proxy boundary polygon
        actual_boundary: Actual boundary polygon

    Returns:
        Dict with comparison metrics
    """
    try:
        # Project to EPSG:3857 for accurate area calculation
        gdf_proxy = gpd.GeoDataFrame([{"geometry": proxy_boundary}], crs="EPSG:4326")
        gdf_actual = gpd.GeoDataFrame([{"geometry": actual_boundary}], crs="EPSG:4326")

        gdf_proxy_proj = gdf_proxy.to_crs(epsg=3857)
        gdf_actual_proj = gdf_actual.to_crs(epsg=3857)

        proxy_proj = gdf_proxy_proj.geometry.iloc[0]
        actual_proj = gdf_actual_proj.geometry.iloc[0]

        # Calculate areas
        proxy_area = proxy_proj.area / 1_000_000  # km²
        actual_area = actual_proj.area / 1_000_000  # km²

        # Calculate intersection and union
        intersection = proxy_proj.intersection(actual_proj)
        union = proxy_proj.union(actual_proj)

        intersection_area = intersection.area / 1_000_000 if not intersection.is_empty else 0
        union_area = union.area / 1_000_000 if not union.is_empty else 0

        # IoU
        iou = intersection_area / union_area if union_area > 0 else 0

        # Coverage rates
        proxy_coverage_actual = intersection_area / actual_area if actual_area > 0 else 0
        actual_coverage_proxy = intersection_area / proxy_area if proxy_area > 0 else 0

        return {
            "area_diff_km2": round(proxy_area - actual_area, 4),
            "area_ratio": round(proxy_area / actual_area if actual_area > 0 else 0, 4),
            "iou": round(iou, 4),
            "coverage_rate": round(proxy_coverage_actual, 4),
            "actual_coverage_rate": round(actual_coverage_proxy, 4)
        }

    except Exception as e:
        logger.error(f"Comparison failed: {e}")
        return {}


def check_dependencies() -> Dict[str, bool]:
    """Check required dependencies availability"""
    deps = {}

    try:
        import geopandas
        deps["geopandas"] = True
    except ImportError:
        deps["geopandas"] = False
        logger.error("Missing: geopandas")

    try:
        import shapely
        deps["shapely"] = True
    except ImportError:
        deps["shapely"] = False
        logger.error("Missing: shapely")

    try:
        import alphashape
        deps["alphashape"] = True
    except ImportError:
        deps["alphashape"] = False
        logger.warning("Missing: alphashape (concave hull will fallback)")

    try:
        import matplotlib
        deps["matplotlib"] = True
    except ImportError:
        deps["matplotlib"] = False
        logger.warning("Missing: matplotlib (visualization disabled)")

    try:
        import contextily
        deps["contextily"] = True
    except ImportError:
        deps["contextily"] = False
        logger.warning("Missing: contextily (basemap disabled)")

    return deps


def create_bbox(center: Tuple[float, float], radius_km: float) -> Tuple[float, float, float, float]:
    """Create bounding box from center and radius"""
    lon, lat = center
    # Approximate degree conversion at mid-latitudes
    lon_offset = radius_km / 111.32
    lat_offset = radius_km / 110.54

    return (
        lon - lon_offset,  # min_lon
        lat - lat_offset,  # min_lat
        lon + lon_offset,  # max_lon
        lat + lat_offset   # max_lat
    )


def save_geojson(geojson: Dict[str, Any], filename: str) -> str:
    """Save GeoJSON to output directory"""
    filepath = os.path.join(OUTPUT_DIR, filename)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved: {filepath}")
    return filepath


def approach_1_isochrone(center: Tuple[float, float]) -> Dict[str, Any]:
    """
    Approach 1: Isochrone-based boundary

    Uses 15-minute walking isochrone as proxy boundary.
    Reflects actual accessibility based on road network.
    """
    logger.info("=" * 50)
    logger.info("Approach 1: Isochrone Boundary (15-min walk)")

    result = {
        "name": "等时圈边界",
        "method": "15分钟步行可达性分析",
        "success": False,
        "geojson": None,
        "stats": {}
    }

    try:
        # Generate 15-minute walking isochrone
        iso_result = generate_isochrones(
            center=center,
            time_minutes=[15],
            travel_mode="walk",
            sample_points=32
        )

        if not iso_result.get("success"):
            result["error"] = iso_result.get("error", "Unknown error")
            return result

        isochrones = iso_result["data"]["isochrones"]
        if not isochrones:
            result["error"] = "No isochrone generated"
            return result

        # Extract 15-minute boundary
        iso_15 = isochrones[0]
        boundary_geojson = iso_15["geojson"]

        # Calculate stats
        gdf = geojson_to_geodataframe(iso_result["data"]["geojson"])
        if gdf is not None:
            gdf_proj = gdf.to_crs(epsg=3857)
            area_km2 = gdf_proj.geometry.area.sum() / 1_000_000
            perimeter_km = gdf_proj.geometry.length.sum() / 1000

            result["stats"] = {
                "time_minutes": 15,
                "travel_mode": "walk",
                "radius_km": iso_15["radius_km"],
                "area_km2": round(area_km2, 4),
                "perimeter_km": round(perimeter_km, 4)
            }

        result["success"] = True
        result["geojson"] = boundary_geojson

        # Save to file
        feature_collection = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "name": "15分钟步行等时圈",
                    "method": "Approach 1",
                    **result["stats"]
                },
                "geometry": boundary_geojson
            }]
        }
        save_geojson(feature_collection, "isochrone_boundary.geojson")

        logger.info(f"  Success: area={result['stats']['area_km2']} km², radius={iso_15['radius_km']} km")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  Failed: {e}")

    return result


def approach_2_morphological(center: Tuple[float, float], bbox: Tuple[float, float, float, float]) -> Dict[str, Any]:
    """
    Approach 2: Morphological envelope

    Uses RESA (residential area) distribution to create boundary envelope.
    Creates both convex hull and concave hull (alpha shape).
    """
    logger.info("=" * 50)
    logger.info("Approach 2: Morphological Envelope (RESA)")

    result = {
        "name": "形态学包络线",
        "method": "居民地(RESA)分布包络",
        "success": False,
        "convex": {"success": False, "geojson": None, "stats": {}},
        "concave": {"success": False, "geojson": None, "stats": {}},
        "stats": {}
    }

    try:
        # Fetch RESA features from Tianditu WFS
        wfs = WfsService(TIANDITU_API_KEY)
        resa_result = wfs.get_residential_features(bbox, include_areas=True, include_points=True)

        if not resa_result.success:
            result["error"] = resa_result.error
            return result

        features = resa_result.data.get("geojson", {}).get("features", [])

        if not features:
            result["error"] = "No RESA features found in bbox"
            logger.warning(f"  No features in bbox: {bbox}")
            return result

        logger.info(f"  Found {len(features)} RESA features")
        result["stats"]["feature_count"] = len(features)

        # Compute convex hull
        convex_result = compute_convex_hull(features)
        if convex_result.get("success"):
            result["convex"]["success"] = True
            result["convex"]["geojson"] = convex_result["data"]["geojson"]
            result["convex"]["stats"] = {
                "area_km2": convex_result["data"]["area_km2"],
                "perimeter_km": convex_result["data"]["perimeter_km"]
            }

            # Save convex hull
            convex_fc = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {
                        "name": "RESA凸包边界",
                        "method": "Approach 2 - Convex Hull",
                        **result["convex"]["stats"]
                    },
                    "geometry": convex_result["data"]["geojson"]
                }]
            }
            save_geojson(convex_fc, "morphological_hull.geojson")
            logger.info(f"  Convex hull: area={result['convex']['stats']['area_km2']} km²")
        else:
            result["convex"]["error"] = convex_result.get("error")

        # Compute concave hull
        concave_result = compute_concave_hull(features, alpha=0.5)
        if concave_result.get("success"):
            result["concave"]["success"] = True
            result["concave"]["geojson"] = concave_result["data"]["geojson"]
            result["concave"]["stats"] = {
                "area_km2": concave_result["data"]["area_km2"],
                "perimeter_km": concave_result["data"]["perimeter_km"],
                "alpha": concave_result["data"]["alpha"],
                "input_points": concave_result["data"]["input_point_count"]
            }

            # Save concave hull
            concave_fc = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {
                        "name": "RESA凹包边界",
                        "method": "Approach 2 - Concave Hull (alpha=0.5)",
                        **result["concave"]["stats"]
                    },
                    "geometry": concave_result["data"]["geojson"]
                }]
            }
            save_geojson(concave_fc, "morphological_concave.geojson")
            logger.info(f"  Concave hull: area={result['concave']['stats']['area_km2']} km²")
        else:
            result["concave"]["error"] = concave_result.get("error")
            logger.warning(f"  Concave hull failed: {concave_result.get('error')}")

        # Mark overall success if at least one hull succeeded
        result["success"] = result["convex"]["success"] or result["concave"]["success"]

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  Failed: {e}")

    return result


def approach_3_natural_boundary(center: Tuple[float, float], bbox: Tuple[float, float, float, float]) -> Dict[str, Any]:
    """
    Approach 3: Natural boundary from geographic barriers

    Uses HYDL (water lines) and LRDL (roads) to create closed polygon regions.
    Selects the region nearest to village center.
    """
    logger.info("=" * 50)
    logger.info("Approach 3: Natural Boundary (HYDL + LRDL)")

    result = {
        "name": "自然闭合边界",
        "method": "水系(HYDL)+公路(LRDL)闭合切割",
        "success": False,
        "geojson": None,
        "stats": {}
    }

    try:
        # Fetch water and road features
        wfs = WfsService(TIANDITU_API_KEY)

        water_result = wfs.get_water_features(bbox, include_lines=True, include_areas=False)
        road_result = wfs.get_road_features(bbox, include_railways=True, include_roads=True)

        water_features = water_result.data.get("geojson", {}).get("features", []) if water_result.success else []
        road_features = road_result.data.get("geojson", {}).get("features", []) if road_result.success else []

        all_lines = water_features + road_features

        logger.info(f"  Water features: {len(water_features)}")
        logger.info(f"  Road features: {len(road_features)}")
        logger.info(f"  Total lines: {len(all_lines)}")

        if not all_lines:
            result["error"] = "No water/road features found in bbox"
            return result

        result["stats"]["line_count"] = len(all_lines)
        result["stats"]["water_count"] = len(water_features)
        result["stats"]["road_count"] = len(road_features)

        # Polygonize and select nearest to center
        from shapely.geometry import Point
        center_point = Point(center)

        poly_result = polygonize_closed_regions(all_lines, center_point)

        if not poly_result.get("success"):
            result["error"] = poly_result.get("error")
            logger.warning(f"  Polygonization failed: {poly_result.get('error')}")
            return result

        result["success"] = True
        result["geojson"] = poly_result["data"]["geojson"]
        result["stats"]["area_km2"] = poly_result["data"]["area_km2"]
        result["stats"]["perimeter_km"] = poly_result["data"]["perimeter_km"]
        result["stats"]["polygon_count"] = poly_result["data"]["polygon_count"]
        result["stats"]["contains_center"] = poly_result["data"]["contains_center"]

        # Save natural boundary
        natural_fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "name": "自然闭合边界",
                    "method": "Approach 3 - HYDL+LRDL Polygonization",
                    **result["stats"]
                },
                "geometry": poly_result["data"]["geojson"]
            }]
        }
        save_geojson(natural_fc, "natural_boundary.geojson")

        logger.info(f"  Success: area={result['stats']['area_km2']} km², polygons={result['stats']['polygon_count']}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  Failed: {e}")

    return result


def approach_4_integrated_fusion(
    center: Tuple[float, float],
    bbox: Tuple[float, float, float, float],
    isochrone_result: Dict[str, Any],
    morphological_result: Dict[str, Any],
    natural_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Approach 4: Integrated Fusion Boundary

    Uses weighted hierarchy integration:
    1. Isochrone as ceiling (soft upper bound)
    2. Morphological envelope as core (seed)
    3. Natural lines for clipping (constraint)

    Args:
        center: Village center coordinates
        bbox: Bounding box for WFS queries
        isochrone_result: Result from approach_1
        morphological_result: Result from approach_2
        natural_result: Result from approach_3

    Returns:
        Dict with success status and fused boundary
    """
    logger.info("=" * 50)
    logger.info("Approach 4: Integrated Fusion Boundary")

    result = {
        "name": "Integrated Fusion Boundary",
        "method": "Weighted hierarchy: isochrone ceiling + morphological core + natural clipping",
        "success": False,
        "geojson": None,
        "stats": {}
    }

    try:
        # Fetch natural lines for clipping
        wfs = WfsService(TIANDITU_API_KEY)
        water_result = wfs.get_water_features(bbox, include_lines=True, include_areas=False)
        road_result = wfs.get_road_features(bbox, include_railways=True, include_roads=True)

        water_features = water_result.data.get("geojson", {}).get("features", []) if water_result.success else []
        road_features = road_result.data.get("geojson", {}).get("features", []) if road_result.success else []
        natural_lines = water_features + road_features

        logger.info(f"  Natural lines for clipping: {len(natural_lines)}")

        # Call fusion function
        fusion_result = generate_integrated_proxy_boundary(
            center=center,
            isochrone_boundary=isochrone_result,
            morphological_core=morphological_result,
            natural_lines=natural_lines,
            clip_tolerance_km=0.3,
            min_core_coverage=0.7
        )

        if not fusion_result.get("success"):
            result["error"] = fusion_result.get("error")
            logger.warning(f"  Fusion failed: {fusion_result.get('error')}")
            return result

        result["success"] = True
        result["geojson"] = fusion_result["data"]["geojson"]
        result["stats"] = {
            "area_km2": fusion_result["data"]["area_km2"],
            "perimeter_km": fusion_result["data"]["perimeter_km"],
            "fusion_method": fusion_result["data"]["fusion_method"],
            "components": fusion_result["data"]["components"]
        }

        # Save integrated boundary
        fusion_fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "name": "Integrated Fusion Boundary",
                    "method": "Approach 4 - Weighted Hierarchy Integration",
                    **result["stats"]
                },
                "geometry": fusion_result["data"]["geojson"]
            }]
        }
        save_geojson(fusion_fc, "integrated_fusion_boundary.geojson")

        logger.info(f"  Success: area={result['stats']['area_km2']} km², method={result['stats']['fusion_method']}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  Failed: {e}")

    return result


def prepare_natural_lines_from_wfs(bbox: Tuple[float, float, float, float]) -> List[Dict]:
    """
    Prepare natural lines from WFS for geometric stitching.

    Fetches LRDL (roads) and HYDL (water lines) from Tianditu WFS,
    filters and flattens to valid LineString features.

    Args:
        bbox: Bounding box for WFS query

    Returns:
        List of GeoJSON features with LineString geometry
    """
    logger.info("=" * 50)
    logger.info("Preparing natural lines from WFS")

    wfs = WfsService(TIANDITU_API_KEY)

    natural_lines = []

    # Fetch road features (LRDL)
    road_result = wfs.get_road_features(bbox, include_railways=False, include_roads=True)
    if road_result.success:
        road_features = road_result.data.get("geojson", {}).get("features", [])
        logger.info(f"  Road features (LRDL): {len(road_features)}")
        natural_lines.extend(road_features)

    # Fetch water line features (HYDL)
    water_result = wfs.get_water_features(bbox, include_lines=True, include_areas=False)
    if water_result.success:
        water_features = water_result.data.get("geojson", {}).get("features", [])
        # Filter only line features (HYDL)
        water_lines = [f for f in water_features if f.get("geometry", {}).get("type") in ["LineString", "MultiLineString"]]
        logger.info(f"  Water line features (HYDL): {len(water_lines)}")
        natural_lines.extend(water_lines)

    logger.info(f"  Total natural lines prepared: {len(natural_lines)}")

    return natural_lines


def approach_5_polygonize_fusion(
    center: Tuple[float, float],
    bbox: Tuple[float, float, float, float],
    isochrone_result: Dict[str, Any],
    morphological_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Approach 5: Polygonize Fusion Boundary (Geometric Stitching)

    Uses trim_polygon_with_lines to:
    1. Break isochrone boundary into segments
    2. Merge with road/water lines
    3. Polygonize to generate closed regions
    4. Select polygon containing morphological centroid

    Args:
        center: Village center coordinates
        bbox: Bounding box for WFS queries
        isochrone_result: Result from approach_1
        morphological_result: Result from approach_2

    Returns:
        Dict with success status and stitched boundary
    """
    logger.info("=" * 50)
    logger.info("Approach 5: Polygonize Fusion Boundary (Geometric Stitching)")

    result = {
        "name": "Polygonize Fusion Boundary",
        "method": "Geometric stitching: isochrone segments + road/water lines -> polygonize",
        "success": False,
        "geojson": None,
        "stats": {}
    }

    try:
        # Check prerequisites
        if not isochrone_result.get("success") or not isochrone_result.get("geojson"):
            result["error"] = "Isochrone boundary required for polygonize_fusion"
            return result

        # Get isochrone polygon
        iso_geom = shape(isochrone_result["geojson"])

        # Get natural lines from WFS
        natural_lines = prepare_natural_lines_from_wfs(bbox)

        if not natural_lines:
            result["error"] = "No natural lines found for stitching"
            return result

        # Determine core point (use morphological centroid or isochrone center)
        core_point = Point(center)
        if morphological_result.get("success") and morphological_result.get("convex", {}).get("geojson"):
            convex_geom = shape(morphological_result["convex"]["geojson"])
            core_point = convex_geom.centroid
            logger.info(f"  Using morphological centroid as core point")

        # Call trim_polygon_with_lines for geometric stitching
        trim_result = trim_polygon_with_lines(
            base_polygon=iso_geom,
            natural_lines=natural_lines,
            core_point=core_point,
            use_projection=True,
            min_area_km2=0.1,
            extend_lines=True
        )

        if not trim_result.get("success"):
            result["error"] = trim_result.get("error", "Trimming failed")
            return result

        trim_data = trim_result.get("data", {})

        result["success"] = True
        result["geojson"] = trim_data["geojson"]
        result["stats"] = {
            "area_km2": trim_data.get("area_km2", 0),
            "perimeter_km": trim_data.get("perimeter_km", 0),
            "trimmed": trim_data.get("trimmed", False),
            "polygon_count": trim_data.get("polygon_count", 0),
            "boundary_segments": trim_data.get("boundary_segments", 0),
            "natural_segments": trim_data.get("natural_segments", 0)
        }

        # Save polygonize fusion boundary
        fusion_fc = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "name": "Polygonize Fusion Boundary v2",
                    "method": "Approach 5 - Geometric Stitching",
                    **result["stats"]
                },
                "geometry": result["geojson"]
            }]
        }
        save_geojson(fusion_fc, "integrated_fusion_boundary_v2.geojson")

        logger.info(f"  Success: area={result['stats']['area_km2']} km2, trimmed={result['stats']['trimmed']}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  Failed: {e}")

    return result


def generate_comparison_chart_v2(actual_boundary: Dict, proxy_results: list) -> str:
    """Generate improved PNG comparison chart with actual boundary

    Shows six boundaries on the same map:
    - Actual boundary: black thick line
    - Isochrone boundary: red fill
    - RESA convex hull: blue fill
    - Natural boundary: yellow fill
    - Integrated Fusion: green fill
    - Polygonize Fusion: purple fill (NEW)

    Output: comparison_chart_v3.png (higher resolution)
    """
    logger.info("=" * 50)
    logger.info("Generating comparison visualization v3")

    filepath = os.path.join(OUTPUT_DIR, "comparison_chart_v3.png")

    try:
        import matplotlib.pyplot as plt
        from shapely.geometry import shape

        fig, ax = plt.subplots(figsize=(14, 12))

        # Define colors for each boundary type
        colors = {
            "actual": "#000000",     # Black for actual boundary
            "isochrone": "#FF6B6B",  # Red for isochrone
            "convex": "#4A90D9",     # Blue for convex hull
            "natural": "#FFD700",    # Yellow for natural boundary
            "fusion": "#00C853",     # Green for integrated fusion
            "polygonize_fusion": "#9C27B0",  # Purple for polygonize fusion
        }

        # Plot actual boundary first (as thick black line, no fill)
        if actual_boundary.get("success") and actual_boundary.get("geojson"):
            actual_geom = shape(actual_boundary["geojson"])
            actual_gdf = gpd.GeoDataFrame([{"geometry": actual_geom}], crs="EPSG:4326")
            actual_area = actual_boundary["stats"].get("area_km2", 0)
            actual_gdf.plot(
                ax=ax,
                facecolor="none",
                edgecolor=colors["actual"],
                linewidth=3,
                linestyle="-",
                label=f"Actual Boundary ({actual_area} km2)"
            )

        # Plot proxy boundaries
        for r in proxy_results:
            if not r.get("success"):
                continue

            # Handle morphological envelope (has convex and concave)
            if r.get("name") == "形态学包络线" or "形态学" in r.get("name", ""):
                # Plot convex hull
                if r.get("convex", {}).get("success") and r.get("convex", {}).get("geojson"):
                    convex_geom = shape(r["convex"]["geojson"])
                    convex_gdf = gpd.GeoDataFrame([{"geometry": convex_geom}], crs="EPSG:4326")
                    convex_area = r["convex"]["stats"].get("area_km2", 0)
                    convex_gdf.plot(
                        ax=ax,
                        facecolor=colors["convex"],
                        edgecolor="darkblue",
                        alpha=0.4,
                        linewidth=1.5,
                        label=f"Convex Hull ({convex_area} km2)"
                    )
                continue  # Skip plotting concave to simplify

            # Handle integrated fusion boundary
            if r.get("name") == "Integrated Fusion Boundary":
                if r.get("geojson"):
                    fusion_geom = shape(r["geojson"])
                    fusion_gdf = gpd.GeoDataFrame([{"geometry": fusion_geom}], crs="EPSG:4326")
                    fusion_area = r.get("stats", {}).get("area_km2", 0)
                    fusion_gdf.plot(
                        ax=ax,
                        facecolor=colors["fusion"],
                        edgecolor="darkgreen",
                        alpha=0.5,
                        linewidth=2,
                        label=f"Integrated Fusion ({fusion_area} km2)"
                    )
                continue

            # Handle polygonize fusion boundary (NEW)
            if r.get("name") == "Polygonize Fusion Boundary":
                if r.get("geojson"):
                    pf_geom = shape(r["geojson"])
                    pf_gdf = gpd.GeoDataFrame([{"geometry": pf_geom}], crs="EPSG:4326")
                    pf_area = r.get("stats", {}).get("area_km2", 0)
                    pf_gdf.plot(
                        ax=ax,
                        facecolor=colors["polygonize_fusion"],
                        edgecolor="purple",
                        alpha=0.5,
                        linewidth=2,
                        label=f"Polygonize Fusion ({pf_area} km2)"
                    )
                continue

            # Handle isochrone and natural boundaries
            if r.get("geojson"):
                proxy_geom = shape(r["geojson"])
                proxy_gdf = gpd.GeoDataFrame([{"geometry": proxy_geom}], crs="EPSG:4326")
                proxy_area = r.get("stats", {}).get("area_km2", 0)

                if "等时圈" in r["name"]:
                    proxy_gdf.plot(
                        ax=ax,
                        facecolor=colors["isochrone"],
                        edgecolor="darkred",
                        alpha=0.4,
                        linewidth=1.5,
                        label=f"Isochrone ({proxy_area} km2)"
                    )
                elif "自然" in r["name"]:
                    proxy_gdf.plot(
                        ax=ax,
                        facecolor=colors["natural"],
                        edgecolor="orange",
                        alpha=0.4,
                        linewidth=1.5,
                        label=f"Natural Boundary ({proxy_area} km2)"
                    )

        # Plot center point
        ax.plot(JINTIAN_CENTER[0], JINTIAN_CENTER[1], "ko", markersize=12, label="Village Center", zorder=10)

        # Use English labels to avoid font issues
        ax.set_xlabel("Longitude (EPSG:4326)", fontsize=12)
        ax.set_ylabel("Latitude (EPSG:4326)", fontsize=12)
        ax.set_title("Village Boundary Proxy Comparison - Jintian Village", fontsize=14)
        ax.legend(loc="upper right", fontsize=10)
        ax.grid(True, alpha=0.3)

        # Set aspect ratio for geographic coordinates
        ax.set_aspect(1 / 0.8)  # Approximate aspect correction for mid-latitudes

        plt.tight_layout()
        plt.savefig(filepath, dpi=200, bbox_inches="tight")
        plt.close()

        logger.info(f"  Saved: {filepath}")
        return filepath

    except ImportError as e:
        logger.warning(f"  Visualization skipped: {e}")
        return ""
    except Exception as e:
        logger.error(f"  Visualization failed: {e}")
        return ""


def generate_report_v3(actual_boundary: Dict, proxy_results: list, comparison_metrics: Dict, deps: Dict[str, bool]) -> str:
    """Generate improved Markdown report with actual boundary comparison

    Includes:
    - Actual boundary as baseline
    - Comparison metrics table for each proxy method (including Polygonize Fusion)
    - Recommendation based on IoU and coverage rate

    Output: boundary_proxy_report_v2.md
    """
    logger.info("=" * 50)
    logger.info("Generating summary report v2")

    filepath = os.path.join(OUTPUT_DIR, "boundary_proxy_report_v3.md")

    lines = [
        "# Village Boundary Proxy Verification Report v3",
        "",
        f"**Verification Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Test Location**: Jintian Village ({JINTIAN_CENTER[0]}, {JINTIAN_CENTER[1]})",
        "",
        "## Dependency Check",
        "",
    ]

    for dep, available in deps.items():
        status = "OK" if available else "MISSING"
        lines.append(f"- {dep}: {status}")

    lines.extend([
        "",
        "## Actual Boundary (Baseline)",
        "",
    ])

    if actual_boundary.get("success"):
        actual_stats = actual_boundary.get("stats", {})
        lines.append(f"**Source**: `{actual_stats.get('source', ACTUAL_BOUNDARY_FILE)}`")
        lines.append(f"**Area**: {actual_stats.get('area_km2', 0)} km2")
        lines.append(f"**Perimeter**: {actual_stats.get('perimeter_km', 0)} km")
        lines.append(f"**Contains Center**: {actual_stats.get('contains_center', 'N/A')}")
        lines.append(f"**Line Count**: {actual_stats.get('line_count', 0)}")
    else:
        lines.append(f"**Status**: FAILED - {actual_boundary.get('error', 'Unknown error')}")

    lines.extend([
        "",
        "## Proxy Methods Comparison",
        "",
        "| Method | Status | Area (km2) | IoU | Coverage | Actual Cov |",
        "|--------|--------|------------|-----|----------|------------|",
    ])

    for method_name, metrics in comparison_metrics.items():
        status = "OK" if metrics.get("success") else "FAIL"
        area = metrics.get("area_km2", "-")
        iou = metrics.get("iou", "-")
        coverage = metrics.get("coverage_rate", "-")
        actual_cov = metrics.get("actual_coverage_rate", "-")
        lines.append(f"| {method_name} | {status} | {area} | {iou} | {coverage} | {actual_cov} |")

    lines.extend([
        "",
        "## Detailed Results",
        "",
    ])

    for r in proxy_results:
        lines.append(f"### {r['name']}")
        lines.append("")
        lines.append(f"**Method**: {r['method']}")
        lines.append(f"**Status**: {'Success' if r.get('success') else 'Failed'}")

        if r.get("error"):
            lines.append(f"**Error**: {r['error']}")

        if r.get("stats"):
            lines.append("")
            lines.append("**Statistics**:")
            for key, value in r["stats"].items():
                lines.append(f"- {key}: {value}")

        lines.append("")

    # Add recommendations based on IoU ranking
    lines.extend([
        "## Method Evaluation",
        "",
        "### Approach 1: Isochrone Boundary",
        "- **Pros**: Reflects real accessibility based on road network",
        "- **Cons**: Requires API support, circular approximation has limits",
        "- **Best for**: Transportation accessibility analysis, service range delineation",
        "",
        "### Approach 2: Morphological Envelope",
        "- **Pros**: Tightly fits built-up area distribution, no API needed",
        "- **Cons**: Needs dense RESA data points",
        "- **Best for**: Settlement cluster boundary delineation",
        "",
        "### Approach 3: Natural Boundary",
        "- **Pros**: Uses geographic barriers, natural boundary logic",
        "- **Cons**: Needs closed line network, unstable success rate",
        "- **Best for**: Areas with clear geographic divisions",
        "",
        "## Recommendation (IoU Ranking)",
        "",
    ])

    # Sort methods by IoU
    if comparison_metrics:
        sorted_methods = sorted(
            comparison_metrics.items(),
            key=lambda x: x[1].get("iou", 0),
            reverse=True
        )

        if sorted_methods:
            lines.append("**Ranked by IoU (Intersection over Union)**:")
            lines.append("")
            for i, (method, metrics) in enumerate(sorted_methods, 1):
                iou = metrics.get("iou", 0)
                coverage = metrics.get("coverage_rate", 0)
                lines.append(f"{i}. **{method}**: IoU={iou}, Coverage={coverage}")

            # Recommend based on top IoU
            best_method = sorted_methods[0][0]
            best_iou = sorted_methods[0][1].get("iou", 0)

            lines.append("")
            if best_iou >= 0.3:
                lines.append(f"**Primary Recommendation**: {best_method} (IoU >= 0.3)")
            else:
                lines.append("**Note**: All methods have IoU < 0.3, consider improving data quality or combining methods.")
        else:
            lines.append("No successful methods to compare.")
    else:
        lines.append("Comparison metrics not available.")

    # Add output files
    lines.extend([
        "",
        "## Output Files",
        "",
    ])

    output_files = [
        "actual_boundary.geojson",
        "isochrone_boundary.geojson",
        "morphological_hull.geojson",
        "morphological_concave.geojson",
        "natural_boundary.geojson",
        "integrated_fusion_boundary.geojson",
        "integrated_fusion_boundary_v2.geojson",
        "comparison_chart_v3.png",
        "boundary_proxy_report_v3.md"
    ]

    for f in output_files:
        lines.append(f"- `{OUTPUT_DIR}/{f}`")

    report_content = "\n".join(lines)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_content)

    logger.info(f"  Saved: {filepath}")
    return filepath


def main():
    """Main verification workflow with actual boundary comparison and fusion"""
    print("=" * 60)
    print("Village Boundary Proxy Verification Script v4")
    print("(With Polygonize Fusion - Geometric Stitching)")
    print("=" * 60)

    # Check dependencies
    deps = check_dependencies()

    if not deps["geopandas"] or not deps["shapely"]:
        logger.error("Core dependencies missing. Cannot proceed.")
        return

    # Create bbox
    bbox = create_bbox(JINTIAN_CENTER, BUFFER_RADIUS_KM)
    logger.info(f"BBox: {bbox}")

    # Step 1: Load actual boundary (ground truth)
    actual_boundary = load_actual_boundary(ACTUAL_BOUNDARY_FILE, JINTIAN_CENTER)

    # Step 2: Run proxy approaches
    results = []

    # Approach 1: Isochrone
    r1 = approach_1_isochrone(JINTIAN_CENTER)
    results.append(r1)

    # Approach 2: Morphological envelope
    r2 = approach_2_morphological(JINTIAN_CENTER, bbox)
    results.append(r2)

    # Approach 3: Natural boundary
    r3 = approach_3_natural_boundary(JINTIAN_CENTER, bbox)
    results.append(r3)

    # Approach 4: Integrated Fusion
    r4 = approach_4_integrated_fusion(JINTIAN_CENTER, bbox, r1, r2, r3)
    results.append(r4)

    # Approach 5: Polygonize Fusion (Geometric Stitching)
    r5 = approach_5_polygonize_fusion(JINTIAN_CENTER, bbox, r1, r2)
    results.append(r5)

    # Step 3: Calculate comparison metrics
    comparison_metrics = {}
    actual_geom = actual_boundary.get("geometry")

    if actual_boundary.get("success") and actual_geom:
        for r in results:
            method_name = r.get("name", "Unknown")

            # Handle morphological envelope (use convex hull for comparison)
            if method_name == "形态学包络线":
                if r.get("convex", {}).get("success"):
                    proxy_geom = shape(r["convex"]["geojson"])
                    metrics = compare_boundaries(proxy_geom, actual_geom)
                    metrics["success"] = True
                    metrics["area_km2"] = r["convex"]["stats"].get("area_km2", 0)
                    comparison_metrics["Morphological (Convex)"] = metrics
            elif method_name == "Integrated Fusion Boundary":
                if r.get("success") and r.get("geojson"):
                    proxy_geom = shape(r["geojson"])
                    metrics = compare_boundaries(proxy_geom, actual_geom)
                    metrics["success"] = True
                    metrics["area_km2"] = r.get("stats", {}).get("area_km2", 0)
                    comparison_metrics["Integrated Fusion"] = metrics
            elif method_name == "Polygonize Fusion Boundary":
                if r.get("success") and r.get("geojson"):
                    proxy_geom = shape(r["geojson"])
                    metrics = compare_boundaries(proxy_geom, actual_geom)
                    metrics["success"] = True
                    metrics["area_km2"] = r.get("stats", {}).get("area_km2", 0)
                    comparison_metrics["Polygonize Fusion"] = metrics
            else:
                if r.get("success") and r.get("geojson"):
                    proxy_geom = shape(r["geojson"])
                    metrics = compare_boundaries(proxy_geom, actual_geom)
                    metrics["success"] = True
                    metrics["area_km2"] = r.get("stats", {}).get("area_km2", 0)

                    if "等时圈" in method_name:
                        comparison_metrics["Isochrone"] = metrics
                    elif "自然" in method_name:
                        comparison_metrics["Natural Boundary"] = metrics
                    else:
                        comparison_metrics[method_name] = metrics

    # Step 4: Generate outputs
    generate_comparison_chart_v2(actual_boundary, results)
    generate_report_v3(actual_boundary, results, comparison_metrics, deps)

    # Print summary
    print("\n" + "=" * 60)
    print("Verification Summary:")
    print("=" * 60)

    # Actual boundary summary
    if actual_boundary.get("success"):
        actual_area = actual_boundary["stats"].get("area_km2", 0)
        print(f"Actual Boundary: {actual_area} km2 (SUCCESS)")
    else:
        print(f"Actual Boundary: FAILED - {actual_boundary.get('error', 'Unknown')}")

    # Proxy results summary
    for r in results:
        status = "SUCCESS" if r.get("success") else "FAILED"
        print(f"{r['name']}: {status}")
        if r.get("stats"):
            area = r.get("stats", {}).get("area_km2", "-")
            if r.get("name") == "形态学包络线":
                convex_area = r.get("convex", {}).get("stats", {}).get("area_km2", "-")
                print(f"  - Convex Hull: {convex_area} km2")
            elif r.get("name") == "Integrated Fusion Boundary":
                fusion_method = r.get("stats", {}).get("fusion_method", "unknown")
                print(f"  - Area: {area} km2, Method: {fusion_method}")
            elif r.get("name") == "Polygonize Fusion Boundary":
                trimmed = r.get("stats", {}).get("trimmed", False)
                print(f"  - Area: {area} km2, Trimmed: {trimmed}")
            else:
                print(f"  - Area: {area} km2")

    # Comparison metrics summary
    if comparison_metrics:
        print("\nComparison Metrics (IoU Ranking):")

        # Sort by IoU
        sorted_metrics = sorted(
            comparison_metrics.items(),
            key=lambda x: x[1].get("iou", 0),
            reverse=True
        )

        for method, metrics in sorted_metrics:
            if metrics.get("success"):
                iou = metrics.get("iou", 0)
                coverage = metrics.get("coverage_rate", 0)
                print(f"  {method}: IoU={iou}, Coverage={coverage}")

    print(f"\nOutput directory: {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()