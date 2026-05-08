"""天地图核心 API 封装"""
import time
import re
import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple, Optional, List

from .types import TiandituResult
from .constants import (
    SEARCH_URL,
    GEOCODER_URL,
    ADMIN_API,
    ROUTE_URL,
    WFS_URL
)
from .tiles import TileService
from .wfs import WfsService
from ..rate_limiter import RateLimiter
from ....core.config import (
    TIANDITU_API_KEY,
    TIANDITU_RATE_LIMIT,
    TIANDITU_MAX_RETRIES,
    GIS_TIMEOUT
)
from ....utils.logger import get_logger

logger = get_logger(__name__)


def _parse_tianditu_pois(pois: List[Dict]) -> List[Dict]:
    """解析天地图 POI 列表为统一格式

    Args:
        pois: 天地图 API 返回的 POI 原始数据

    Returns:
        统一格式的 POI 列表 [{"name", "lon", "lat", "address", "category"}]
    """
    poi_list = []
    for poi in pois:
        lonlat = poi.get("lonlat", ",").split(",")
        poi_item = {
            "name": poi.get("name", ""),
            "lon": float(lonlat[0]) if len(lonlat) > 0 else 0,
            "lat": float(lonlat[1]) if len(lonlat) > 1 else 0,
            "address": poi.get("address", ""),
            "category": poi.get("typeName", "")
        }
        poi_list.append(poi_item)
    return poi_list


