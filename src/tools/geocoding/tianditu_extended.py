"""
天地图扩展服务

提供天地图 Web 服务 API 的完整封装：
1. 逆地理编码（坐标→地址）
2. POI 搜索（关键词+范围）
3. WFS 数据获取（交通/水系/居民地图层）
4. 路径规划（驾车/步行）
5. 距离测量

API 文档：http://lbs.tianditu.gov.cn/home/guide/guide.html
"""

import json
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

from ...utils.logger import get_logger
from ...utils.geo_utils import haversine_distance, calculate_total_distance

logger = get_logger(__name__)


class RouteType(Enum):
    """路径规划类型"""
    DRIVING = "driving"
    WALKING = "walking"
    BICYCLING = "bicycling"


class WFSLayerType(Enum):
    """WFS 图层类型"""
    # 交通要素
    LRRL = "LRRL"  # 铁路
    LRDL = "LRDL"  # 公路
    # 水系要素
    HYDA = "HYDA"  # 水系面
    HYDL = "HYDL"  # 水系线
    HYDP = "HYDP"  # 水系点
    # 居民地要素
    RESA = "RESA"  # 居民地面
    RESP = "RESP"  # 居民地点


@dataclass
class ReverseGeocodeResult:
    """
    逆地理编码结果

    Attributes:
        success: 是否成功
        address: 解析后的地址
        formatted_address: 格式化完整地址
        province: 省份
        city: 城市
        county: 县区
        town: 乡镇
        village: 村/社区
        poi_name: 最近的 POI 名称
        poi_distance: 到最近 POI 的距离（米）
        lon: 经度
        lat: 纬度
        error: 错误信息
    """
    success: bool
    address: Optional[str] = None
    formatted_address: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    town: Optional[str] = None
    village: Optional[str] = None
    poi_name: Optional[str] = None
    poi_distance: Optional[float] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class POIResult:
    """
    POI 搜索结果

    Attributes:
        success: 是否成功
        pois: POI 列表
        total_count: 总数量
        error: 错误信息
    """
    success: bool
    pois: List[Dict[str, Any]] = field(default_factory=list)
    total_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WFSResult:
    """
    WFS 数据获取结果

    Attributes:
        success: 是否成功
        geojson: GeoJSON FeatureCollection
        layer_name: 图层名称
        feature_count:要素数量
        error: 错误信息
    """
    success: bool
    geojson: Optional[Dict[str, Any]] = None
    layer_name: Optional[str] = None
    feature_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RouteResult:
    """
    路径规划结果

    Attributes:
        success: 是否成功
        distance: 总距离（米）
        duration: 总时长（秒）
        geometry: 路径几何坐标列表 [[lon, lat], ...]
        steps: 分段导航信息
        origin: 起点坐标
        destination: 终点坐标
        route_type: 路径类型
        error: 错误信息
    """
    success: bool
    distance: float = 0
    duration: float = 0
    geometry: List[List[float]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    origin: Optional[Tuple[float, float]] = None
    destination: Optional[Tuple[float, float]] = None
    route_type: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TiandituExtendedService:
    """
    天地图扩展服务

    提供天地图 Web 服务 API 的完整封装，支持：
    - 逆地理编码：坐标 → 地址
    - POI 搜索：关键词搜索周边兴趣点
    - WFS 数据：获取交通、水系、居民地等矢量图层
    - 路径规划：驾车、步行、骑行路线计算
    - 距离测量：多点距离计算

    使用方法：
    ```python
    service = TiandituExtendedService(api_key="your_key")

    # 逆地理编码
    result = service.reverse_geocode(115.891, 24.567)

    # POI 搜索
    result = service.search_poi("学校", center=(115.891, 24.567), radius=1000)

    # WFS 数据获取
    result = service.fetch_wfs_layer(WFSLayerType.LRDL, bbox=(115.8, 24.5, 116.0, 24.7))

    # 路径规划
    result = service.route_planning((115.891, 24.567), (116.0, 24.6), RouteType.DRIVING)
    ```
    """

    # API 基础 URL
    API_BASE = "http://api.tianditu.gov.cn"

    # 各服务端点
    REVERSE_GEOCODE_URL = "http://api.tianditu.gov.cn/geocoder"
    POI_SEARCH_URL = "http://api.tianditu.gov.cn/search"
    WFS_URL = "http://api.tianditu.gov.cn/api"
    ROUTE_URL = "http://api.tianditu.gov.cn/drive"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        """
        初始化天地图扩展服务

        Args:
            api_key: 天地图 API Key（可从环境变量 TIANDITU_API_KEY 获取）
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        if not self.api_key:
            try:
                from ...core.config import TIANDITU_API_KEY
                self.api_key = TIANDITU_API_KEY
            except ImportError:
                logger.warning("[TiandituExtended] 无法加载配置模块")

        if not self.api_key:
            logger.warning("[TiandituExtended] API Key 未配置，服务将不可用")

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return bool(self.api_key)

    # ==========================================
    # 逆地理编码
    # ==========================================

    def reverse_geocode(
        self,
        lon: float,
        lat: float,
        coord_type: str = "wgs84"
    ) -> ReverseGeocodeResult:
        """
        逆地理编码：坐标 → 地址

        Args:
            lon: 经度
            lat: 纬度
            coord_type: 坐标类型（wgs84/gcj02/bd09），天地图使用 wgs84

        Returns:
            ReverseGeocodeResult 包含解析后的地址信息
        """
        if not self.api_key:
            return ReverseGeocodeResult(
                success=False,
                error="天地图 API Key 未配置"
            )

        try:
            params = {
                "postStr": json.dumps({
                    "lon": lon,
                    "lat": lat,
                    "ver": 1,
                    "coord_type": coord_type
                }, ensure_ascii=False),
                "type": "geocoder",
                "tk": self.api_key
            }

            logger.info(f"[TiandituExtended] 逆地理编码: ({lon}, {lat})")

            response = self.session.get(
                self.REVERSE_GEOCODE_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()
            logger.debug(f"[TiandituExtended] 逆地理编码响应: {data}")

            return self._parse_reverse_geocode_response(data, lon, lat)

        except requests.Timeout:
            logger.warning(f"[TiandituExtended] 逆地理编码请求超时")
            return ReverseGeocodeResult(success=False, error="请求超时")
        except requests.RequestException as e:
            logger.warning(f"[TiandituExtended] 逆地理编码请求失败: {e}")
            return ReverseGeocodeResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"[TiandituExtended] 逆地理编码解析失败: {e}")
            return ReverseGeocodeResult(success=False, error=str(e))

    def _parse_reverse_geocode_response(
        self,
        data: Dict[str, Any],
        lon: float,
        lat: float
    ) -> ReverseGeocodeResult:
        """解析逆地理编码响应"""
        if data.get("status") != "0":
            return ReverseGeocodeResult(
                success=False,
                error=f"API 返回错误: status={data.get('status')}",
                lon=lon,
                lat=lat
            )

        result = data.get("result", {})
        if not result:
            return ReverseGeocodeResult(
                success=False,
                error="未找到地址信息",
                lon=lon,
                lat=lat
            )

        address_data = result.get("addressComponent", {})
        formatted_address = result.get("formatted_address", "")

        return ReverseGeocodeResult(
            success=True,
            address=formatted_address,
            formatted_address=formatted_address,
            province=address_data.get("province", ""),
            city=address_data.get("city", ""),
            county=address_data.get("county", ""),
            town=address_data.get("town", ""),
            village=address_data.get("village", ""),
            poi_name=result.get("pois", [{}])[0].get("name", "") if result.get("pois") else None,
            poi_distance=result.get("pois", [{}])[0].get("distance", 0) if result.get("pois") else None,
            lon=lon,
            lat=lat
        )

    # ==========================================
    # POI 搜索
    # ==========================================

    def search_poi(
        self,
        keyword: str,
        center: Optional[Tuple[float, float]] = None,
        radius: Optional[int] = None,
        bbox: Optional[Tuple[float, float, float, float]] = None,
        admin_code: Optional[str] = None,
        page_size: int = 20,
        page_index: int = 1
    ) -> POIResult:
        """
        POI 关键词搜索

        Args:
            keyword: 搜索关键词（如 "学校"、"医院"、"停车场"）
            center: 中心坐标 (lon, lat)，配合 radius 使用
            radius: 搜索半径（米），配合 center 使用
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat)
            admin_code: 行政区划代码，限定搜索范围
            page_size: 每页结果数量（最大 50）
            page_index: 页码（从 1 开始）

        Returns:
            POIResult 包含 POI 列表
        """
        if not self.api_key:
            return POIResult(success=False, error="天地图 API Key 未配置")

        try:
            post_data = {
                "keyWord": keyword,
                "queryType": "1",  # 关键词查询
                "start": str((page_index - 1) * page_size),
                "count": str(page_size),
            }

            if center and radius:
                post_data["centerLon"] = center[0]
                post_data["centerLat"] = center[1]
                post_data["radius"] = str(radius)

            if bbox:
                post_data["mapBound"] = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

            if admin_code:
                post_data["adminCode"] = admin_code

            params = {
                "postStr": json.dumps(post_data, ensure_ascii=False),
                "type": "query",
                "tk": self.api_key
            }

            logger.info(f"[TiandituExtended] POI 搜索: keyword={keyword}")

            response = self.session.get(
                self.POI_SEARCH_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_poi_response(data)

        except requests.Timeout:
            logger.warning(f"[TiandituExtended] POI 搜索请求超时")
            return POIResult(success=False, error="请求超时")
        except requests.RequestException as e:
            logger.warning(f"[TiandituExtended] POI 搜索请求失败: {e}")
            return POIResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"[TiandituExtended] POI 搜索解析失败: {e}")
            return POIResult(success=False, error=str(e))

    def search_poi_nearby(
        self,
        keyword: str,
        center: Tuple[float, float],
        radius: int = 1000
    ) -> POIResult:
        """
        周边POI搜索

        Args:
            keyword: 搜索关键词
            center: 中心坐标 (lon, lat)
            radius: 搜索半径（米）

        Returns:
            POIResult
        """
        return self.search_poi(keyword, center=center, radius=radius)

    def _parse_poi_response(self, data: Dict[str, Any]) -> POIResult:
        """解析 POI 搜索响应"""
        if data.get("status") != "0":
            return POIResult(
                success=False,
                error=f"API 返回错误: status={data.get('status')}"
            )

        pois = data.get("pois", [])
        if not pois:
            return POIResult(
                success=True,
                pois=[],
                total_count=0
            )

        # 解析每个 POI
        parsed_pois = []
        for poi in pois:
            parsed_pois.append({
                "name": poi.get("name", ""),
                "address": poi.get("address", ""),
                "lon": float(poi.get("lon", 0)),
                "lat": float(poi.get("lat", 0)),
                "category": poi.get("type", ""),
                "tel": poi.get("tel", ""),
                "distance": float(poi.get("distance", 0)) if poi.get("distance") else None,
            })

        return POIResult(
            success=True,
            pois=parsed_pois,
            total_count=data.get("count", len(parsed_pois))
        )

    # ==========================================
    # WFS 数据获取
    # ==========================================

    def fetch_wfs_layer(
        self,
        layer_type: WFSLayerType,
        bbox: Tuple[float, float, float, float],
        max_features: int = 1000
    ) -> WFSResult:
        """
        获取 WFS 矢量图层数据

        Args:
            layer_type: 图层类型（交通/水系/居民地）
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat)
            max_features: 最大要素数量

        Returns:
            WFSResult 包含 GeoJSON 数据
        """
        if not self.api_key:
            return WFSResult(success=False, error="天地图 API Key 未配置")

        try:
            # WFS GetFeature 请求参数
            params = {
                "SERVICE": "WFS",
                "VERSION": "1.0.0",
                "REQUEST": "GetFeature",
                "TYPENAME": layer_type.value,
                "MAXFEATURES": str(max_features),
                "OUTPUTFORMAT": "application/json",
                "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                "tk": self.api_key
            }

            logger.info(f"[TiandituExtended] WFS 获取: layer={layer_type.value}")

            response = self.session.get(
                self.WFS_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()

            # 构建 GeoJSON
            features = []
            raw_features = data.get("features", [])
            for feature in raw_features:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "source": "TiandituWFS",
                        "layer": layer_type.value,
                        **feature.get("properties", {})
                    },
                    "geometry": feature.get("geometry", {})
                })

            geojson = {
                "type": "FeatureCollection",
                "features": features
            }

            return WFSResult(
                success=True,
                geojson=geojson,
                layer_name=layer_type.value,
                feature_count=len(features)
            )

        except requests.Timeout:
            logger.warning(f"[TiandituExtended] WFS 请求超时")
            return WFSResult(success=False, error="请求超时")
        except requests.RequestException as e:
            logger.warning(f"[TiandituExtended] WFS 请求失败: {e}")
            return WFSResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"[TiandituExtended] WFS 解析失败: {e}")
            return WFSResult(success=False, error=str(e))

    def fetch_road_network(
        self,
        bbox: Tuple[float, float, float, float]
    ) -> WFSResult:
        """
        获取道路网络数据

        Args:
            bbox: 边界框

        Returns:
            WFSResult 包含公路数据
        """
        return self.fetch_wfs_layer(WFSLayerType.LRDL, bbox)

    def fetch_water_system(
        self,
        bbox: Tuple[float, float, float, float],
        include_lines: bool = True,
        include_areas: bool = True
    ) -> Dict[str, WFSResult]:
        """
        获取水系数据

        Args:
            bbox: 边界框
            include_lines: 是否包含水系线（河流）
            include_areas: 是否包含水系面（湖泊、水库）

        Returns:
            Dict 包含各类型水系数据
        """
        results = {}
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            if include_areas:
                futures["water_areas"] = executor.submit(
                    self.fetch_wfs_layer, WFSLayerType.HYDA, bbox
                )
            if include_lines:
                futures["water_lines"] = executor.submit(
                    self.fetch_wfs_layer, WFSLayerType.HYDL, bbox
                )
            for name, future in futures.items():
                results[name] = future.result()
        return results

    # ==========================================
    # 路径规划
    # ==========================================

    def route_planning(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        route_type: RouteType = RouteType.DRIVING
    ) -> RouteResult:
        """
        路径规划

        Args:
            origin: 起点坐标 (lon, lat)
            destination: 终点坐标 (lon, lat)
            route_type: 路径类型（驾车/步行/骑行）

        Returns:
            RouteResult 包含路径信息
        """
        if not self.api_key:
            return RouteResult(success=False, error="天地图 API Key 未配置")

        try:
            # 构建请求参数
            post_data = {
                "orig": f"{origin[0]},{origin[1]}",
                "dest": f"{destination[0]},{destination[1]}",
                "style": route_type.value
            }

            params = {
                "postStr": json.dumps(post_data, ensure_ascii=False),
                "type": "search",
                "tk": self.api_key
            }

            logger.info(
                f"[TiandituExtended] 路径规划: {origin} -> {destination}, type={route_type.value}"
            )

            response = self.session.get(
                self.ROUTE_URL,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_route_response(data, origin, destination, route_type)

        except requests.Timeout:
            logger.warning(f"[TiandituExtended] 路径规划请求超时")
            return RouteResult(success=False, error="请求超时")
        except requests.RequestException as e:
            logger.warning(f"[TiandituExtended] 路径规划请求失败: {e}")
            return RouteResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"[TiandituExtended] 路径规划解析失败: {e}")
            return RouteResult(success=False, error=str(e))

    def driving_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> RouteResult:
        """驾车路径规划"""
        return self.route_planning(origin, destination, RouteType.DRIVING)

    def walking_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float]
    ) -> RouteResult:
        """步行路径规划"""
        return self.route_planning(origin, destination, RouteType.WALKING)

    def _parse_route_response(
        self,
        data: Dict[str, Any],
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        route_type: RouteType
    ) -> RouteResult:
        """解析路径规划响应"""
        if data.get("status") != "0":
            return RouteResult(
                success=False,
                error=f"API 返回错误: status={data.get('status')}",
                origin=origin,
                destination=destination,
                route_type=route_type.value
            )

        routes = data.get("data", {}).get("routes", [])
        if not routes:
            return RouteResult(
                success=False,
                error="未找到可行路径",
                origin=origin,
                destination=destination,
                route_type=route_type.value
            )

        route = routes[0]

        # 解析路径几何
        geometry = []
        steps = []
        for segment in route.get("steps", []):
            segment_geom = []
            for coord in segment.get("geometry", []):
                segment_geom.append([coord[0], coord[1]])
                geometry.append([coord[0], coord[1]])

            steps.append({
                "instruction": segment.get("instruction", ""),
                "distance": segment.get("distance", 0),
                "duration": segment.get("duration", 0),
                "geometry": segment_geom
            })

        return RouteResult(
            success=True,
            distance=float(route.get("distance", 0)),
            duration=float(route.get("duration", 0)),
            geometry=geometry,
            steps=steps,
            origin=origin,
            destination=destination,
            route_type=route_type.value
        )

    # ==========================================
    # 距离测量
    # ==========================================

    def measure_distance(
        self,
        points: List[Tuple[float, float]],
        coord_type: str = "wgs84"
    ) -> float:
        """
        测量多点距离

        Args:
            points: 坐标点列表 [(lon, lat), ...]
            coord_type: 坐标类型

        Returns:
            总距离（米）
        """
        if not self.api_key:
            logger.warning("[TiandituExtended] API Key 未配置，使用简化计算")
            return self._haversine_distance(points)

        if len(points) < 2:
            return 0.0

        try:
            # 构建测量参数
            coords_str = ";".join([f"{p[0]},{p[1]}" for p in points])

            post_data = {
                "points": coords_str,
                "coord_type": coord_type
            }

            params = {
                "postStr": json.dumps(post_data, ensure_ascii=False),
                "type": "measure",
                "tk": self.api_key
            }

            logger.info(f"[TiandituExtended] 距离测量: {len(points)} 个点")

            response = self.session.get(
                f"{self.API_BASE}/measure",
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()

            if data.get("status") == "0":
                return float(data.get("data", {}).get("distance", 0))
            else:
                logger.warning(f"[TiandituExtended] 距离测量 API 失败，使用简化计算")
                return self._haversine_distance(points)

        except Exception as e:
            logger.warning(f"[TiandituExtended] 距离测量失败: {e}, 使用简化计算")
            return calculate_total_distance(points)

    def _haversine_distance(self, points: List[Tuple[float, float]]) -> float:
        """
        使用 Haversine 公式计算距离（简化版，不考虑地形）

        已重构为使用共享工具函数。

        Args:
            points: 坐标点列表

        Returns:
            总距离（米）
        """
        return calculate_total_distance(points)


# 模块级单例
_extended_service: Optional[TiandituExtendedService] = None


def get_extended_service() -> TiandituExtendedService:
    """
    获取天地图扩展服务单例

    Returns:
        TiandituExtendedService 实例
    """
    global _extended_service
    if _extended_service is None:
        _extended_service = TiandituExtendedService()
    return _extended_service