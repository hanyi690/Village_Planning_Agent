"""高德地图核心 API 封装"""
import math
import time
import requests
from typing import Dict, Any, Tuple, Optional, List

from .types import AmapResult
from .constants import (
    POI_TEXT_URL,
    POI_AROUND_URL,
    DRIVING_URL,
    WALKING_URL,
    GEOCODE_URL,
    REGEOCODE_URL,
    DISTRICT_URL,
    POI_TYPES_PUBLIC_SERVICE,
    POI_EXTENSIONS,
    DEFAULT_POI_PAGE_SIZE,
    DEFAULT_POI_OFFSET,
    DRIVING_STRATEGY,
)
from ..rate_limiter import RateLimiter
from ....core.config import (
    AMAP_API_KEY,
    AMAP_RATE_LIMIT,
    AMAP_MAX_RETRIES,
    GIS_TIMEOUT,
)
from ....utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# GCJ-02 → WGS84 坐标转换
# ==========================================

# 定义一些常量
_X_PI = 3.14159265358979324 * 3000.0 / 180.0
_PI = 3.1415926535897932384626
_A = 6378245.0  # 长半轴
_EE = 0.00669342162296594323  # 偏心率平方


def _out_of_china(lon: float, lat: float) -> bool:
    """判断是否在国内，不在国内则不做偏移"""
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(lon: float, lat: float) -> float:
    """纬度转换"""
    ret = -100.0 + 2.0 * lon + 3.0 * lat + 0.2 * lat * lat + \
          0.1 * lon * lat + 0.2 * math.sqrt(abs(lon))
    ret += (20.0 * math.sin(6.0 * lon * _PI) + 20.0 *
            math.sin(2.0 * lon * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * _PI) + 40.0 *
            math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * _PI) + 320 *
            math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(lon: float, lat: float) -> float:
    """经度转换"""
    ret = 300.0 + lon + 2.0 * lat + 0.1 * lon * lon + \
          0.1 * lon * lat + 0.1 * math.sqrt(abs(lon))
    ret += (20.0 * math.sin(6.0 * lon * _PI) + 20.0 *
            math.sin(2.0 * lon * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lon * _PI) + 40.0 *
            math.sin(lon / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lon / 12.0 * _PI) + 300.0 *
            math.sin(lon / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    """GCJ-02 转 WGS-84

    高德地图使用的 GCJ-02 坐标系转 WGS-84 坐标系。

    Args:
        lon: GCJ-02 经度
        lat: GCJ-02 纬度

    Returns:
        (wgs_lon, wgs_lat): WGS-84 坐标
    """
    if _out_of_china(lon, lat):
        return lon, lat

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    mglat = lat + dlat
    mglon = lon + dlon
    return lon * 2 - mglon, lat * 2 - mglat


def _parse_route_steps(steps: List) -> Tuple[List[List[float]], List[Dict]]:
    """解析高德路径步骤为坐标和指令列表

    Args:
        steps: 高德 API 返回的步骤列表

    Returns:
        (route_coords, step_list): 路径坐标列表和步骤信息列表
    """
    route_coords = []
    step_list = []

    for step in steps:
        polyline = step.get("polyline", "")
        if polyline:
            for coord_pair in polyline.split(";"):
                if "," in coord_pair:
                    parts = coord_pair.split(",")
                    route_coords.append([float(parts[0]), float(parts[1])])

        step_list.append({
            "instruction": step.get("instruction", ""),
            "road": step.get("road", ""),
            "distance": int(step.get("distance", 0)),
            "duration": int(step.get("duration", 0)),
        })

    return route_coords, step_list


class AmapProvider:
    """高德地图 API 封装"""

    def __init__(self):
        self.api_key = AMAP_API_KEY
        self.rate_limit = AMAP_RATE_LIMIT  # QPS
        self.max_retries = AMAP_MAX_RETRIES
        self.timeout = GIS_TIMEOUT

        # 使用全局速率限制器
        self._rate_limiter = RateLimiter.get_instance("amap", self.rate_limit)

        if not self.api_key:
            logger.warning("[AmapProvider] AMAP_API_KEY 未配置")

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0",
        }

    def _rate_limit_wait(self):
        """使用全局速率限制器等待"""
        self._rate_limiter.wait()

    def _request(self, url: str, params: Dict[str, Any]) -> AmapResult:
        """发送请求（含重试）"""
        if not self.api_key:
            return AmapResult(
                success=False,
                data={},
                metadata={},
                error="AMAP_API_KEY 未配置",
            )

        # 添加 key 和 output 参数
        params["key"] = self.api_key
        params["output"] = "JSON"

        for attempt in range(self.max_retries):
            self._rate_limit_wait()

            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                )

                # 处理特殊错误码
                if resp.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"[AmapProvider] 429 速率限制，等待 {wait_time}s")
                    time.sleep(wait_time)
                    continue

                if resp.status_code >= 500:
                    wait_time = 2 ** attempt
                    logger.warning(f"[AmapProvider] {resp.status_code} 错误，等待 {wait_time}s 重试")
                    time.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    return AmapResult(
                        success=False,
                        data={},
                        metadata={},
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )

                data = resp.json()

                # 检查高德 API 返回状态
                # status="1" 表示成功，infocode=10000 表示正常
                status = data.get("status", "0")
                infocode = data.get("infocode", "0")

                if status != "1" or infocode != "10000":
                    error_msg = data.get("info", "未知错误")
                    return AmapResult(
                        success=False,
                        data={},
                        metadata={},
                        error=f"API 错误 ({infocode}): {error_msg}",
                    )

                return AmapResult(
                    success=True,
                    data=data,
                    metadata={"source": "amap", "url": url},
                )

            except requests.Timeout:
                logger.warning(f"[AmapProvider] 请求超时，重试 {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return AmapResult(
                    success=False,
                    data={},
                    metadata={},
                    error="请求超时",
                )

            except requests.RequestException as e:
                logger.error(f"[AmapProvider] 请求异常: {e}")
                return AmapResult(
                    success=False,
                    data={},
                    metadata={},
                    error=str(e),
                )

        return AmapResult(
            success=False,
            data={},
            metadata={},
            error="重试次数耗尽",
        )

    # ==================== POI 搜索 ====================

    def search_poi_keyword(
        self,
        keywords: str,
        city: Optional[str] = None,
        citylimit: bool = False,
        page_size: int = DEFAULT_POI_PAGE_SIZE,
        page: int = DEFAULT_POI_OFFSET,
    ) -> AmapResult:
        """关键字 POI 搜索

        Args:
            keywords: 搜索关键字
            city: 城市/区域名称（可选）
            citylimit: 是否限定在城市范围内
            page_size: 每页结果数（最大 25）
            page: 当前页码（从 1 开始）

        Returns:
            AmapResult with POI list
        """
        params = {
            "keywords": keywords,
            "extensions": POI_EXTENSIONS,
            "offset": str(page_size),
            "page": str(page),
        }

        if city:
            params["city"] = city
            params["citylimit"] = "true" if citylimit else "false"

        result = self._request(POI_TEXT_URL, params)

        if not result.success:
            return result

        data = result.data
        pois = data.get("pois", [])
        count = int(data.get("count", 0))

        poi_list = self._parse_pois(pois)

        return AmapResult(
            success=True,
            data={"pois": poi_list, "total": count},
            metadata={
                "keyword": keywords,
                "city": city,
                "total_count": count,
                "source": "amap",
            },
        )

    def search_poi_nearby(
        self,
        keywords: str,
        location: Tuple[float, float],
        radius: int = 1000,
        page_size: int = DEFAULT_POI_PAGE_SIZE,
        page: int = DEFAULT_POI_OFFSET,
    ) -> AmapResult:
        """周边 POI 搜索

        Args:
            keywords: 搜索关键字
            location: 中心点坐标 (lon, lat)
            radius: 搜索半径（米），最大 50000
            page_size: 每页结果数（最大 25）
            page: 当前页码（从 1 开始）

        Returns:
            AmapResult with POI list and distances
        """
        params = {
            "keywords": keywords,
            "location": f"{location[0]},{location[1]}",
            "radius": str(radius),
            "extensions": POI_EXTENSIONS,
            "offset": str(page_size),
            "page": str(page),
        }

        result = self._request(POI_AROUND_URL, params)

        if not result.success:
            return result

        data = result.data
        pois = data.get("pois", [])
        count = int(data.get("count", 0))

        poi_list = self._parse_pois(pois)

        return AmapResult(
            success=True,
            data={"pois": poi_list, "total": count},
            metadata={
                "keyword": keywords,
                "center": location,
                "radius": radius,
                "total_count": count,
                "source": "amap",
            },
        )

    def search_poi_by_types(
        self,
        types: str,
        location: Tuple[float, float],
        radius: int = 1000,
        page_size: int = DEFAULT_POI_PAGE_SIZE,
        page: int = DEFAULT_POI_OFFSET,
    ) -> AmapResult:
        """按类型码搜索周边 POI

        Args:
            types: POI 类型码，多个类型用 | 分隔（如 "090100|141200"）
            location: 中心点坐标 (lon, lat)
            radius: 搜索半径（米）
            page_size: 每页结果数
            page: 当前页码

        Returns:
            AmapResult with POI list
        """
        params = {
            "types": types,
            "location": f"{location[0]},{location[1]}",
            "radius": str(radius),
            "extensions": POI_EXTENSIONS,
            "offset": str(page_size),
            "page": str(page),
        }

        result = self._request(POI_AROUND_URL, params)

        if not result.success:
            return result

        data = result.data
        pois = data.get("pois", [])
        count = int(data.get("count", 0))

        poi_list = self._parse_pois(pois)

        return AmapResult(
            success=True,
            data={"pois": poi_list, "total": count},
            metadata={
                "types": types,
                "center": location,
                "radius": radius,
                "total_count": count,
                "source": "amap",
            },
        )

    def _parse_pois(self, pois: List[Dict]) -> List[Dict[str, Any]]:
        """解析 POI 数据为统一格式

        注意：高德 POI 坐标为 GCJ-02，需要转换为 WGS-84
        """
        poi_list = []
        for poi in pois:
            # 高德坐标格式: "lon,lat" (GCJ-02)
            location_str = poi.get("location", "")
            lon, lat = 0.0, 0.0
            gcj_lon, gcj_lat = 0.0, 0.0
            if location_str and "," in location_str:
                parts = location_str.split(",")
                gcj_lon = float(parts[0])
                gcj_lat = float(parts[1])
                # GCJ-02 → WGS-84 坐标转换
                lon, lat = gcj02_to_wgs84(gcj_lon, gcj_lat)

            poi_item = {
                "id": poi.get("id", ""),
                "name": poi.get("name", ""),
                "lon": lon,
                "lat": lat,
                # 保留原始 GCJ-02 坐标供参考
                "lon_gcj02": gcj_lon,
                "lat_gcj02": gcj_lat,
                "address": poi.get("address", "") or poi.get("pname", "") + poi.get("cityname", "") + poi.get("adname", ""),
                "distance": int(poi.get("distance", 0)) if poi.get("distance") else 0,
                "category": poi.get("type", ""),
                "typecode": poi.get("typecode", ""),
                "tel": poi.get("tel", ""),
            }
            poi_list.append(poi_item)

        return poi_list

    # ==================== 地理编码 ====================

    def geocode(self, address: str, city: Optional[str] = None) -> AmapResult:
        """地址转坐标

        Args:
            address: 地址字符串
            city: 城市（可选，用于提高精度）

        Returns:
            AmapResult with lon, lat
        """
        params = {"address": address}
        if city:
            params["city"] = city

        result = self._request(GEOCODE_URL, params)

        if not result.success:
            return result

        data = result.data
        geocodes = data.get("geocodes", [])

        if not geocodes:
            return AmapResult(
                success=False,
                data={},
                metadata={},
                error=f"未找到 {address} 的坐标",
            )

        geocode = geocodes[0]
        location_str = geocode.get("location", "")
        lon, lat = 0.0, 0.0
        if location_str and "," in location_str:
            parts = location_str.split(",")
            lon = float(parts[0])
            lat = float(parts[1])

        return AmapResult(
            success=True,
            data={
                "lon": lon,
                "lat": lat,
                "formatted_address": geocode.get("formatted_address", address),
                "level": geocode.get("level", ""),
                "adcode": geocode.get("adcode", ""),
            },
            metadata={"address": address, "city": city, "source": "amap"},
        )

    def reverse_geocode(self, lon: float, lat: float) -> AmapResult:
        """坐标转地址

        Args:
            lon: 经度
            lat: 纬度

        Returns:
            AmapResult with address info
        """
        params = {"location": f"{lon},{lat}"}

        result = self._request(REGEOCODE_URL, params)

        if not result.success:
            return result

        data = result.data
        regeocode = data.get("regeocode", {})

        address_component = regeocode.get("addressComponent", {})

        return AmapResult(
            success=True,
            data={
                "formatted_address": regeocode.get("formatted_address", ""),
                "province": address_component.get("province", ""),
                "city": address_component.get("city", ""),
                "district": address_component.get("district", ""),
                "towncode": address_component.get("towncode", ""),
                "street": address_component.get("streetNumber", {}).get("street", ""),
                "number": address_component.get("streetNumber", {}).get("number", ""),
                "adcode": address_component.get("adcode", ""),
            },
            metadata={"lon": lon, "lat": lat, "source": "amap"},
        )

    # ==================== 行政区划查询 ====================

    def get_district(
        self,
        keywords: str,
        subdistrict: int = 1,
        extensions: str = "base",
        filter_adcode: Optional[str] = None,
    ) -> AmapResult:
        """行政区划查询

        Args:
            keywords: 查询关键字（行政区名称、citycode、adcode）
            subdistrict: 子级行政区级数（0=不返回，1=下一级，2=下两级，3=下三级）
            extensions: 返回结果控制（base=基本信息，all=包含边界坐标）
            filter_adcode: 按行政区划过滤（adcode）

        Returns:
            AmapResult with district data

        Note:
            目前不能返回乡镇/街道级别的边界值
        """
        params = {
            "keywords": keywords,
            "subdistrict": str(subdistrict),
            "extensions": extensions,
        }

        if filter_adcode:
            params["filter"] = filter_adcode

        result = self._request(DISTRICT_URL, params)

        if not result.success:
            return result

        data = result.data
        districts = data.get("districts", [])

        if not districts:
            return AmapResult(
                success=False,
                data={},
                metadata={},
                error=f"未找到 {keywords} 的行政区划",
            )

        # 解析行政区划列表
        district_list = []
        for dist in districts:
            district_item = {
                "adcode": dist.get("adcode", ""),
                "name": dist.get("name", ""),
                "level": dist.get("level", ""),
                "citycode": dist.get("citycode", ""),
                "center": self._parse_center(dist.get("center", "")),
                "polyline": dist.get("polyline", ""),  # 边界坐标字符串
                "districts": dist.get("districts", []),  # 下级行政区
            }
            district_list.append(district_item)

        # 取第一个作为主结果
        main_district = district_list[0]

        # 如果 extensions=all，解析边界坐标为 GeoJSON
        geojson = None
        if extensions == "all" and main_district.get("polyline"):
            geojson = self._parse_polyline_to_geojson(
                main_district["polyline"],
                main_district["name"],
                main_district["adcode"]
            )

        return AmapResult(
            success=True,
            data={
                "district": main_district,
                "districts": district_list,
                "geojson": geojson,
            },
            metadata={
                "keyword": keywords,
                "subdistrict": subdistrict,
                "extensions": extensions,
                "source": "amap",
            },
        )

    def _parse_center(self, center_str: str) -> Tuple[float, float]:
        """解析中心坐标字符串"""
        if not center_str or "," not in center_str:
            return (0.0, 0.0)
        parts = center_str.split(",")
        return (float(parts[0]), float(parts[1]))

    def _parse_polyline_to_geojson(
        self,
        polyline: str,
        name: str,
        adcode: str
    ) -> Optional[Dict[str, Any]]:
        """解析 polyline 边界坐标为 GeoJSON

        高德 polyline 格式: "x1,y1;x2,y2;...|x1,y1;x2,y2;..."
        每个 | 分隔的是一个区域（可能是 MultiPolygon 的多个部分）
        """
        if not polyline:
            return None

        polygons = []
        for region in polyline.split("|"):
            if not region:
                continue
            ring = []
            for coord_pair in region.split(";"):
                if "," in coord_pair:
                    parts = coord_pair.split(",")
                    ring.append([float(parts[0]), float(parts[1])])
            if ring:
                # 确保 ring 是闭合的
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                polygons.append([ring])

        if not polygons:
            return None

        geometry_type = "Polygon" if len(polygons) == 1 else "MultiPolygon"
        coordinates = polygons[0] if len(polygons) == 1 else polygons

        return {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "name": name,
                    "adcode": adcode,
                },
                "geometry": {
                    "type": geometry_type,
                    "coordinates": coordinates,
                },
            }],
        }

    # ==================== 路径规划 ====================

    def plan_route_driving(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        strategy: int = 0,
        waypoints: Optional[List[Tuple[float, float]]] = None,
    ) -> AmapResult:
        """驾车路径规划

        Args:
            origin: 起点坐标 (lon, lat)
            destination: 终点坐标 (lon, lat)
            strategy: 路径策略（0=最快，1=最短，2=避开高速，3=避开拥堵）
            waypoints: 途经点坐标列表（可选）

        Returns:
            AmapResult with route data
        """
        params = {
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}",
            "strategy": str(strategy),
            "extensions": "all",
        }

        if waypoints:
            waypoint_strs = [f"{p[0]},{p[1]}" for p in waypoints]
            params["waypoints"] = ";".join(waypoint_strs)

        result = self._request(DRIVING_URL, params)

        if not result.success:
            return result

        data = result.data
        route = data.get("route", {})
        paths = route.get("paths", [])

        if not paths:
            return AmapResult(
                success=False,
                data={},
                metadata={},
                error="未找到可行路径",
            )

        # 取第一条路径
        path = paths[0]
        distance = int(path.get("distance", 0))  # 米
        duration = int(path.get("duration", 0))  # 秒

        # 使用辅助函数解析路径步骤
        steps = path.get("steps", [])
        route_coords, step_list = _parse_route_steps(steps)

        # 构建 GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"type": "route", "distance": distance, "duration": duration},
                "geometry": {
                    "type": "LineString",
                    "coordinates": route_coords,
                },
            }],
        }

        route_data = {
            "distance": distance,
            "duration": duration,
            "steps": step_list,
        }

        return AmapResult(
            success=True,
            data={"route": route_data, "geojson": geojson},
            metadata={
                "origin": origin,
                "destination": destination,
                "strategy": strategy,
                "distance": distance,
                "duration": duration,
                "steps_count": len(step_list),
                "source": "amap",
            },
        )

    def plan_route_walking(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
    ) -> AmapResult:
        """步行路径规划

        Args:
            origin: 起点坐标 (lon, lat)
            destination: 终点坐标 (lon, lat)

        Returns:
            AmapResult with route data
        """
        params = {
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}",
        }

        result = self._request(WALKING_URL, params)

        if not result.success:
            return result

        data = result.data
        route = data.get("route", {})
        paths = route.get("paths", [])

        if not paths:
            return AmapResult(
                success=False,
                data={},
                metadata={},
                error="未找到可行步行路径",
            )

        path = paths[0]
        distance = int(path.get("distance", 0))
        duration = int(path.get("duration", 0))

        # 使用辅助函数解析路径步骤
        steps = path.get("steps", [])
        route_coords, step_list = _parse_route_steps(steps)

        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"type": "walking_route", "distance": distance, "duration": duration},
                "geometry": {
                    "type": "LineString",
                    "coordinates": route_coords,
                },
            }],
        }

        route_data = {
            "distance": distance,
            "duration": duration,
            "steps": step_list,
        }

        return AmapResult(
            success=True,
            data={"route": route_data, "geojson": geojson},
            metadata={
                "origin": origin,
                "destination": destination,
                "distance": distance,
                "duration": duration,
                "steps_count": len(step_list),
                "source": "amap",
            },
        )


__all__ = ["AmapProvider", "gcj02_to_wgs84"]