class TiandituProvider:
    """天地图 API 封装"""

    def __init__(self):
        self.api_key = TIANDITU_API_KEY
        self.rate_limit = TIANDITU_RATE_LIMIT  # QPS
        self.max_retries = TIANDITU_MAX_RETRIES
        self.timeout = GIS_TIMEOUT

        # 使用全局速率限制器（与其他天地图组件共享）
        self._rate_limiter = RateLimiter.get_instance("tianditu", self.rate_limit)

        # 子服务（共享同一速率限制器）
        self.tile_service = TileService(self.api_key)
        self.wfs_service = WfsService(self.api_key, rate_limiter=self._rate_limiter)

        if not self.api_key:
            logger.warning("[TiandituProvider] TIANDITU_API_KEY 未配置")

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头（服务端密钥校验 IP 白名单，不需要 Referer）"""
        return {
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0"
        }

    def _rate_limit_wait(self):
        """使用全局速率限制器等待"""
        self._rate_limiter.wait()

    def _request(self, url: str, params: Dict[str, Any]) -> TiandituResult:
        """发送请求（含重试）"""
        if not self.api_key:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error="TIANDITU_API_KEY 未配置"
            )

        # 添加 token
        params["tk"] = self.api_key

        for attempt in range(self.max_retries):
            self._rate_limit_wait()

            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self.timeout
                )

                # 处理特殊错误码
                if resp.status_code == 418:
                    # 服务端密钥校验 IP 白名单，而非 Referer
                    logger.warning("[TiandituProvider] 418 错误，请检查 IP 白名单配置")
                    return TiandituResult(
                        success=False,
                        data={},
                        metadata={},
                        error="418 错误：请在天地图控制台配置 IP 白名单（本地测试可留空）"
                    )

                if resp.status_code == 429:
                    # 速率限制，等待后重试
                    wait_time = 2 ** attempt
                    logger.warning(f"[TiandituProvider] 429 速率限制，等待 {wait_time}s")
                    time.sleep(wait_time)
                    continue

                if resp.status_code >= 500:
                    # 服务端错误，重试
                    wait_time = 2 ** attempt
                    logger.warning(f"[TiandituProvider] {resp.status_code} 错误，等待 {wait_time}s 重试")
                    time.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    return TiandituResult(
                        success=False,
                        data={},
                        metadata={},
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )

                # 尝试解析 JSON，失败则返回原始文本（如 drive API 返回 XML）
                try:
                    data = resp.json()
                except ValueError:
                    # 非 JSON 响应，返回原始文本
                    return TiandituResult(
                        success=True,
                        data=resp.text,
                        metadata={"source": "tianditu", "url": url, "format": "raw"}
                    )

                # 检查 API 返回状态
                # V2 API: status={"infocode": 1000} 成功, 行政区划API: status=200 成功, 旧 API: status="0" 成功
                if "status" in data:
                    status = data["status"]
                    # V2 Search API 返回 status 对象
                    if isinstance(status, dict):
                        if status.get("infocode") != 1000:
                            return TiandituResult(
                                success=False,
                                data={},
                                metadata={},
                                error=f"API 错误: {status.get('cndesc', '未知错误')}"
                            )
                    elif status != 200 and status != "0":
                        return TiandituResult(
                            success=False,
                            data={},
                            metadata={},
                            error=f"API 错误: {data.get('message', data.get('msg', '未知错误'))}"
                        )

                return TiandituResult(
                    success=True,
                    data=data,
                    metadata={"source": "tianditu", "url": url}
                )

            except requests.Timeout:
                logger.warning(f"[TiandituProvider] 请求超时，重试 {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={},
                    error="请求超时"
                )

            except requests.RequestException as e:
                logger.error(f"[TiandituProvider] 请求异常: {e}")
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={},
                    error=str(e)
                )

        return TiandituResult(
            success=False,
            data={},
            metadata={},
            error="重试次数耗尽"
        )

    def get_boundary(self, location: str, level: str = "county") -> TiandituResult:
        """获取行政边界（使用 V2 API）"""
        # V2 API 参数格式
        params = {
            "keyword": location,
            "extensions": "true"
        }

        result = self._request(ADMIN_API, params)

        if not result.success:
            return result

        data = result.data

        # V2 API 返回格式: {"status": 200, "data": {"district": [...]}
        if data.get("status") != 200:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"API 错误: {data.get('message', '未知错误')}"
            )

        districts = data.get("data", {}).get("district", [])
        if not districts:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"未找到 {location} 的行政边界"
            )

        # 取第一个匹配结果
        district = districts[0]

        # 解析 MULTIPOLYGON WKT 格式的边界数据
        boundary_wkt = district.get("boundary", "")
        coordinates = self._parse_wkt_multipolygon(boundary_wkt)

        # 构建 GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "name": district.get("name", location),
                    "admin_code": district.get("gb", ""),
                    "level": district.get("level", 0)
                },
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": coordinates
                }
            }]
        }

        # 获取中心点 (V2 API 使用 lng/lat)
        center = district.get("center", {})
        center_coord = (center.get("lng", 0), center.get("lat", 0))

        return TiandituResult(
            success=True,
            data={
                "geojson": geojson,
                "center": center_coord
            },
            metadata={
                "center": center_coord,
                "admin_code": district.get("gb", ""),
                "level": district.get("level", 0),
                "location": location,
                "source": "tianditu_v2"
            }
        )

    def _parse_wkt_multipolygon(self, wkt: str) -> List[List[List[List[float]]]]:
        """解析 MULTIPOLYGON WKT 格式为 GeoJSON coordinates"""
        if not wkt or not wkt.startswith("MULTIPOLYGON"):
            return [[]]

        # 移除 MULTIPOLYGON 前缀
        coords_str = wkt.replace("MULTIPOLYGON", "").strip()

        # 解析多层括号结构
        polygons = []

        try:
            # 提取所有数字对
            coord_pairs = re.findall(r'(\d+\.\d+)\s+(\d+\.\d+)', coords_str)
            if coord_pairs:
                # 转换为 [lng, lat] 格式
                ring = [[float(lon), float(lat)] for lon, lat in coord_pairs]
                polygons.append([ring])
        except Exception as e:
            logger.warning(f"[TiandituProvider] WKT 解析失败: {e}")
            return [[]]

        return polygons if polygons else [[]]

    def search_poi(
        self,
        keyword: str,
        center: Tuple[float, float],
        radius: int = 1000,
        page_size: int = 20
    ) -> TiandituResult:
        """周边 POI 搜索（V2 API queryType=3）"""
        # V2 API 周边搜索参数格式
        params = {
            "postStr": f'{{"keyWord":"{keyword}","queryRadius":"{radius}","pointLonlat":"{center[0]},{center[1]}","queryType":"3","start":0,"count":"{page_size}"}}',
            "type": "query"
        }

        result = self._request(SEARCH_URL, params)

        if not result.success:
            return result

        data = result.data

        # V2 API 返回格式检查
        if data.get("resultType") != 1:
            # resultType=1 是 POI 结果
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"未找到 {keyword} 相关 POI"
            )

        pois = data.get("pois", [])
        total = data.get("count", len(pois))

        # 使用辅助函数解析 POI
        poi_list = _parse_tianditu_pois(pois)

        # 构建 GeoJSON Feature
        features = []
        for poi_item in poi_list:
            features.append({
                "type": "Feature",
                "properties": poi_item,
                "geometry": {
                    "type": "Point",
                    "coordinates": [poi_item["lon"], poi_item["lat"]]
                }
            })

        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        return TiandituResult(
            success=True,
            data={"pois": poi_list, "geojson": geojson},
            metadata={
                "keyword": keyword,
                "total_count": total,
                "center": center,
                "radius": radius,
                "source": "tianditu"
            }
        )

    def search_poi_in_region(self, keyword: str, region: str, page_size: int = 20) -> TiandituResult:
        """区域内 POI 搜索（V2 API 行政区划区域搜索 queryType=12）"""
        # V2 API 行政区划区域搜索参数格式
        params = {
            "postStr": f'{{"keyWord":"{keyword}","specify":"{region}","queryType":"12","start":0,"count":"{page_size}"}}',
            "type": "query"
        }

        result = self._request(SEARCH_URL, params)

        if not result.success:
            return result

        data = result.data

        # V2 API 返回格式检查
        if data.get("resultType") != 1:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"未找到 {keyword} 相关 POI"
            )

        pois = data.get("pois", [])
        total = data.get("count", len(pois))

        # 使用辅助函数解析 POI
        poi_list = _parse_tianditu_pois(pois)

        # 构建 GeoJSON Feature
        features = []
        for poi_item in poi_list:
            features.append({
                "type": "Feature",
                "properties": poi_item,
                "geometry": {
                    "type": "Point",
                    "coordinates": [poi_item["lon"], poi_item["lat"]]
                }
            })

        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        return TiandituResult(
            success=True,
            data={"pois": poi_list, "geojson": geojson},
            metadata={
                "keyword": keyword,
                "total_count": total,
                "region": region,
                "source": "tianditu"
            }
        )

    def geocode(self, address: str) -> TiandituResult:
        """地址转坐标（使用新格式 ds参数）"""
        params = {
            "ds": f'{{"keyWord":"{address}"}}'
        }

        result = self._request(GEOCODER_URL, params)

        if not result.success:
            return result

        data = result.data
        location = data.get("location", {})

        if not location:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"未找到 {address} 的坐标"
            )

        return TiandituResult(
            success=True,
            data={
                "lon": float(location.get("lon", 0)),
                "lat": float(location.get("lat", 0)),
                "formatted_address": data.get("formatted_address", address)
            },
            metadata={"address": address, "source": "tianditu"}
        )

    def reverse_geocode(self, lon: float, lat: float) -> TiandituResult:
        """坐标转地址"""
        params = {
            "postStr": f'{{"lon":{lon},"lat":{lat},"ver":1}}',
            "type": "geocode"
        }

        result = self._request(GEOCODER_URL, params)

        if not result.success:
            return result

        data = result.data
        address = data.get("formatted_address", "")

        # 解析行政区划
        result_data = {
            "formatted_address": address,
            "province": data.get("province", ""),
            "city": data.get("city", ""),
            "county": data.get("county", ""),
            "town": data.get("town", "")
        }

        return TiandituResult(
            success=True,
            data=result_data,
            metadata={"lon": lon, "lat": lat, "source": "tianditu"}
        )

    def get_wfs_data(
        self,
        layer_type: str,
        bbox: Tuple[float, float, float, float],
        max_features: int = 1000
    ) -> TiandituResult:
        """获取 WFS 图层数据（委托给 WfsService）"""
        return self.wfs_service.get_wfs_data(layer_type, bbox, max_features)

    def plan_route(
        self,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        route_type: int = 0
    ) -> TiandituResult:
        """路径规划

        Args:
            origin: 起点坐标 (lon, lat)
            destination: 终点坐标 (lon, lat)
            route_type: 路线类型 0=最快, 1=最短, 2=避开高速, 3=步行

        Returns:
            TiandituResult with route data
        """
        params = {
            "postStr": f'{{"orig":"{origin[0]},{origin[1]}","dest":"{destination[0]},{destination[1]}","style":"{route_type}"}}',
            "type": "search"
        }

        result = self._request(ROUTE_URL, params)

        if not result.success:
            return result

        # drive API 返回 XML 格式，需要解析
        data = result.data
        if isinstance(data, str):
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={},
                    error="路径规划返回格式错误"
                )
        else:
            root = data

        # 解析 XML 结果
        distance_elem = root.find("distance")
        duration_elem = root.find("duration")
        routelatlon_elem = root.find("routelatlon")

        distance = float(distance_elem.text) if distance_elem is not None else 0
        duration = float(duration_elem.text) if duration_elem is not None else 0

        # 解析路径坐标
        route_coords = []
        if routelatlon_elem is not None and routelatlon_elem.text:
            coords_str = routelatlon_elem.text.strip()
            for coord_pair in coords_str.split(";"):
                if "," in coord_pair:
                    lon, lat = coord_pair.split(",")
                    route_coords.append([float(lon), float(lat)])

        # 构建 GeoJSON
        features = []
        if route_coords:
            features.append({
                "type": "Feature",
                "properties": {"type": "route"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": route_coords
                }
            })

        geojson = {
            "type": "FeatureCollection",
            "features": features
        }

        route_data = {
            "distance": distance * 1000,  # km -> m
            "duration": duration,  # seconds
            "steps": []
        }

        return TiandituResult(
            success=True,
            data={"route": route_data, "geojson": geojson},
            metadata={
                "origin": origin,
                "destination": destination,
                "distance": route_data["distance"],
                "duration": route_data["duration"],
                "steps_count": len(route_data["steps"]),
                "source": "tianditu"
            }
        )

    # ==================== 瓦片服务委托 ====================

    def get_tile_url(self, *args, **kwargs) -> str:
        """获取瓦片 URL（委托给 TileService）"""
        return self.tile_service.get_tile_url(*args, **kwargs)

    def get_tile_template(self, *args, **kwargs) -> str:
        """获取瓦片模板 URL（委托给 TileService）"""
        return self.tile_service.get_tile_template(*args, **kwargs)

    def get_annotation_url(self, *args, **kwargs) -> str:
        """获取注记瓦片 URL（委托给 TileService）"""
        return self.tile_service.get_annotation_url(*args, **kwargs)

    def get_annotation_template(self, *args, **kwargs) -> str:
        """获取注记模板 URL（委托给 TileService）"""
        return self.tile_service.get_annotation_template(*args, **kwargs)

    def get_global_boundary_url(self, *args, **kwargs) -> str:
        """获取全球境界瓦片 URL（委托给 TileService）"""
        return self.tile_service.get_global_boundary_url(*args, **kwargs)

    def get_3d_tiles_url(self, *args, **kwargs) -> str:
        """获取三维瓦片 URL（委托给 TileService）"""
        return self.tile_service.get_3d_tiles_url(*args, **kwargs)

    def get_layer_info(self) -> Dict[str, Any]:
        """获取所有可用图层信息"""
        return self.tile_service.get_layer_info()


__all__ = ["TiandituProvider"]