"""
天地图 API 封装

直接封装天地图 REST API，支持：
- 行政区划查询
- POI 搜索
- 地理编码/逆地理编码
- WFS 图层获取
- 路径规划
"""

import time
import re
import requests
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass

from ...core.config import (
    TIANDITU_API_KEY,
    TIANDITU_RATE_LIMIT,
    TIANDITU_MAX_RETRIES,
    GIS_TIMEOUT
)
from ...utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TiandituResult:
    """天地图 API 返回结果"""
    success: bool
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    error: Optional[str] = None


class TiandituProvider:
    """天地图 API 封装"""

    # API endpoints
    BASE_URL = "https://api.tianditu.gov.cn"
    SEARCH_URL = f"{BASE_URL}/v2/search"
    GEOCODER_URL = f"{BASE_URL}/geocoder"

    # 行政区划查询 endpoints
    ADMIN_API = "https://api.tianditu.gov.cn/v2/administrative"

    # WFS endpoints
    WFS_URL = "http://gisserver.tianditu.gov.cn/TDTService/wfs"

    # 路径规划 endpoints
    ROUTE_URL = "https://api.tianditu.gov.cn/drive"

    def __init__(self):
        self.api_key = TIANDITU_API_KEY
        self.rate_limit = TIANDITU_RATE_LIMIT  # QPS
        self.max_retries = TIANDITU_MAX_RETRIES
        self.timeout = GIS_TIMEOUT
        self._last_request_time = 0

        if not self.api_key:
            logger.warning("[TiandituProvider] TIANDITU_API_KEY 未配置")

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头（服务端密钥校验 IP 白名单，不需要 Referer）"""
        return {
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0"
        }

    def _rate_limit_wait(self):
        """速率限制等待"""
        if self.rate_limit <= 0:
            return
        min_interval = 1.0 / self.rate_limit
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

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

        result = self._request(self.ADMIN_API, params)

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

        # 提取括号内的坐标部分
        import re

        # MULTIPOLYGON(((x y, x y, ...)))
        # 转换为 GeoJSON MultiPolygon 格式: [[[x, y], [x, y], ...]]

        # 移除 MULTIPOLYGON 前缀
        coords_str = wkt.replace("MULTIPOLYGON", "").strip()

        # 解析多层括号结构
        polygons = []

        # 使用正则提取每个 POLYGON 的坐标
        # 匹配 (((...))) 这样的结构
        polygon_pattern = r'\(\(([^)]+(?:\)[^)]*)*)\)\)'

        # 简化处理：直接解析坐标
        try:
            # 提取所有数字对
            coord_pairs = re.findall(r'(\d+\.\d+)\s+(\d+\.\d+)', coords_str)
            if coord_pairs:
                # 转换为 [lng, lat] 格式
                ring = [[float(lon), float(lat)] for lon, lat in coord_pairs]
                # MultiPolygon 格式: [polygon1, polygon2, ...]
                # 每个 polygon: [ring1, ring2, ...]
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

        result = self._request(self.SEARCH_URL, params)

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

        # 构建 POI 列表
        poi_list = []
        features = []

        for poi in pois:
            # V2 API 坐标格式: "lon,lat"
            lonlat = poi.get("lonlat", ",").split(",")
            poi_item = {
                "name": poi.get("name", ""),
                "lon": float(lonlat[0]) if len(lonlat) > 0 else 0,
                "lat": float(lonlat[1]) if len(lonlat) > 1 else 0,
                "address": poi.get("address", ""),
                "distance": poi.get("distance", ""),
                "category": poi.get("typeName", "")
            }
            poi_list.append(poi_item)

            # 构建 GeoJSON Feature
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

        result = self._request(self.SEARCH_URL, params)

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

        poi_list = []
        features = []

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

        result = self._request(self.GEOCODER_URL, params)

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

        result = self._request(self.GEOCODER_URL, params)

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
        """获取 WFS 图层数据"""
        params = {
            "SERVICE": "WFS",
            "VERSION": "1.0.0",
            "REQUEST": "GetFeature",
            "TYPENAME": layer_type,
            "MAXFEATURES": max_features,
            "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "OUTPUTFORMAT": "application/json",
            "tk": self.api_key
        }

        # WFS 使用不同的请求方式
        url = f"{self.WFS_URL}?SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature&TYPENAME={layer_type}&MAXFEATURES={max_features}&BBOX={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}&OUTPUTFORMAT=application/json&tk={self.api_key}"

        self._rate_limit_wait()

        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=self.timeout)

            if resp.status_code != 200:
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={},
                    error=f"WFS HTTP {resp.status_code}"
                )

            geojson = resp.json()

            features = geojson.get("features", [])

            return TiandituResult(
                success=True,
                data={"geojson": geojson},
                metadata={
                    "layer": layer_type,
                    "feature_count": len(features),
                    "bbox": bbox,
                    "source": "tianditu_wfs"
                }
            )

        except Exception as e:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=str(e)
            )

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

        result = self._request(self.ROUTE_URL, params)

        if not result.success:
            return result

        # drive API 返回 XML 格式，需要解析
        import xml.etree.ElementTree as ET

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

    # ==================== 地图瓦片服务 ====================

    # 瓦片图层类型定义
    TILE_LAYERS = {
        "vec": "矢量底图",
        "img": "影像底图",
        "ter": "地形晕渲"
    }

    # 注记图层类型定义
    ANNOTATION_LAYERS = {
        "cva": "矢量注记",
        "cia": "影像注记",
        "cta": "地形注记"
    }

    def get_tile_url(
        self,
        layer: str = "vec",
        projection: str = "c",
        x: int = 0,
        y: int = 0,
        z: int = 1,
        server: int = 0
    ) -> str:
        """获取单个瓦片 URL

        Args:
            layer: 图层类型 vec=矢量, img=影像, ter=地形
            projection: 投影类型 c=经纬度投影, w=球面墨卡托投影
            x: 瓦片列号
            y: 瓦片行号
            z: 缩放级别 (1-18)
            server: 服务器编号 (0-7)，用于负载均衡

        Returns:
            瓦片图片 URL
        """
        if layer not in self.TILE_LAYERS:
            logger.warning(f"[TiandituProvider] 未知的图层类型: {layer}")
        if projection not in ("c", "w"):
            logger.warning(f"[TiandituProvider] 未知的投影类型: {projection}")

        return (
            f"http://t{server}.tianditu.gov.cn/{layer}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={layer}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
            f"&tk={self.api_key}"
        )

    def get_tile_template(
        self,
        layer: str = "vec",
        projection: str = "c"
    ) -> str:
        """获取瓦片模板 URL（用于 Leaflet/Mapbox）

        Args:
            layer: 图层类型 vec=矢量, img=影像, ter=地形
            projection: 投影类型 c=经纬度投影, w=球面墨卡托投影

        Returns:
            包含 {s}/{z}/{x}/{y} 占位符的模板 URL
        """
        return (
            f"http://t{{s}}.tianditu.gov.cn/{layer}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={layer}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}"
            f"&tk={self.api_key}"
        )

    def get_annotation_url(
        self,
        annotation_type: str = "cva",
        projection: str = "c",
        x: int = 0,
        y: int = 0,
        z: int = 1,
        server: int = 0
    ) -> str:
        """获取注记图层瓦片 URL

        Args:
            annotation_type: 注记类型 cva=矢量注记, cia=影像注记, cta=地形注记
            projection: 投影类型 c=经纬度投影, w=球面墨卡托投影
            x: 瓦片列号
            y: 瓦片行号
            z: 缩放级别
            server: 服务器编号 (0-7)

        Returns:
            注记瓦片 URL
        """
        if annotation_type not in self.ANNOTATION_LAYERS:
            logger.warning(f"[TiandituProvider] 未知的注记类型: {annotation_type}")

        return (
            f"http://t{server}.tianditu.gov.cn/{annotation_type}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={annotation_type}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
            f"&tk={self.api_key}"
        )

    def get_annotation_template(
        self,
        annotation_type: str = "cva",
        projection: str = "c"
    ) -> str:
        """获取注记图层模板 URL

        Args:
            annotation_type: 注记类型 cva=矢量注记, cia=影像注记, cta=地形注记
            projection: 投影类型 c=经纬度投影, w=球面墨卡托投影

        Returns:
            注记瓦片模板 URL
        """
        return (
            f"http://t{{s}}.tianditu.gov.cn/{annotation_type}_{projection}/wmts"
            f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
            f"&LAYER={annotation_type}&STYLE=default&TILEMATRIXSET={projection}"
            f"&FORMAT=tiles&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}"
            f"&tk={self.api_key}"
        )

    def get_layer_info(self) -> Dict[str, Any]:
        """获取所有可用图层信息

        Returns:
            图层类型和投影类型的说明
        """
        return {
            "base_layers": self.TILE_LAYERS,
            "annotation_layers": self.ANNOTATION_LAYERS,
            "projections": {
                "c": "经纬度投影 (EPSG:4326)",
                "w": "球面墨卡托投影 (EPSG:3857)"
            },
            "zoom_range": {"min": 1, "max": 18},
            "server_range": {"min": 0, "max": 7}
        }


__all__ = ["TiandituProvider", "TiandituResult"]