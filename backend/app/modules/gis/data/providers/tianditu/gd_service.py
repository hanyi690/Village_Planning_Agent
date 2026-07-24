"""广东省天地图专题服务封装

封装广东省天地图专题服务（WMS/WMTS/WFS），用于自动获取
村庄规划约束数据（农田保护、生态红线、地质灾害点等）。

服务地址可通过环境变量 GD_TIANDITU_BASE_URL 配置。
"""
import os
import time
import requests
from typing import Dict, Any, Tuple, Optional

from .types import TiandituResult
from .constants import WFS_URL
from .gd_constants import (
    GD_TIANDITU_BASE_URL,
    GD_SPECIALIZED_SERVICES,
    GD_LAYER_SERVICE_MAP,
    GD_SERVICE_LAYER_MAP,
    CRS_TRANSFORM_MAP,
    GD_WMTS_PARAMS,
    GD_WMS_PARAMS,
)
from ..rate_limiter import RateLimiter
from app.core.settings import (
    TIANDITU_API_KEY,
    TIANDITU_RATE_LIMIT,
    GIS_TIMEOUT,
    GD_TIANDITU_TOKEN,
    GD_TIANDITU_BASE_URL as CONFIG_GD_BASE_URL,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 使用配置文件中的 Token 和 Base URL
GD_TOKEN = GD_TIANDITU_TOKEN or TIANDITU_API_KEY
GD_BASE_URL = CONFIG_GD_BASE_URL or GD_TIANDITU_BASE_URL


class GDSpecializedService:
    """广东省天地图专题服务封装"""

    def __init__(self, gd_token: str = None, base_url: str = None):
        """初始化广东省天地图服务

        Args:
            gd_token: 广东省天地图Token（可选，默认使用配置文件中的Token）
            base_url: 服务基础URL（可选，默认使用配置文件中的URL）
        """
        self.gd_token = gd_token or GD_TOKEN
        self.base_url = base_url or GD_BASE_URL
        self.timeout = GIS_TIMEOUT
        self._rate_limiter = RateLimiter.get_instance("tianditu", TIANDITU_RATE_LIMIT)

        if not self.gd_token:
            logger.warning("[GDSpecializedService] GD_TIANDITU_TOKEN 未配置")

    def get_service_wmts_url(self, service_id: str) -> str:
        """获取服务的 WMTS URL

        Args:
            service_id: 服务ID（如 dom2023, SQSXWPSJ）

        Returns:
            服务独立的 WMTS URL
        """
        return f"{self.base_url}/server/{service_id}/wmts"

    def get_service_wms_url(self, service_id: str) -> str:
        """获取服务的 WMS URL

        Args:
            service_id: 服务ID

        Returns:
            服务独立的 WMS URL
        """
        return f"{self.base_url}/server/{service_id}/wms"

    def get_service_rest_url(self, service_id: str) -> str:
        """获取服务的 REST URL（MapServer）

        Args:
            service_id: 服务ID

        Returns:
            服务独立的 REST URL
        """
        return f"{self.base_url}/server/{service_id}/MapServer"

    def get_service_wfs_url(self, service_id: str) -> str:
        """获取服务的 WFS URL（部分服务支持）

        Args:
            service_id: 服务ID

        Returns:
            服务独立的 WFS URL
        """
        return f"{self.base_url}/server/{service_id}/wfs"

    def _rate_limit_wait(self):
        """使用共享速率限制器等待"""
        self._rate_limiter.wait()

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "VillagePlanningAgent/1.0"
        }

    def get_service_info(self, service_id: str) -> Optional[Dict]:
        """获取服务详细信息

        Args:
            service_id: 服务ID（如 SQSXWPSJ, GDSTBHHX）

        Returns:
            服务配置信息字典
        """
        return GD_SPECIALIZED_SERVICES.get(service_id)

    def get_layer_service_id(self, layer_type: str) -> Optional[str]:
        """根据图层类型获取服务ID

        Args:
            layer_type: 图层类型（如 farmland_protection, ecological_protection）

        Returns:
            服务ID
        """
        return GD_LAYER_SERVICE_MAP.get(layer_type)

    def get_wmts_tile_url(
        self,
        service_id: str,
        x: int,
        y: int,
        z: int,
        tilematrixset: str = "c"
    ) -> str:
        """构建 WMTS 瓦片请求 URL

        Args:
            service_id: 服务ID
            x: 瓦片列号
            y: 瓦片行号
            z: 级别
            tilematrixset: 瓦片矩阵集（c=经纬度, w=墨卡托）

        Returns:
            WMTS 瓦片 URL
        """
        service_info = GD_SPECIALIZED_SERVICES.get(service_id)
        if not service_info:
            logger.warning(f"[GDSpecializedService] 未知服务ID: {service_id}")
            return ""

        # 根据服务坐标系选择 tilematrixset
        epsg = service_info.get("epsg", "EPSG:4326")
        if epsg == "EPSG:3857":
            tilematrixset = "w"

        params = {
            **GD_WMTS_PARAMS,
            "LAYER": service_id,
            "TILEMATRIXSET": tilematrixset,
            "TILEMATRIX": str(z),
            "TILEROW": str(y),
            "TILECOL": str(x),
            "tk": self.gd_token,
        }

        wmts_url = self.get_service_wmts_url(service_id)
        url = f"{wmts_url}?"
        for key, value in params.items():
            url += f"{key}={value}&"
        return url.rstrip("&")

    def get_wms_map_url(
        self,
        service_id: str,
        bbox: Tuple[float, float, float, float],
        width: int = 512,
        height: int = 512,
        srs: str = "EPSG:4326"
    ) -> str:
        """构建 WMS GetMap 请求 URL

        Args:
            service_id: 服务ID
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat)
            width: 图片宽度
            height: 图片高度
            srs: 坐标参考系统

        Returns:
            WMS GetMap URL
        """
        service_info = GD_SPECIALIZED_SERVICES.get(service_id)
        if not service_info:
            logger.warning(f"[GDSpecializedService] 未知服务ID: {service_id}")
            return ""

        # 根据服务坐标系调整 bbox
        source_epsg = service_info.get("epsg", "EPSG:4326")
        transformed_bbox = self._transform_bbox_for_request(bbox, source_epsg)

        # 使用服务配置中的 wms_layer，若未配置则使用 service_id
        wms_layer = service_info.get("wms_layer", service_id)

        params = {
            **GD_WMS_PARAMS,
            "LAYERS": wms_layer,
            "BBOX": f"{transformed_bbox[0]},{transformed_bbox[1]},{transformed_bbox[2]},{transformed_bbox[3]}",
            "WIDTH": str(width),
            "HEIGHT": str(height),
            "SRS": source_epsg,
            "tk": self.gd_token,
        }

        wms_url = self.get_service_wms_url(service_id)
        url = f"{wms_url}?"
        for key, value in params.items():
            url += f"{key}={value}&"
        return url.rstrip("&")

    def fetch_constraint_data(
        self,
        layer_type: str,
        bbox: Tuple[float, float, float, float],
        max_features: int = 1000
    ) -> TiandituResult:
        """获取约束层数据

        优先尝试 WFS，若不支持则使用 WMS GetMap 返回影像。

        Args:
            layer_type: 图层类型（farmland_protection/ecological_protection/
                        three_zones_three_lines/geological_hazard_points）
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat) WGS84坐标
            max_features: 最大要素数量（仅WFS有效）

        Returns:
            TiandituResult 包含 GeoJSON 或影像 URL
        """
        service_id = GD_LAYER_SERVICE_MAP.get(layer_type)
        if not service_id:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"未知的图层类型: {layer_type}"
            )

        service_info = GD_SPECIALIZED_SERVICES.get(service_id)
        protocols = service_info.get("protocols", [])

        # 尝试 WFS 获取（若支持）
        if "WFS" in protocols:
            result = self._fetch_wfs_data(service_id, bbox, max_features)
            if result.success and result.data.get("geojson"):
                # 坐标转换
                geojson = result.data["geojson"]
                source_epsg = service_info.get("epsg", "EPSG:4326")
                transformed_geojson = self._transform_crs(geojson, source_epsg)
                result.data["geojson"] = transformed_geojson
                return result

        # 使用 WMS/WMTS 返回瓦片 URL（无法直接获取要素数据）
        tile_url = self.get_wmts_tile_url(service_id, 0, 0, 10)
        wms_url = self.get_wms_map_url(service_id, bbox)

        return TiandituResult(
            success=True,
            data={
                "wmts_url": tile_url,
                "wms_url": wms_url,
                "service_id": service_id,
                "service_name": service_info.get("name", ""),
                "protocols": protocols,
            },
            metadata={
                "layer_type": layer_type,
                "service_id": service_id,
                "bbox": bbox,
                "source": "gd_tianditu_wms",
                "note": "此服务仅支持瓦片/影像，无法获取要素数据"
            }
        )

    def _fetch_wfs_data(
        self,
        service_id: str,
        bbox: Tuple[float, float, float, float],
        max_features: int = 1000
    ) -> TiandituResult:
        """获取 WFS 图层数据

        Args:
            service_id: 服务ID
            bbox: 边界框（WGS84）
            max_features: 最大要素数量

        Returns:
            TiandituResult with GeoJSON data
        """
        if not self.gd_token:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error="GD_TIANDITU_TOKEN 未配置"
            )

        service_info = GD_SPECIALIZED_SERVICES.get(service_id)
        source_epsg = service_info.get("epsg", "EPSG:4326")
        transformed_bbox = self._transform_bbox_for_request(bbox, source_epsg)

        wfs_url = self.get_service_wfs_url(service_id)
        url = (
            f"{wfs_url}?SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature"
            f"&TYPENAME={service_id}&MAXFEATURES={max_features}"
            f"&BBOX={transformed_bbox[0]},{transformed_bbox[1]},{transformed_bbox[2]},{transformed_bbox[3]}"
            f"&OUTPUTFORMAT=application/json&tk={self.gd_token}"
        )

        self._rate_limit_wait()

        try:
            resp = requests.get(url, headers=self._get_headers(), timeout=self.timeout)

            if resp.status_code == 401:
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={"status_code": 401},
                    error="认证失败，请检查 GD_TIANDITU_TOKEN 配置"
                )

            if resp.status_code != 200:
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={"status_code": resp.status_code},
                    error=f"WFS HTTP {resp.status_code}"
                )

            # 解析 JSON
            try:
                geojson = resp.json()
            except ValueError:
                # 非 JSON 响应
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={"response_preview": resp.text[:200]},
                    error="WFS 返回非 JSON 格式"
                )

            features = geojson.get("features", [])

            return TiandituResult(
                success=True,
                data={"geojson": geojson},
                metadata={
                    "service_id": service_id,
                    "service_name": service_info.get("name", ""),
                    "feature_count": len(features),
                    "bbox": bbox,
                    "source": "gd_tianditu_wfs",
                }
            )

        except requests.Timeout:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error="WFS 请求超时"
            )

        except Exception as e:
            logger.error(f"[GDSpecializedService] WFS 请求异常: {e}")
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=str(e)
            )

    def _transform_bbox_for_request(
        self,
        bbox: Tuple[float, float, float, float],
        target_epsg: str
    ) -> Tuple[float, float, float, float]:
        """将 WGS84 bbox 转换为目标坐标系

        CGCS2000 (EPSG:4490) 与 WGS-84 (EPSG:4326) 使用相同的 GRS80 椭球参数
        (长半轴 6378137.0m, 扁率倒数 298.257222101)，两者之间的 Helmert 变换
        残差小于 1 米，在村级规划（公顷级精度）下可视为等价（偏差 < 0.01%）
        GB/T 21010-2017 强制使用 CGCS2000，而 GeoJSON RFC 7946 要求 WGS-84
        因此代码不执行显式转换，直接存储为 WGS84 格式

        Args:
            bbox: WGS84 边界框 (min_lon, min_lat, max_lon, max_lat)
            target_epsg: 目标坐标系 EPSG 代码

        Returns:
            转换后的 bbox
        """
        # CGCS2000 地理坐标(EPSG:4490) 与 WGS84(EPSG:4326) 兼容，无需转换
        if target_epsg in ("EPSG:4490", "EPSG:4326"):
            return bbox

        # Web墨卡托转换
        if target_epsg == "EPSG:3857":
            try:
                import pyproj
                transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
                min_x, min_y = transformer.transform(bbox[0], bbox[1])
                max_x, max_y = transformer.transform(bbox[2], bbox[3])
                return (min_x, min_y, max_x, max_y)
            except ImportError:
                logger.warning("[GDSpecializedService] pyproj 未安装，无法转换墨卡托坐标")
                return bbox

        # CGCS2000投影坐标系 与 WGS84 兼容，无需转换
        return bbox

    def _transform_crs(
        self,
        geojson: Dict[str, Any],
        source_epsg: str
    ) -> Dict[str, Any]:
        """坐标系转换: CGCS2000/Web墨卡托 -> WGS84

        CGCS2000 (EPSG:4490) 与 WGS-84 (EPSG:4326) 使用相同的 GRS80 椭球参数
        (长半轴 6378137.0m, 扁率倒数 298.257222101)，两者之间的 Helmert 变换
        残差小于 1 米，在村级规划（公顷级精度）下可视为等价（偏差 < 0.01%）
        GB/T 21010-2017 强制使用 CGCS2000，而 GeoJSON RFC 7946 要求 WGS-84
        因此代码不执行显式转换，直接存储为 WGS84 格式

        Args:
            geojson: 源 GeoJSON 数据
            source_epsg: 源坐标系 EPSG 代码

        Returns:
            转换后的 GeoJSON（WGS84）
        """
        if source_epsg in ("EPSG:4326", "EPSG:4490"):
            return geojson

        # CGCS2000投影坐标系 (EPSG:45xx) 与 WGS84 在精度要求不高时可视为兼容
        if source_epsg.startswith("EPSG:45"):  # CGCS2000 投影系列
            logger.info(f"[GDSpecializedService] CGCS2000({source_epsg}) 视为兼容 WGS84")
            return geojson

        # Web墨卡托转换
        if source_epsg == "EPSG:3857":
            try:
                import geopandas as gpd
                gdf = gpd.GeoDataFrame.from_features(geojson.get("features", []))
                gdf.set_crs(source_epsg, inplace=True)
                gdf = gdf.to_crs("EPSG:4326")
                return gdf.__geo_interface__
            except ImportError:
                logger.warning("[GDSpecializedService] geopandas 未安装，无法转换墨卡托坐标")
                return geojson
            except Exception as e:
                logger.error(f"[GDSpecializedService] 坐标转换失败: {e}")
                return geojson

        return geojson

    def check_service_availability(self, service_id: str) -> TiandituResult:
        """检查服务可用性

        Args:
            service_id: 服务ID

        Returns:
            TiandituResult 包含服务状态信息
        """
        service_info = GD_SPECIALIZED_SERVICES.get(service_id)
        if not service_info:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"未知服务ID: {service_id}"
            )

        # 使用服务独立路径获取 GetCapabilities
        wmts_url = self.get_service_wmts_url(service_id)
        capabilities_url = f"{wmts_url}?SERVICE=WMTS&VERSION=1.0.0&REQUEST=GetCapabilities&tk={self.gd_token}"

        self._rate_limit_wait()

        try:
            resp = requests.get(capabilities_url, headers=self._get_headers(), timeout=self.timeout)

            if resp.status_code == 200:
                return TiandituResult(
                    success=True,
                    data={"status": "available"},
                    metadata={
                        "service_id": service_id,
                        "service_name": service_info.get("name", ""),
                        "status_code": resp.status_code,
                        "source": "gd_tianditu_check",
                    }
                )

            return TiandituResult(
                success=False,
                data={},
                metadata={
                    "service_id": service_id,
                    "status_code": resp.status_code,
                },
                error=f"服务不可用: HTTP {resp.status_code}"
            )

        except Exception as e:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=str(e)
            )

    def get_all_services_info(self) -> Dict[str, Dict]:
        """获取所有可用服务信息"""
        return GD_SPECIALIZED_SERVICES

    def query_mapserver_layer(
        self,
        service_id: str,
        layer_id: int,
        bbox: Tuple[float, float, float, float],
        where: str = "1=1",
        out_fields: str = "*",
        max_features: int = 1000,
    ) -> TiandituResult:
        """通过 MapServer REST API 查询图层矢量数据

        基于 ArcGIS REST API 规范，直接获取 GeoJSON 格式的矢量要素。
        这就是 ArcMap/QGIS "导出要素" 功能的 Python 实现。

        Args:
            service_id: 服务ID（如 "SQSXWPSJ"）
            layer_id: 图层ID（如 0, 1, 2）
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat) WGS84
            where: SQL WHERE 条件，默认 "1=1" 返回所有
            out_fields: 返回字段，默认 "*" 返回所有
            max_features: 最大要素数量（部分服务可能忽略此参数）

        Returns:
            TiandituResult with GeoJSON data
        """
        if not self.gd_token:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error="GD_TIANDITU_TOKEN 未配置"
            )

        service_info = GD_SPECIALIZED_SERVICES.get(service_id)
        if not service_info:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=f"未知服务ID: {service_id}"
            )

        # 构建查询 URL
        query_url = f"{self.base_url}/server/{service_id}/MapServer/{layer_id}/query"

        # 获取服务坐标系
        source_epsg = service_info.get("epsg", "EPSG:4326")
        in_sr = "4326"  # 输入坐标系 WGS84
        out_sr = "4326"  # 输出坐标系 WGS84
        if source_epsg == "EPSG:4490":
            in_sr = "4490"  # CGCS2000
            out_sr = "4490"
        elif source_epsg == "EPSG:3857":
            out_sr = "3857"  # Web墨卡托

        # 天地图 GeoGlobe 平台的 Query 参数
        # 参考: https://bingtuan.tianditu.gov.cn/docApi/pages/apiHtml/MapService.html
        params = {
            "geometry": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": in_sr,
            "outSR": out_sr,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields,
            "returnGeometry": "true",
            "f": "json",  # 先用 ESRI JSON 格式，更兼容
            "tk": self.gd_token,
        }

        # 添加 where 条件（某些服务需要）
        if where != "1=1":
            params["where"] = where

        self._rate_limit_wait()

        try:
            resp = requests.get(
                query_url,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout
            )

            if resp.status_code == 401:
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={"status_code": 401},
                    error="认证失败，请检查 GD_TIANDITU_TOKEN 配置"
                )

            if resp.status_code != 200:
                # 尝试解析错误响应
                error_detail = ""
                try:
                    error_json = resp.json()
                    if "error" in error_json:
                        error_detail = f": {error_json['error'].get('message', '')}"
                    else:
                        error_detail = f": {str(error_json)[:200]}"
                except ValueError:
                    error_detail = f": {resp.text[:200]}"
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={"status_code": resp.status_code, "response": resp.text[:500]},
                    error=f"MapServer Query HTTP {resp.status_code}{error_detail}"
                )

            # 解析响应
            try:
                response_json = resp.json()
            except ValueError:
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={"response_preview": resp.text[:200]},
                    error="MapServer 返回非 JSON 格式"
                )

            # 检查是否是错误响应
            if "error" in response_json:
                error_msg = response_json.get("error", {}).get("message", "未知错误")
                return TiandituResult(
                    success=False,
                    data={},
                    metadata={"error_code": response_json.get("error", {}).get("code")},
                    error=f"MapServer 错误: {error_msg}"
                )

            # 处理 ESRI JSON 格式 -> GeoJSON
            # ESRI JSON 格式: {features: [{attributes: {...}, geometry: {x, y} or {rings: [...]}}]}
            geojson = None
            if "features" in response_json and "type" not in response_json:
                # 这是 ESRI JSON 格式，需要转换
                geojson = self._esri_json_to_geojson(response_json)
            else:
                # 已经是 GeoJSON 格式
                geojson = response_json

            features = geojson.get("features", []) if geojson else []

            return TiandituResult(
                success=True,
                data={"geojson": geojson},
                metadata={
                    "service_id": service_id,
                    "layer_id": layer_id,
                    "layer_name": service_info.get("name", ""),
                    "feature_count": len(features),
                    "bbox": bbox,
                    "source": "gd_mapserver_query",
                }
            )

        except requests.Timeout:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error="MapServer Query 请求超时"
            )

        except Exception as e:
            logger.error(f"[GDSpecializedService] MapServer Query 异常: {e}")
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=str(e)
            )

    def _esri_json_to_geojson(self, esri_json: Dict[str, Any]) -> Dict[str, Any]:
        """将 ESRI JSON 格式转换为 GeoJSON 格式

        ESRI JSON 格式:
            {
                "features": [{
                    "attributes": {...},
                    "geometry": {"x": ..., "y": ...} or {"rings": [[[x,y], ...]]}
                }],
                "geometryType": "esriGeometryPoint" | "esriGeometryPolyline" | "esriGeometryPolygon"
            }

        Args:
            esri_json: ESRI JSON 格式的响应

        Returns:
            标准 GeoJSON FeatureCollection
        """
        features = []
        esri_features = esri_json.get("features", [])
        geometry_type = esri_json.get("geometryType", "")

        for esri_feat in esri_features:
            attributes = esri_feat.get("attributes", {})
            esri_geom = esri_feat.get("geometry")

            if not esri_geom:
                continue

            # 转换几何
            geojson_geom = None

            # 点
            if "x" in esri_geom and "y" in esri_geom:
                geojson_geom = {
                    "type": "Point",
                    "coordinates": [esri_geom["x"], esri_geom["y"]]
                }
            # 线
            elif "paths" in esri_geom:
                paths = esri_geom["paths"]
                if len(paths) == 1:
                    geojson_geom = {
                        "type": "LineString",
                        "coordinates": paths[0]
                    }
                else:
                    geojson_geom = {
                        "type": "MultiLineString",
                        "coordinates": paths
                    }
            # 面
            elif "rings" in esri_geom:
                rings = esri_geom["rings"]
                if len(rings) == 1:
                    geojson_geom = {
                        "type": "Polygon",
                        "coordinates": rings
                    }
                else:
                    # 多面或带洞的多边形
                    # ESRI rings: 外环逆时针，内环顺时针
                    # GeoJSON: 外环 + 洞
                    geojson_geom = {
                        "type": "Polygon",
                        "coordinates": rings
                    }

            if geojson_geom:
                features.append({
                    "type": "Feature",
                    "properties": attributes,
                    "geometry": geojson_geom
                })

        return {
            "type": "FeatureCollection",
            "features": features
        }


__all__ = ["GDSpecializedService", "GD_TOKEN", "GD_BASE_URL"]