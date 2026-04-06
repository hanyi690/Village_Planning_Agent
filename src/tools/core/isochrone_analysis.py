"""
Isochrone Analysis Core Logic

Generates isochrones (time-based accessibility zones) based on travel time
from a center point. Integrates with existing route planning APIs.

Reference: Planning workflow requires 5/10/15 minute walking/driving isochrones
for facility coverage analysis.
"""

import math
from typing import Dict, Any, List, Optional, Literal, Tuple
from concurrent.futures import ThreadPoolExecutor
from ...utils.logger import get_logger

logger = get_logger(__name__)

# Import accessibility core for route planning
from .accessibility_core import haversine_distance
from ..geocoding import TiandituProvider

# Travel speeds (km/h) for isochrone estimation
TRAVEL_SPEEDS = {
    "walk": 5.0,      # Walking speed
    "drive": 40.0,    # Driving speed (city average)
    "bike": 15.0,     # Bicycle speed
}

# Default isochrone intervals (minutes)
DEFAULT_ISOCHRONE_INTERVALS = [5, 10, 15]


def generate_isochrones(
    center: Tuple[float, float],
    time_minutes: List[int] = DEFAULT_ISOCHRONE_INTERVALS,
    travel_mode: Literal["walk", "drive", "bike"] = "walk",
    **kwargs
) -> Dict[str, Any]:
    """
    Generate isochrones (time-based accessibility zones)

    Uses radial sampling with route planning to create accurate isochrone boundaries.
    For walking mode, creates circular approximations; for driving, uses road network.

    Args:
        center: Center point coordinates (lon, lat)
        time_minutes: List of time intervals in minutes (default: [5, 10, 15])
        travel_mode: Travel mode (walk, drive, bike)
        **kwargs: Additional parameters
            - sample_points: Number of radial sample points (default: 16)
            - use_route_api: Whether to use route API for accuracy (default: True for drive)

    Returns:
        Dict with success status and isochrone GeoJSON
    """
    try:
        speed_km_h = TRAVEL_SPEEDS.get(travel_mode, 5.0)
        sample_points = kwargs.get("sample_points", 16)
        use_route_api = kwargs.get("use_route_api", travel_mode == "drive")

        isochrones = []

        for time_min in sorted(time_minutes):
            # Calculate theoretical radius
            theoretical_radius_km = (time_min / 60.0) * speed_km_h
            theoretical_radius_m = theoretical_radius_km * 1000

            if use_route_api and travel_mode == "drive":
                # Use route API for accurate driving isochrone
                boundary_points = _sample_isochrone_boundary_with_routes(
                    center, time_min, theoretical_radius_m, sample_points, travel_mode
                )
            else:
                # Use circular approximation for walking/bike
                boundary_points = _generate_circle_points(
                    center, theoretical_radius_m, sample_points
                )

            # Create polygon from boundary points
            polygon_geojson = _create_polygon_from_points(boundary_points)

            isochrones.append({
                "time_minutes": time_min,
                "travel_mode": travel_mode,
                "radius_km": round(theoretical_radius_km, 2),
                "geojson": polygon_geojson,
                "boundary_points": boundary_points,
            })

        # Create nested GeoJSON FeatureCollection
        features = []
        for iso in isochrones:
            feature = {
                "type": "Feature",
                "properties": {
                    "time_minutes": iso["time_minutes"],
                    "travel_mode": iso["travel_mode"],
                    "radius_km": iso["radius_km"],
                    "label": f"{iso['time_minutes']}min {iso['travel_mode']}",
                },
                "geometry": iso["geojson"],
            }
            features.append(feature)

        result_geojson = {"type": "FeatureCollection", "features": features}

        return {
            "success": True,
            "data": {
                "geojson": result_geojson,
                "isochrones": isochrones,
                "center": center,
                "travel_mode": travel_mode,
                "metadata": {
                    "speed_km_h": speed_km_h,
                    "sample_points": sample_points,
                    "use_route_api": use_route_api,
                }
            }
        }

    except Exception as e:
        logger.error(f"[isochrone_analysis] Generation failed: {e}")
        return {"success": False, "error": f"Isochrone generation failed: {str(e)}"}


