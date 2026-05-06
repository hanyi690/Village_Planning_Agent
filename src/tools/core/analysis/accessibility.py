"""
Accessibility Analysis - 可达性分析（合并模块）

整合 accessibility_core 和 isochrone_analysis，提供完整的可达性分析功能。

功能：
- 路由可达性分析（驾车/步行）
- 服务半径覆盖分析
- POI 设施覆盖分析
- 等时圈生成与分析
- 服务缺口分析
"""

import math
from typing import Dict, Any, List, Optional, Literal, Tuple
from concurrent.futures import ThreadPoolExecutor

from src.utils.logger import get_logger
from src.tools.geocoding import TiandituProvider
from ..utils.geo_utils import haversine_distance

logger = get_logger(__name__)

# ============================================
# Constants
# ============================================

# 服务半径标准（米）
SERVICE_RADIUS_STANDARDS = {
    "幼儿园": 300,
    "小学": 500,
    "中学": 1000,
    "医院": 1000,
    "诊所": 500,
    "公园": 500,
    "公交站": 300,
    "停车场": 200,
    "超市": 500,
    "菜市场": 500,
    "健身设施": 500,
    "垃圾收集点": 100,
}

# Travel speeds (km/h) for isochrone estimation
TRAVEL_SPEEDS = {
    "walk": 5.0,
    "drive": 40.0,
    "bike": 15.0,
}

# Default isochrone intervals (minutes)
DEFAULT_ISOCHRONE_INTERVALS = [5, 10, 15]


# ============================================
# Route Accessibility Analysis
# ============================================

