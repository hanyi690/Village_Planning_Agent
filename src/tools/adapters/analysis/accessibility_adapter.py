"""
可达性分析适配器

基于天地图真实道路网络的可达性分析：
1. 驾车可达性分析
2. 步行可达性分析
3. 服务半径覆盖分析
4. POI 覆盖分析

使用天地图路径规划 API，支持真实道路网络计算。
"""

from typing import Dict, Any, Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor

from ..base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...geocoding.tianditu_provider import TiandituProvider
from ....utils.logger import get_logger
from ....utils.geo_utils import haversine_distance

logger = get_logger(__name__)


class AccessibilityAdapter(BaseAdapter):
    """
    可达性分析适配器

    支持的分析类型：
    1. driving_accessibility - 驾车可达性分析
    2. walking_accessibility - 步行可达性分析
    3. service_coverage - 服务半径覆盖分析
    4. poi_coverage - POI 设施覆盖分析

    数据源：
    - 天地图路径规划 API：真实道路网络
    - 天地图 POI 搜索：设施位置数据

    使用示例：
    ```python
    adapter = AccessibilityAdapter()

    # 驾车可达性分析
    result = adapter.execute(
        "driving_accessibility",
        origin=(115.891, 24.567),
        destinations=[(116.0, 24.6), (116.1, 24.7)],
        max_time=30  # 最大时间（分钟）
    )

    # 服务半径覆盖分析
    result = adapter.execute(
        "service_coverage",
        center=(115.891, 24.567),
        radius=1000,  # 服务半径（米）
        poi_type="学校"
    )
    ```
    """

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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化适配器"""
        self._provider: Optional[TiandituProvider] = None
        super().__init__(config)

    def validate_dependencies(self) -> bool:
        """验证外部依赖是否可用"""
        try:
            self._provider = TiandituProvider()

            if self._provider.api_key:
                logger.info("[AccessibilityAdapter] 天地图服务可用")
                return True
            else:
                logger.warning("[AccessibilityAdapter] 天地图 API Key 未配置")
                return True  # 仍然返回 True，让用户知道需要配置

        except Exception as e:
            logger.warning(f"[AccessibilityAdapter] 初始化失败: {e}")
            return False

    def initialize(self) -> bool:
        """初始化适配器"""
        try:
            if not self._provider:
                self._provider = TiandituProvider()

            if not self._provider.api_key:
                logger.warning(
                    "[AccessibilityAdapter] 天地图 API Key 未配置，"
                    "请设置 TIANDITU_API_KEY 环境变量"
                )

            self._status = AdapterStatus.READY
            return True

        except Exception as e:
            self._error_message = f"初始化失败: {str(e)}"
            logger.error(f"[AccessibilityAdapter] {self._error_message}")
            return False

    def execute(
        self,
        analysis_type: str = "driving_accessibility",
        **kwargs
    ) -> AdapterResult:
        """
        执行可达性分析

        Args:
            analysis_type: 分析类型
                - driving_accessibility: 驾车可达性
                - walking_accessibility: 步行可达性
                - service_coverage: 服务半径覆盖
                - poi_coverage: POI 设施覆盖

            **kwargs: 参数

        Returns:
            AdapterResult: 包含分析结果
        """
        logger.info(f"[AccessibilityAdapter] 执行: {analysis_type}")

        if analysis_type == "driving_accessibility":
            return self._analyze_driving_accessibility(**kwargs)
        elif analysis_type == "walking_accessibility":
            return self._analyze_walking_accessibility(**kwargs)
        elif analysis_type == "service_coverage":
            return self._analyze_service_coverage(**kwargs)
        elif analysis_type == "poi_coverage":
            return self._analyze_poi_coverage(**kwargs)
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"不支持的分析类型: {analysis_type}"
            )

    def get_schema(self) -> Dict[str, Any]:
        """获取输出 Schema"""
        return {
            "adapter_name": "AccessibilityAdapter",
            "supported_analyses": [
                "driving_accessibility",
                "walking_accessibility",
                "service_coverage",
                "poi_coverage"
            ],
            "output_schema": {
                "accessibility_matrix": "array (origin to destinations)",
                "coverage_rate": "float (0-1)",
                "covered_points": "array [coordinates]",
                "uncovered_points": "array [coordinates]",
                "metadata": {
                    "source": "string (TiandituRoute)",
                    "analysis_type": "string",
                    "total_count": "int",
                    "covered_count": "int",
                }
            }
        }

    # ==========================================
    # 驾车可达性分析
    # ==========================================

    def _analyze_driving_accessibility(self, **kwargs) -> AdapterResult:
        """
        驾车可达性分析

        Args:
            origin: 起点坐标 (lon, lat)
            destinations: 目标点列表 [(lon, lat), ...]
            max_time: 最大时间限制（分钟）
            max_distance: 最大距离限制（公里）

        Returns:
            AdapterResult: 包含可达性矩阵
        """
        origin = kwargs.get("origin")
        destinations = kwargs.get("destinations", [])
        max_time = kwargs.get("max_time", 30)  # 分钟
        max_distance = kwargs.get("max_distance", 20)  # 公里

        if not origin:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 origin 参数"
            )

        if not destinations:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 destinations 参数"
            )

        if not self._provider or not self._provider.api_key:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="天地图服务不可用。请配置 TIANDITU_API_KEY 环境变量"
            )

        # 计算每个目标点的可达性
        accessibility_matrix = []
        reachable_count = 0

        # 并行计算所有路线
        def calc_route(dest):
            return dest, self._provider.plan_route(origin, dest, route_type=0)

        route_results = []
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

                is_reachable = (
                    time_minutes <= max_time and
                    distance_km <= max_distance
                )

                accessibility_matrix.append({
                    "destination": dest,
                    "distance": distance,
                    "duration": duration,
                    "distance_km": distance_km,
                    "time_minutes": time_minutes,
                    "is_reachable": is_reachable,
                    "geometry": route_result.data.get("geojson"),
                })

                if is_reachable:
                    reachable_count += 1
            else:
                # 使用简化计算作为备份
                simple_distance = haversine_distance(origin, dest)
                accessibility_matrix.append({
                    "destination": dest,
                    "distance": simple_distance,
                    "duration": simple_distance / 1000 * 60 / 40,  # 假设 40km/h
                    "distance_km": simple_distance / 1000,
                    "time_minutes": simple_distance / 1000 * 60 / 40,
                    "is_reachable": simple_distance / 1000 <= max_distance,
                    "geometry": [],
                    "error": route_result.error,
                })

        metadata = {
            "source": "TiandituRoute",
            "analysis_type": "driving_accessibility",
            "origin": origin,
            "total_count": len(destinations),
            "reachable_count": reachable_count,
            "max_time": max_time,
            "max_distance": max_distance,
            "coverage_rate": reachable_count / len(destinations) if destinations else 0,
        }

        return AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
                "accessibility_matrix": accessibility_matrix,
                "summary": {
                    "total": len(destinations),
                    "reachable": reachable_count,
                    "coverage_rate": reachable_count / len(destinations) if destinations else 0,
                },
                "metadata": metadata,
            },
            metadata=metadata
        )

    # ==========================================
    # 步行可达性分析
    # ==========================================

    def _analyze_walking_accessibility(self, **kwargs) -> AdapterResult:
        """
        步行可达性分析

        Args:
            origin: 起点坐标 (lon, lat)
            destinations: 目标点列表 [(lon, lat), ...]
            max_time: 最大时间限制（分钟）
            max_distance: 最大距离限制（公里）

        Returns:
            AdapterResult: 包含步行可达性矩阵
        """
        origin = kwargs.get("origin")
        destinations = kwargs.get("destinations", [])
        max_time = kwargs.get("max_time", 15)  # 分钟（步行较短）
        max_distance = kwargs.get("max_distance", 1)  # 公里（步行较短）

        if not origin:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 origin 参数"
            )

        if not destinations:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 destinations 参数"
            )

        if not self._provider or not self._provider.api_key:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="天地图服务不可用"
            )

        # 计算步行可达性（假设步行速度 5km/h）
        walking_speed = 5  # km/h
        accessibility_matrix = []
        reachable_count = 0

        # 并行计算所有步行路线
        def calc_route(dest):
            return dest, self._provider.plan_route(origin, dest, route_type=3)

        route_results = []
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

                is_reachable = (
                    time_minutes <= max_time and
                    distance_km <= max_distance
                )

                accessibility_matrix.append({
                    "destination": dest,
                    "distance": distance,
                    "duration": duration,
                    "distance_km": distance_km,
                    "time_minutes": time_minutes,
                    "is_reachable": is_reachable,
                    "geometry": route_result.data.get("geojson"),
                })

                if is_reachable:
                    reachable_count += 1
            else:
                # 使用简化计算
                simple_distance = haversine_distance(origin, dest)
                time_minutes = simple_distance / 1000 / walking_speed * 60

                accessibility_matrix.append({
                    "destination": dest,
                    "distance": simple_distance,
                    "duration": time_minutes * 60,
                    "distance_km": simple_distance / 1000,
                    "time_minutes": time_minutes,
                    "is_reachable": time_minutes <= max_time,
                    "geometry": [],
                    "error": route_result.error,
                })

                if time_minutes <= max_time:
                    reachable_count += 1

        metadata = {
            "source": "TiandituRoute",
            "analysis_type": "walking_accessibility",
            "origin": origin,
            "total_count": len(destinations),
            "reachable_count": reachable_count,
            "max_time": max_time,
            "max_distance": max_distance,
            "walking_speed": walking_speed,
            "coverage_rate": reachable_count / len(destinations) if destinations else 0,
        }

        return AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
                "accessibility_matrix": accessibility_matrix,
                "summary": {
                    "total": len(destinations),
                    "reachable": reachable_count,
                    "coverage_rate": reachable_count / len(destinations) if destinations else 0,
                },
                "metadata": metadata,
            },
            metadata=metadata
        )

    # ==========================================
    # 服务半径覆盖分析
    # ==========================================

    def _analyze_service_coverage(self, **kwargs) -> AdapterResult:
        """
        服务半径覆盖分析

        分析指定范围内的设施覆盖情况

        Args:
            center: 中心坐标 (lon, lat)
            radius: 服务半径（米）
            poi_type: POI 类型（如 "学校"、"医院"）
            population_points: 人口分布点列表 [(lon, lat, population), ...]
            use_standard_radius: 是否使用标准服务半径

        Returns:
            AdapterResult: 包含覆盖分析结果
        """
        center = kwargs.get("center")
        radius = kwargs.get("radius", 500)
        poi_type = kwargs.get("poi_type", "学校")
        population_points = kwargs.get("population_points", [])
        use_standard_radius = kwargs.get("use_standard_radius", True)

        if not center:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 center 参数"
            )

        if not self._provider or not self._provider.api_key:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="天地图服务不可用"
            )

        # 使用标准服务半径（如果启用）
        if use_standard_radius and poi_type in self.SERVICE_RADIUS_STANDARDS:
            radius = self.SERVICE_RADIUS_STANDARDS[poi_type]

        # 搜索范围内的 POI
        poi_result = self._provider.search_poi(
            keyword=poi_type,
            center=center,
            radius=radius * 3  # 扩大搜索范围以获取周边设施
        )

        facilities = []
        if poi_result.success:
            facilities = poi_result.data.get("pois", [])

        # 计算覆盖情况
        covered_points = []
        uncovered_points = []

        if population_points:
            for point in population_points:
                if len(point) >= 2:
                    point_coords = (point[0], point[1])
                    point_pop = point[2] if len(point) >= 3 else 1

                    # 检查是否有设施覆盖此点
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
            # 如果没有人口点数据，返回设施分布
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

        # 构建 GeoJSON
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

        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        metadata = {
            "source": "TiandituPOI",
            "analysis_type": "service_coverage",
            "center": center,
            "radius": radius,
            "poi_type": poi_type,
            "facility_count": len(facilities),
            "covered_count": len(covered_points),
            "uncovered_count": len(uncovered_points),
            "coverage_rate": covered_pop / total_pop if total_pop > 0 else 0,
            "use_standard_radius": use_standard_radius,
        }

        return AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
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
                "metadata": metadata,
            },
            metadata=metadata
        )

    # ==========================================
    # POI 覆盖分析
    # ==========================================

    def _analyze_poi_coverage(self, **kwargs) -> AdapterResult:
        """
        POI 设施覆盖分析

        分析多种类型设施的覆盖情况

        Args:
            center: 中心坐标 (lon, lat)
            poi_types: POI 类型列表 ["学校", "医院", ...]
            radii: 各类型的服务半径列表 [500, 1000, ...]

        Returns:
            AdapterResult: 包含多类型覆盖分析结果
        """
        center = kwargs.get("center")
        poi_types = kwargs.get("poi_types", ["学校", "医院", "公园"])
        radii = kwargs.get("radii")

        if not center:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少 center 参数"
            )

        if not self._provider or not self._provider.api_key:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="天地图服务不可用"
            )

        # 分析每种类型的覆盖情况
        coverage_by_type = {}

        for i, poi_type in enumerate(poi_types):
            # 获取半径
            if radii and i < len(radii):
                radius = radii[i]
            elif poi_type in self.SERVICE_RADIUS_STANDARDS:
                radius = self.SERVICE_RADIUS_STANDARDS[poi_type]
            else:
                radius = 500  # 默认半径

            # 搜索 POI
            poi_result = self._provider.search_poi(
                keyword=poi_type,
                center=center,
                radius=radius * 2
            )

            facilities = []
            if poi_result.success:
                facilities = poi_result.data.get("pois", [])

            # 筛选范围内的设施
            in_range_facilities = []
            for facility in facilities:
                facility_coords = (facility.get("lon", 0), facility.get("lat", 0))
                distance = haversine_distance(center, facility_coords)

                if distance <= radius:
                    in_range_facilities.append({
                        **facility,
                        "within_radius": True,
                    })

            coverage_by_type[poi_type] = {
                "radius": radius,
                "total_found": len(facilities),
                "in_range": len(in_range_facilities),
                "facilities": in_range_facilities,
                "coverage_rate": len(in_range_facilities) / max(len(facilities), 1),
            }

        # 计算总体覆盖情况
        total_types = len(poi_types)
        covered_types = sum(1 for t in coverage_by_type.values() if t["in_range"] > 0)

        metadata = {
            "source": "TiandituPOI",
            "analysis_type": "poi_coverage",
            "center": center,
            "total_types": total_types,
            "covered_types": covered_types,
            "type_coverage_rate": covered_types / total_types if total_types > 0 else 0,
        }

        return AdapterResult(
            success=True,
            status=AdapterStatus.SUCCESS,
            data={
                "coverage_by_type": coverage_by_type,
                "summary": {
                    "total_types": total_types,
                    "covered_types": covered_types,
                    "type_coverage_rate": covered_types / total_types if total_types > 0 else 0,
                },
                "metadata": metadata,
            },
            metadata=metadata
        )