def _sample_isochrone_boundary_with_routes(
    center: Tuple[float, float],
    time_minutes: int,
    theoretical_radius_m: float,
    sample_points: int,
    travel_mode: str
) -> List[Tuple[float, float]]:
    """
    Sample isochrone boundary using route planning API

    For each radial direction, find the point reachable within given time.
    """
    provider = TiandituProvider()
    route_type = 0 if travel_mode == "drive" else 3  # 0=drive, 3=walk

    boundary_points = []

    def sample_radial(angle_deg):
        # Start from theoretical radius point
        angle_rad = math.radians(angle_deg)
        # Overshoot slightly and backtrack
        test_radius_m = theoretical_radius_m * 1.2

        # Calculate test point coordinates
        lon_offset = (test_radius_m / 111320) * math.cos(angle_rad)
        lat_offset = (test_radius_m / 110540) * math.sin(angle_rad)

        test_lon = center[0] + lon_offset
        test_lat = center[1] + lat_offset

        if provider.api_key:
            # Use route API to check actual travel time
            route_result = provider.plan_route(
                center, (test_lon, test_lat), route_type=route_type
            )

            if route_result.success:
                route_data = route_result.data.get("route", {})
                duration_seconds = route_data.get("duration", 0)
                duration_minutes = duration_seconds / 60

                if duration_minutes <= time_minutes:
                    return (test_lon, test_lat)
                else:
                    # Scale back proportionally
                    scale = time_minutes / duration_minutes
                    actual_lon = center[0] + lon_offset * scale
                    actual_lat = center[1] + lat_offset * scale
                    return (actual_lon, actual_lat)
            else:
                # Fallback to theoretical point
                actual_lon = center[0] + (theoretical_radius_m / 111320) * math.cos(angle_rad)
                actual_lat = center[1] + (theoretical_radius_m / 110540) * math.sin(angle_rad)
                return (actual_lon, actual_lat)
        else:
            # No API available, use theoretical
            actual_lon = center[0] + (theoretical_radius_m / 111320) * math.cos(angle_rad)
            actual_lat = center[1] + (theoretical_radius_m / 110540) * math.sin(angle_rad)
            return (actual_lon, actual_lat)

    # Sample points in parallel
    angles = [i * (360 / sample_points) for i in range(sample_points)]

    with ThreadPoolExecutor(max_workers=min(sample_points, 8)) as executor:
        results = list(executor.map(sample_radial, angles))

    boundary_points = results
    return boundary_points


def _generate_circle_points(
    center: Tuple[float, float],
    radius_m: float,
    sample_points: int
) -> List[Tuple[float, float]]:
    """
    Generate points on a circle (simple circular approximation)

    Note: Uses approximate degree conversions (111320m per degree longitude,
    110540m per degree latitude at mid-latitudes).
    """
    points = []
    for i in range(sample_points):
        angle_rad = math.radians(i * (360 / sample_points))
        lon_offset = (radius_m / 111320) * math.cos(angle_rad)
        lat_offset = (radius_m / 110540) * math.sin(angle_rad)
        points.append((center[0] + lon_offset, center[1] + lat_offset))
    return points


def _create_polygon_from_points(
    points: List[Tuple[float, float]]
) -> Dict[str, Any]:
    """
    Create GeoJSON Polygon from boundary points

    Closes the polygon by adding first point at end.
    """
    coords = [[list(p) for p in points]]
    # Close polygon
    if coords[0] and coords[0][0] != coords[0][-1]:
        coords[0].append(coords[0][0])

    return {"type": "Polygon", "coordinates": coords}