def run_accessibility_analysis(
    analysis_type: str,
    origin: Optional[Tuple[float, float]] = None,
    destinations: Optional[List[Tuple[float, float]]] = None,
    center: Optional[Tuple[float, float]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    执行可达性分析

    Args:
        analysis_type: 分析类型
            - driving_accessibility: 驾车可达性
            - walking_accessibility: 步行可达性
            - service_coverage: 服务半径覆盖
            - poi_coverage: POI设施覆盖
        origin: 起点坐标 (lon, lat)
        destinations: 目标点列表 [(lon, lat), ...]
        center: 中心坐标 (lon, lat)

    Returns:
        Dict[str, Any]: 分析结果
    """
    provider = TiandituProvider()

    if not provider.api_key:
        return {"success": False, "error": "天地图服务不可用，请配置 TIANDITU_API_KEY"}

    if analysis_type == "driving_accessibility":
        return _analyze_route_accessibility(
            provider, origin, destinations,
            route_type=0, default_max_time=30, default_max_distance=20,
            fallback_speed=40, analysis_type_name="driving_accessibility",
            **kwargs
        )
    elif analysis_type == "walking_accessibility":
        return _analyze_route_accessibility(
            provider, origin, destinations,
            route_type=3, default_max_time=15, default_max_distance=1,
            fallback_speed=5, analysis_type_name="walking_accessibility",
            **kwargs
        )
    elif analysis_type == "service_coverage":
        return _analyze_service_coverage(provider, center, **kwargs)
    elif analysis_type == "poi_coverage":
        return _analyze_poi_coverage(provider, center, **kwargs)
    else:
        return {"success": False, "error": f"不支持的分析类型: {analysis_type}"}


def _analyze_route_accessibility(
    provider: TiandituProvider,
    origin: Optional[Tuple[float, float]],
    destinations: Optional[List[Tuple[float, float]]],
    route_type: int,
    default_max_time: int,
    default_max_distance: float,
    fallback_speed: float,
    analysis_type_name: str,
    **kwargs
) -> Dict[str, Any]:
    """统一的路由可达性分析"""
    max_time = kwargs.get("max_time", default_max_time)
    max_distance = kwargs.get("max_distance", default_max_distance)

    if not origin:
        return {"success": False, "error": "缺少 origin 参数"}
    if not destinations:
        return {"success": False, "error": "缺少 destinations 参数"}

    accessibility_matrix = []
    reachable_count = 0

    def calc_route(dest):
        return dest, provider.plan_route(origin, dest, route_type=route_type)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(calc_route, d) for d in destinations]
        route_results = [f.result() for f in futures]

    for dest, route_result in route_results:
        if route_result.success:
            route_data = route_result.data.get("route", {})
            duration = route_data.get("duration", 0)
            distance = route_data.get("distance", 0)
            time_minutes = duration / 60
            distance_km = distance / 1000

            is_reachable = time_minutes <= max_time and distance_km <= max_distance

            accessibility_matrix.append({
                "destination": dest,
                "distance": distance,
                "duration": duration,
                "distance_km": round(distance_km, 2),
                "time_minutes": round(time_minutes, 1),
                "is_reachable": is_reachable,
                "geometry": route_result.data.get("geojson"),
            })

            if is_reachable:
                reachable_count += 1
        else:
            simple_distance = haversine_distance(origin, dest)
            time_minutes = simple_distance / 1000 / fallback_speed * 60

            accessibility_matrix.append({
                "destination": dest,
                "distance": simple_distance,
                "duration": time_minutes * 60,
                "distance_km": round(simple_distance / 1000, 2),
                "time_minutes": round(time_minutes, 1),
                "is_reachable": time_minutes <= max_time and simple_distance / 1000 <= max_distance,
                "geometry": [],
                "error": route_result.error,
            })

            if time_minutes <= max_time:
                reachable_count += 1

    metadata = {
        "source": "TiandituRoute",
        "analysis_type": analysis_type_name,
        "origin": origin,
        "max_time": max_time,
        "max_distance": max_distance,
    }

    return {
        "success": True,
        "data": {
            "accessibility_matrix": accessibility_matrix,
            "summary": {
                "total": len(destinations),
                "reachable": reachable_count,
                "coverage_rate": reachable_count / len(destinations) if destinations else 0,
            },
            "metadata": metadata
        }
    }


def _analyze_service_coverage(
    provider: TiandituProvider,
    center: Optional[Tuple[float, float]],
    **kwargs
) -> Dict[str, Any]:
    """服务半径覆盖分析"""
    radius = kwargs.get("radius", 500)
    poi_type = kwargs.get("poi_type", "学校")
    population_points = kwargs.get("population_points", [])
    use_standard_radius = kwargs.get("use_standard_radius", True)

    if not center:
        return {"success": False, "error": "缺少 center 参数"}

    if use_standard_radius and poi_type in SERVICE_RADIUS_STANDARDS:
        radius = SERVICE_RADIUS_STANDARDS[poi_type]

    poi_result = provider.search_poi(keyword=poi_type, center=center, radius=radius * 3)

    facilities = []
    if poi_result.success:
        facilities = poi_result.data.get("pois", [])

    covered_points = []
    uncovered_points = []

    if population_points:
        for point in population_points:
            if len(point) >= 2:
                point_coords = (point[0], point[1])
                point_pop = point[2] if len(point) >= 3 else 1

                is_covered = False
                for facility in facilities:
                    facility_coords = (facility.get("lon", 0), facility.get("lat", 0))
                    distance = haversine_distance(point_coords, facility_coords)

                    if distance <= radius:
                        is_covered = True
                        covered_points.append({
                            "coordinates": point_coords,
                            "population": point_pop,
                            "nearest_facility": facility.get("name", ""),
                            "distance": distance,
                        })
                        break

                if not is_covered:
                    uncovered_points.append({
                        "coordinates": point_coords,
                        "population": point_pop,
                    })
    else:
        for facility in facilities:
            facility_coords = (facility.get("lon", 0), facility.get("lat", 0))
            distance = haversine_distance(center, facility_coords)

            if distance <= radius:
                covered_points.append({
                    "coordinates": facility_coords,
                    "facility_name": facility.get("name", ""),
                    "distance": distance,
                })

    features = []
    for facility in facilities:
        features.append({
            "type": "Feature",
            "properties": {
                "name": facility.get("name", ""),
                "type": poi_type,
                "address": facility.get("address", ""),
                "distance": facility.get("distance", 0),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [facility.get("lon", 0), facility.get("lat", 0)]
            }
        })

    geojson = {"type": "FeatureCollection", "features": features}

    total_pop = sum(p.get("population", 1) for p in covered_points) + \
                sum(p.get("population", 1) for p in uncovered_points)
    covered_pop = sum(p.get("population", 1) for p in covered_points)

    return {
        "success": True,
        "data": {
            "geojson": geojson,
            "facilities": facilities,
            "covered_points": covered_points,
            "uncovered_points": uncovered_points,
            "summary": {
                "total_facilities": len(facilities),
                "covered_count": len(covered_points),
                "uncovered_count": len(uncovered_points),
                "coverage_rate": covered_pop / total_pop if total_pop > 0 else 0,
            },
            "metadata": {
                "source": "TiandituPOI",
                "analysis_type": "service_coverage",
                "center": center,
                "radius": radius,
                "poi_type": poi_type,
            }
        }
    }


def _analyze_poi_coverage(
    provider: TiandituProvider,
    center: Optional[Tuple[float, float]],
    **kwargs
) -> Dict[str, Any]:
    """POI设施覆盖分析"""
    poi_types = kwargs.get("poi_types", ["学校", "医院", "公园"])
    radii = kwargs.get("radii")

    if not center:
        return {"success": False, "error": "缺少 center 参数"}

    coverage_by_type = {}

    for i, poi_type in enumerate(poi_types):
        if radii and i < len(radii):
            radius = radii[i]
        elif poi_type in SERVICE_RADIUS_STANDARDS:
            radius = SERVICE_RADIUS_STANDARDS[poi_type]
        else:
            radius = 500

        poi_result = provider.search_poi(keyword=poi_type, center=center, radius=radius * 2)

        facilities = []
        if poi_result.success:
            facilities = poi_result.data.get("pois", [])

        in_range_facilities = []
        for facility in facilities:
            facility_coords = (facility.get("lon", 0), facility.get("lat", 0))
            distance = haversine_distance(center, facility_coords)

            if distance <= radius:
                in_range_facilities.append({**facility, "within_radius": True})

        coverage_by_type[poi_type] = {
            "radius": radius,
            "total_found": len(facilities),
            "in_range": len(in_range_facilities),
            "facilities": in_range_facilities,
            "coverage_rate": len(in_range_facilities) / max(len(facilities), 1),
        }

    total_types = len(poi_types)
    covered_types = sum(1 for t in coverage_by_type.values() if t["in_range"] > 0)

    return {
        "success": True,
        "data": {
            "coverage_by_type": coverage_by_type,
            "summary": {
                "total_types": total_types,
                "covered_types": covered_types,
                "type_coverage_rate": covered_types / total_types if total_types > 0 else 0,
            },
            "metadata": {
                "source": "TiandituPOI",
                "analysis_type": "poi_coverage",
                "center": center,
            }
        }
    }


# ============================================
# Isochrone Analysis (合并自 isochrone_analysis)
# ============================================

def generate_isochrones(
    center: Tuple[float, float],
    time_minutes: List[int] = DEFAULT_ISOCHRONE_INTERVALS,
    travel_mode: Literal["walk", "drive", "bike"] = "walk",
    **kwargs
) -> Dict[str, Any]:
    """
    Generate isochrones (time-based accessibility zones)

    Args:
        center: Center point coordinates (lon, lat)
        time_minutes: List of time intervals in minutes (default: [5, 10, 15])
        travel_mode: Travel mode (walk, drive, bike)
        **kwargs: Additional parameters

    Returns:
        Dict with success status and isochrone GeoJSON
    """
    try:
        speed_km_h = TRAVEL_SPEEDS.get(travel_mode, 5.0)
        sample_points = kwargs.get("sample_points", 16)
        use_route_api = kwargs.get("use_route_api", travel_mode == "drive")

        isochrones = []

        for time_min in sorted(time_minutes):
            theoretical_radius_km = (time_min / 60.0) * speed_km_h
            theoretical_radius_m = theoretical_radius_km * 1000

            if use_route_api and travel_mode == "drive":
                boundary_points = _sample_isochrone_boundary_with_routes(
                    center, time_min, theoretical_radius_m, sample_points, travel_mode
                )
            else:
                boundary_points = _generate_circle_points(
                    center, theoretical_radius_m, sample_points
                )

            polygon_geojson = _create_polygon_from_points(boundary_points)

            isochrones.append({
                "time_minutes": time_min,
                "travel_mode": travel_mode,
                "radius_km": round(theoretical_radius_km, 2),
                "geojson": polygon_geojson,
                "boundary_points": boundary_points,
            })

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
        logger.error(f"[accessibility] Isochrone generation failed: {e}")
        return {"success": False, "error": f"Isochrone generation failed: {str(e)}"}


def _sample_isochrone_boundary_with_routes(
    center: Tuple[float, float],
    time_minutes: int,
    theoretical_radius_m: float,
    sample_points: int,
    travel_mode: str
) -> List[Tuple[float, float]]:
    """Sample isochrone boundary using route planning API"""
    provider = TiandituProvider()
    route_type = 0 if travel_mode == "drive" else 3

    def sample_radial(angle_deg):
        angle_rad = math.radians(angle_deg)
        test_radius_m = theoretical_radius_m * 1.2

        lon_offset = (test_radius_m / 111320) * math.cos(angle_rad)
        lat_offset = (test_radius_m / 110540) * math.sin(angle_rad)

        test_lon = center[0] + lon_offset
        test_lat = center[1] + lat_offset

        if provider.api_key:
            route_result = provider.plan_route(center, (test_lon, test_lat), route_type=route_type)

            if route_result.success:
                route_data = route_result.data.get("route", {})
                duration_minutes = route_data.get("duration", 0) / 60

                if duration_minutes <= time_minutes:
                    return (test_lon, test_lat)
                else:
                    scale = time_minutes / duration_minutes
                    return (center[0] + lon_offset * scale, center[1] + lat_offset * scale)
            else:
                return (center[0] + (theoretical_radius_m / 111320) * math.cos(angle_rad),
                        center[1] + (theoretical_radius_m / 110540) * math.sin(angle_rad))
        else:
            return (center[0] + (theoretical_radius_m / 111320) * math.cos(angle_rad),
                    center[1] + (theoretical_radius_m / 110540) * math.sin(angle_rad))

    angles = [i * (360 / sample_points) for i in range(sample_points)]

    with ThreadPoolExecutor(max_workers=min(sample_points, 8)) as executor:
        results = list(executor.map(sample_radial, angles))

    return results


def _generate_circle_points(
    center: Tuple[float, float],
    radius_m: float,
    sample_points: int
) -> List[Tuple[float, float]]:
    """Generate points on a circle (simple circular approximation)"""
    points = []
    for i in range(sample_points):
        angle_rad = math.radians(i * (360 / sample_points))
        lon_offset = (radius_m / 111320) * math.cos(angle_rad)
        lat_offset = (radius_m / 110540) * math.sin(angle_rad)
        points.append((center[0] + lon_offset, center[1] + lat_offset))
    return points


def _create_polygon_from_points(points: List[Tuple[float, float]]) -> Dict[str, Any]:
    """Create GeoJSON Polygon from boundary points"""
    coords = [[list(p) for p in points]]
    if coords[0] and coords[0][0] != coords[0][-1]:
        coords[0].append(coords[0][0])
    return {"type": "Polygon", "coordinates": coords}


def calculate_isochrone_coverage(
    isochrone_geojson: Dict[str, Any],
    poi_layer: Dict[str, Any],
    **kwargs
) -> Dict[str, Any]:
    """Calculate POI coverage within isochrones"""
    try:
        from .spatial_ops import geojson_to_geodataframe

        iso_gdf = geojson_to_geodataframe(isochrone_geojson)
        poi_gdf = geojson_to_geodataframe(poi_layer)

        if iso_gdf is None or poi_gdf is None:
            return {"success": False, "error": "Invalid GeoJSON input"}

        poi_type_filter = kwargs.get("poi_type_filter")
        if poi_type_filter:
            poi_gdf = poi_gdf[poi_gdf.get("type", "") == poi_type_filter]

        coverage_by_isochrone = []
        total_pois = len(poi_gdf)

        for idx, iso_row in iso_gdf.iterrows():
            iso_geom = iso_row.geometry
            time_minutes = iso_row.get("time_minutes", 0)

            pois_within = poi_gdf[poi_gdf.geometry.within(iso_geom)]
            poi_count = len(pois_within)

            covered_pois = []
            for poi_idx, poi_row in pois_within.iterrows():
                covered_pois.append({
                    "name": poi_row.get("name", f"POI_{poi_idx}"),
                    "type": poi_row.get("type", "unknown"),
                    "coordinates": [poi_row.geometry.x, poi_row.geometry.y],
                })

            coverage_by_isochrone.append({
                "time_minutes": time_minutes,
                "travel_mode": iso_row.get("travel_mode", "walk"),
                "total_pois_in_zone": poi_count,
                "coverage_rate": poi_count / total_pois if total_pois > 0 else 0,
                "covered_pois": covered_pois[:20],
            })

        return {
            "success": True,
            "data": {
                "coverage_by_isochrone": coverage_by_isochrone,
                "total_pois": total_pois,
                "poi_type_filter": poi_type_filter,
                "metadata": {"isochrone_count": len(iso_gdf)}
            }
        }

    except Exception as e:
        logger.error(f"[accessibility] Coverage calculation failed: {e}")
        return {"success": False, "error": f"Isochrone coverage calculation failed: {str(e)}"}


def analyze_service_area_gap(
    center: Tuple[float, float],
    facility_type: str,
    population_points: List[Dict[str, Any]],
    **kwargs
) -> Dict[str, Any]:
    """Analyze service area gaps for facility planning"""
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

    isochrone_result = generate_isochrones(center=center, time_minutes=[5, 10, 15], travel_mode="walk")

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
            f"Coverage rate ({coverage_rate:.1%}) is below 50%. Consider adding new {facility_type} facilities."
        )
    elif coverage_rate < 0.8:
        recommendations.append(
            f"Coverage rate ({coverage_rate:.1%}) needs improvement. Review facility locations."
        )

    if uncovered_points:
        farthest = max(uncovered_points, key=lambda p: p.get("gap_m", 0))
        recommendations.append(
            f"Farthest uncovered point is {farthest.get('gap_m', 0):.0f}m outside service radius."
        )

    return recommendations


# ============================================
# Formatting Functions
# ============================================

def format_accessibility_result(result: Dict[str, Any]) -> str:
    """格式化可达性分析结果为字符串"""
    if not result.get("success"):
        return f"可达性分析失败: {result.get('error', '未知错误')}"

    data = result.get("data", {})
    lines = ["可达性分析结果："]

    if "accessibility_matrix" in data:
        summary = data.get("summary", {})
        lines.append(f"- 总目标点数: {summary.get('total', 0)}")
        lines.append(f"- 可达点数: {summary.get('reachable', 0)}")
        lines.append(f"- 覆盖率: {summary.get('coverage_rate', 0):.2%}")
        lines.append("- 可达性矩阵:")
        for item in data["accessibility_matrix"][:5]:
            status = "✓" if item.get("is_reachable") else "✗"
            lines.append(f"  * {status} 距离: {item.get('distance_km', 0)} km, 时间: {item.get('time_minutes', 0)} min")

    if "coverage_by_type" in data:
        lines.append("- POI覆盖情况:")
        for poi_type, coverage in data["coverage_by_type"].items():
            lines.append(f"  * {poi_type}: 范围内 {coverage['in_range']} 个设施 (半径 {coverage['radius']}m)")

    return "\n".join(lines)


def format_isochrone_result(result: Dict[str, Any]) -> str:
    """Format isochrone analysis result to string"""
    if not result.get("success"):
        return f"Isochrone analysis failed: {result.get('error', 'Unknown error')}"

    data = result.get("data", {})
    lines = ["Isochrone Analysis Result:"]

    if "isochrones" in data:
        for iso in data["isochrones"]:
            lines.append(f"- {iso['time_minutes']}min zone: radius {iso['radius_km']}km")

    if "coverage_by_isochrone" in data:
        lines.append("- POI Coverage:")
        for cov in data["coverage_by_isochrone"]:
            lines.append(f"  * {cov['time_minutes']}min: {cov['total_pois_in_zone']} POIs ({cov['coverage_rate']:.1%})")

    return "\n".join(lines)


__all__ = [
    'haversine_distance',
    'run_accessibility_analysis',
    'generate_isochrones',
    'calculate_isochrone_coverage',
    'analyze_service_area_gap',
    'format_accessibility_result',
    'format_isochrone_result',
    'SERVICE_RADIUS_STANDARDS',
    'TRAVEL_SPEEDS',
    'DEFAULT_ISOCHRONE_INTERVALS',
]