"""
可达性分析核心逻辑

从 AccessibilityAdapter 提取的核心功能，基于天地图 API 提供可达性分析。
"""

import math
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

from ..geocoding.tianditu_provider import TiandituProvider
from ...utils.logger import get_logger

logger = get_logger(__name__)


def haversine_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """
    计算两点之间的 Haversine 距离（米）

    Args:
        coord1: 第一个点的坐标 (lon, lat)
        coord2: 第二个点的坐标 (lon, lat)

    Returns:
        两点之间的距离（米）
    """
    lon1, lat1 = coord1
    lon2, lat2 = coord2

    R = 6371000  # 地球半径（米）

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

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
            route_type=0,
            default_max_time=30,
            default_max_distance=20,
            fallback_speed=40,  # km/h for driving
            analysis_type_name="driving_accessibility",
            **kwargs
        )
    elif analysis_type == "walking_accessibility":
        return _analyze_route_accessibility(
            provider, origin, destinations,
            route_type=3,
            default_max_time=15,
            default_max_distance=1,
            fallback_speed=5,  # km/h for walking
            analysis_type_name="walking_accessibility",
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
    """
    统一的路由可达性分析

    Args:
        provider: 天地图服务提供者
        origin: 起点坐标
        destinations: 目标点列表
        route_type: 路由类型 (0=驾车, 3=步行)
        default_max_time: 默认最大时间
        default_max_distance: 默认最大距离
        fallback_speed: API 失败时的备用速度 (km/h)
        analysis_type_name: 分析类型名称
        **kwargs: 其他参数
    """
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
            # 使用简化计算作为备份
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

    if analysis_type_name == "walking_accessibility":
        metadata["walking_speed"] = fallback_speed

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

    poi_result = provider.search_poi(
        keyword=poi_type,
        center=center,
        radius=radius * 3
    )

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

    total_pop = sum(p.get("population", 1) for p in covered_points) + \
                sum(p.get("population", 1) for p in uncovered_points)
    covered_pop = sum(p.get("population", 1) for p in covered_points)

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

        poi_result = provider.search_poi(
            keyword=poi_type,
            center=center,
            radius=radius * 2
        )

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