def calculate_isochrone_coverage(
    isochrone_geojson: Dict[str, Any],
    poi_layer: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """
    Calculate POI coverage within isochrones

    For each isochrone zone, counts how many POIs are within the zone.

    Args:
        isochrone_geojson: Isochrone GeoJSON FeatureCollection
        poi_layer: POI layer (GeoJSON FeatureCollection)
        **kwargs: Additional parameters
            - poi_type_filter: Optional POI type to filter

    Returns:
        Dict with success status and coverage statistics
    """
    try:
        # Import spatial analysis for geometry operations
        from .spatial_analysis import geojson_to_geodataframe

        if not geojson_to_geodataframe:
            return {
                "success": False,
                "error": "Spatial analysis module not available"
            }

        iso_gdf = geojson_to_geodataframe(isochrone_geojson)
        poi_gdf = geojson_to_geodataframe(poi_layer)

        if iso_gdf is None or poi_gdf is None:
            return {"success": False, "error": "Invalid GeoJSON input"}

        poi_type_filter = kwargs.get("poi_type_filter")

        # Filter POIs by type if specified
        if poi_type_filter:
            poi_gdf = poi_gdf[poi_gdf.get("type", "") == poi_type_filter]

        coverage_by_isochrone = []
        total_pois = len(poi_gdf)

        for idx, iso_row in iso_gdf.iterrows():
            iso_geom = iso_row.geometry
            time_minutes = iso_row.get("time_minutes", 0)

            # Find POIs within this isochrone
            pois_within = poi_gdf[poi_gdf.geometry.within(iso_geom)]
            poi_count = len(pois_within)

            # List covered POIs
            covered_pois = []
            for poi_idx, poi_row in pois_within.iterrows():
                poi_name = poi_row.get("name", f"POI_{poi_idx}")
                poi_type = poi_row.get("type", "unknown")
                covered_pois.append({
                    "name": poi_name,
                    "type": poi_type,
                    "coordinates": [poi_row.geometry.x, poi_row.geometry.y],
                })

            coverage_by_isochrone.append({
                "time_minutes": time_minutes,
                "travel_mode": iso_row.get("travel_mode", "walk"),
                "total_pois_in_zone": poi_count,
                "coverage_rate": poi_count / total_pois if total_pois > 0 else 0,
                "covered_pois": covered_pois[:20],  # Limit to 20 for display
            })

        return {
            "success": True,
            "data": {
                "coverage_by_isochrone": coverage_by_isochrone,
                "total_pois": total_pois,
                "poi_type_filter": poi_type_filter,
                "metadata": {
                    "isochrone_count": len(iso_gdf),
                }
            }
        }

    except Exception as e:
        logger.error(f"[isochrone_analysis] Coverage calculation failed: {e}")
        return {"success": False, "error": f"Isochrone coverage calculation failed: {str(e)}"}


def analyze_service_area_gap(
    center: Tuple[float, float],
    facility_type: str,
    population_points: List[Dict[str, Any]],
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze service area gaps for facility planning

    Identifies population points not covered by standard service radius.

    Args:
        center: Facility center coordinates (lon, lat)
        facility_type: Type of facility (for radius lookup)
        population_points: List of population distribution points
            [{"coordinates": [lon, lat], "population": N}, ...]
        **kwargs: Additional parameters
            - custom_radius: Override standard radius (meters)

    Returns:
        Dict with success status and gap analysis
    """
    # Import service radius standards
    from .accessibility_core import SERVICE_RADIUS_STANDARDS

    radius = kwargs.get("custom_radius")
    if radius is None:
        radius = SERVICE_RADIUS_STANDARDS.get(facility_type, 500)

    covered_populations = []
    uncovered_populations = []
    total_population = 0
    covered_population = 0

    for point in population_points:
        coords = point.get("coordinates", [0, 0])
        pop = point.get("population", 1)
        total_population += pop

        # Calculate distance
        distance = haversine_distance(center, (coords[0], coords[1]))

        if distance <= radius:
            covered_populations.append({
                "coordinates": coords,
                "population": pop,
                "distance_m": round(distance, 1),
            })
            covered_population += pop
        else:
            uncovered_populations.append({
                "coordinates": coords,
                "population": pop,
                "distance_m": round(distance, 1),
                "gap_m": round(distance - radius, 1),
            })

    coverage_rate = covered_population / total_population if total_population > 0 else 0

    # Generate isochrone for visualization
    isochrone_result = generate_isochrones(
        center=center,
        time_minutes=[5, 10, 15],
        travel_mode="walk",
    )

    return {
        "success": True,
        "data": {
            "facility_type": facility_type,
            "service_radius_m": radius,
            "coverage_rate": round(coverage_rate, 4),
            "covered_population": covered_population,
            "uncovered_population": total_population - covered_population,
            "total_population": total_population,
            "covered_points": covered_populations[:20],
            "uncovered_points": uncovered_populations[:20],
            "isochrone_geojson": isochrone_result.get("data", {}).get("geojson"),
            "recommendations": _generate_gap_recommendations(
                facility_type, coverage_rate, uncovered_populations[:5]
            ),
        }
    }


def _generate_gap_recommendations(
    facility_type: str,
    coverage_rate: float,
    uncovered_points: List[Dict[str, Any]]
) -> List[str]:
    """Generate recommendations for service area gaps"""
    recommendations = []

    if coverage_rate < 0.5:
        recommendations.append(
            f"Coverage rate ({coverage_rate:.1%}) is below 50%. "
            f"Consider adding new {facility_type} facilities."
        )
    elif coverage_rate < 0.8:
        recommendations.append(
            f"Coverage rate ({coverage_rate:.1%}) needs improvement. "
            f"Review facility locations for better coverage."
        )

    if uncovered_points:
        farthest = max(uncovered_points, key=lambda p: p.get("gap_m", 0))
        recommendations.append(
            f"Farthest uncovered point is {farthest.get('gap_m', 0):.0f}m outside service radius. "
            f"Consider facility at coordinates {farthest.get('coordinates', [])}."
        )

    return recommendations


def format_isochrone_result(result: Dict[str, Any]) -> str:
    """Format isochrone analysis result to string"""
    if not result.get("success"):
        return f"Isochrone analysis failed: {result.get('error', 'Unknown error')}"

    data = result.get("data", {})
    lines = ["Isochrone Analysis Result:"]

    if "isochrones" in data:
        for iso in data["isochrones"]:
            lines.append(
                f"- {iso['time_minutes']}min zone: radius {iso['radius_km']}km"
            )

    if "coverage_by_isochrone" in data:
        lines.append("- POI Coverage:")
        for cov in data["coverage_by_isochrone"]:
            lines.append(
                f"  * {cov['time_minutes']}min: {cov['total_pois_in_zone']} POIs "
                f"({cov['coverage_rate']:.1%})"
            )

    if "coverage_rate" in data:
        lines.append(f"- Population coverage: {data['coverage_rate']:.1%}")

    return "\n".join(lines)


__all__ = [
    "generate_isochrones",
    "calculate_isochrone_coverage",
    "analyze_service_area_gap",
    "format_isochrone_result",
    "TRAVEL_SPEEDS",
    "DEFAULT_ISOCHRONE_INTERVALS",
]