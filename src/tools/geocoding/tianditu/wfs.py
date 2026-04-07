"""天地图 WFS 服务"""
import time
import requests
from typing import Dict, Any, Tuple

from .types import TiandituResult
from .constants import WFS_URL, WFS_LAYERS
from ..rate_limiter import RateLimiter
from ....core.config import (
    TIANDITU_API_KEY,
    TIANDITU_RATE_LIMIT,
    GIS_TIMEOUT
)
from ....utils.logger import get_logger

logger = get_logger(__name__)


class WfsService:
    """WFS 服务封装"""

    def __init__(self, api_key: str, rate_limiter: RateLimiter = None):
        """初始化 WFS 服务

        Args:
            api_key: 天地图 API Key
            rate_limiter: 外部传入的速率限制器（共享天地图限制器）
        """
        self.api_key = api_key
        self.timeout = GIS_TIMEOUT
        # 使用传入的限制器或获取全局天地图限制器
        if rate_limiter:
            self._rate_limiter = rate_limiter
        else:
            self._rate_limiter = RateLimiter.get_instance("tianditu", TIANDITU_RATE_LIMIT)

    def _rate_limit_wait(self):
        """使用共享速率限制器等待"""
        self._rate_limiter.wait()

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0"
        }

    def get_wfs_data(
        self,
        layer_type: str,
        bbox: Tuple[float, float, float, float],
        max_features: int = 1000
    ) -> TiandituResult:
        """获取 WFS 图层数据

        Args:
            layer_type: 图层类型 (TDTService:LRRL/TDTService:LRDL/TDTService:HYDA/TDTService:HYDL/TDTService:RESA/TDTService:RESP)
            bbox: 边界框 (min_lon, min_lat, max_lon, max_lat)
            max_features: 最大要素数量

        Returns:
            TiandituResult with GeoJSON data
        """
        if not self.api_key:
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error="TIANDITU_API_KEY 未配置"
            )

        # 验证图层类型
        if layer_type not in WFS_LAYERS:
            logger.warning(f"[WfsService] 未知的图层类型: {layer_type}, 可用: {list(WFS_LAYERS.keys())}")

        url = (
            f"{WFS_URL}?SERVICE=WFS&VERSION=1.0.0&REQUEST=GetFeature"
            f"&TYPENAME={layer_type}&MAXFEATURES={max_features}"
            f"&BBOX={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            f"&OUTPUTFORMAT=application/json&tk={self.api_key}"
        )

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

            # 尝试解析 JSON，若失败则记录实际响应内容
            try:
                geojson = resp.json()
                response_type = "json"
                response_preview = None
            except ValueError:
                # 检查是否是 OGC ServiceExceptionReport
                response_text = resp.text
                if "<?xml" in response_text and "ServiceExceptionReport" in response_text:
                    import xml.etree.ElementTree as ET
                    try:
                        root = ET.fromstring(response_text)
                        ns = {"ogc": "http://www.opengis.net/ogc"}
                        exc_elem = root.find(".//ogc:ServiceException", ns) or root.find("ServiceException")
                        error_code = exc_elem.get("code", "NoApplicableCode") if exc_elem else "Unknown"
                        error_msg = (exc_elem.text or "").strip() if exc_elem else "WFS 服务错误"

                        logger.warning(f"[WfsService] {layer_type} ServiceException: [{error_code}] {error_msg}")
                        return TiandituResult(
                            success=False,
                            data={},
                            metadata={
                                "layer": layer_type,
                                "error_code": error_code,
                                "response_type": "service_exception"
                            },
                            error=f"WFS [{error_code}]: {error_msg}"
                        )
                    except ET.ParseError:
                        logger.warning(f"[WfsService] {layer_type} XML 解析失败")
                # 其他非 JSON 响应
                response_preview = response_text[:200] if response_text else "(empty)"
                logger.warning(f"[WfsService] {layer_type} 非预期响应: {response_preview}")
                geojson = {"type": "FeatureCollection", "features": []}
                response_type = "non_json_fallback"

            features = geojson.get("features", [])

            return TiandituResult(
                success=True,
                data={"geojson": geojson},
                metadata={
                    "layer": layer_type,
                    "layer_name": WFS_LAYERS.get(layer_type, layer_type),
                    "feature_count": len(features),
                    "bbox": bbox,
                    "source": "tianditu_wfs",
                    # 增强: 标记响应类型，便于诊断
                    "response_type": response_type,
                    **({"response_preview": response_preview} if response_preview else {})
                }
            )

        except Exception as e:
            logger.error(f"[WfsService] WFS 请求异常: {e}")
            return TiandituResult(
                success=False,
                data={},
                metadata={},
                error=str(e)
            )

    def get_water_features(
        self,
        bbox: Tuple[float, float, float, float],
        include_lines: bool = True,
        include_areas: bool = True,
        include_points: bool = False,
        max_features: int = 500
    ) -> TiandituResult:
        """获取水系要素

        Args:
            bbox: 边界框
            include_lines: 是否包含水系线 (HYDL)
            include_areas: 是否包含水系面 (HYDA)
            include_points: 是否包含水系点 (HYDP)
            max_features: 每类最大要素数量

        Returns:
            合并的水系要素 GeoJSON
        """
        all_features = []
        metadata = {"layers": [], "total_count": 0, "bbox": bbox}

        if include_areas:
            result = self.get_wfs_data("TDTService:HYDA", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "TDTService:HYDA",
                    "name": "水系面",
                    "count": len(features)
                })

        if include_lines:
            result = self.get_wfs_data("TDTService:HYDL", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "TDTService:HYDL",
                    "name": "水系线",
                    "count": len(features)
                })

        # 注意：HYDP（水系点）不存在于天地图 WFS 服务中
        # include_points 参数保留但无实际效果

        metadata["total_count"] = len(all_features)

        geojson = {
            "type": "FeatureCollection",
            "features": all_features
        }

        return TiandituResult(
            success=True,
            data={"geojson": geojson},
            metadata=metadata
        )

    def get_road_features(
        self,
        bbox: Tuple[float, float, float, float],
        include_railways: bool = True,
        include_roads: bool = True,
        max_features: int = 500
    ) -> TiandituResult:
        """获取道路要素

        Args:
            bbox: 边界框
            include_railways: 是否包含铁路 (LRRL)
            include_roads: 是否包含公路 (LRDL)
            max_features: 每类最大要素数量

        Returns:
            合并的道路要素 GeoJSON
        """
        all_features = []
        metadata = {"layers": [], "total_count": 0, "bbox": bbox}

        if include_railways:
            result = self.get_wfs_data("TDTService:LRRL", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "TDTService:LRRL",
                    "name": "铁路",
                    "count": len(features)
                })

        if include_roads:
            result = self.get_wfs_data("TDTService:LRDL", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "TDTService:LRDL",
                    "name": "公路",
                    "count": len(features)
                })

        metadata["total_count"] = len(all_features)

        geojson = {
            "type": "FeatureCollection",
            "features": all_features
        }

        return TiandituResult(
            success=True,
            data={"geojson": geojson},
            metadata=metadata
        )

    def get_residential_features(
        self,
        bbox: Tuple[float, float, float, float],
        include_areas: bool = True,
        include_points: bool = True,
        max_features: int = 500
    ) -> TiandituResult:
        """获取居民地要素

        Args:
            bbox: 边界框
            include_areas: 是否包含居民地面 (RESA)
            include_points: 是否包含居民地点 (RESP)
            max_features: 每类最大要素数量

        Returns:
            合并的居民地要素 GeoJSON
        """
        all_features = []
        metadata = {"layers": [], "total_count": 0, "bbox": bbox}

        if include_areas:
            result = self.get_wfs_data("TDTService:RESA", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "TDTService:RESA",
                    "name": "居民地面",
                    "count": len(features)
                })

        if include_points:
            result = self.get_wfs_data("TDTService:RESP", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "TDTService:RESP",
                    "name": "居民地点",
                    "count": len(features)
                })

        metadata["total_count"] = len(all_features)

        geojson = {
            "type": "FeatureCollection",
            "features": all_features
        }

        return TiandituResult(
            success=True,
            data={"geojson": geojson},
            metadata=metadata
        )

    def get_available_layers(self) -> Dict[str, str]:
        """获取所有可用的 WFS 图层"""
        return WFS_LAYERS


__all__ = ["WfsService", "WFS_LAYERS"]