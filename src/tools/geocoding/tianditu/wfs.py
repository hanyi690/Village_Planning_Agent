"""天地图 WFS 服务"""
import time
import requests
from typing import Dict, Any, Tuple

from .types import TiandituResult
from .constants import WFS_URL, WFS_LAYERS
from ....core.config import (
    TIANDITU_API_KEY,
    TIANDITU_RATE_LIMIT,
    GIS_TIMEOUT
)
from ....utils.logger import get_logger

logger = get_logger(__name__)


class WfsService:
    """WFS 服务封装"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.rate_limit = TIANDITU_RATE_LIMIT
        self.timeout = GIS_TIMEOUT
        self._last_request_time = 0

    def _rate_limit_wait(self):
        """速率限制等待"""
        if self.rate_limit <= 0:
            return
        min_interval = 1.0 / self.rate_limit
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

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
            layer_type: 图层类型 (LRRL/LRDL/HYDA/HYDL/HYDP/RESA/RESP)
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

            # 尝试解析 JSON，若失败则返回空 GeoJSON
            try:
                geojson = resp.json()
            except ValueError:
                # 空响应或非 JSON 格式，返回空要素
                logger.warning(f"[WfsService] {layer_type} 返回非 JSON 响应，视为空数据")
                geojson = {"type": "FeatureCollection", "features": []}

            features = geojson.get("features", [])

            return TiandituResult(
                success=True,
                data={"geojson": geojson},
                metadata={
                    "layer": layer_type,
                    "layer_name": WFS_LAYERS.get(layer_type, layer_type),
                    "feature_count": len(features),
                    "bbox": bbox,
                    "source": "tianditu_wfs"
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
            result = self.get_wfs_data("HYDA", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "HYDA",
                    "name": "水系面",
                    "count": len(features)
                })

        if include_lines:
            result = self.get_wfs_data("HYDL", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "HYDL",
                    "name": "水系线",
                    "count": len(features)
                })

        if include_points:
            result = self.get_wfs_data("HYDP", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "HYDP",
                    "name": "水系点",
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
            result = self.get_wfs_data("LRRL", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "LRRL",
                    "name": "铁路",
                    "count": len(features)
                })

        if include_roads:
            result = self.get_wfs_data("LRDL", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "LRDL",
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
            result = self.get_wfs_data("RESA", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "RESA",
                    "name": "居民地面",
                    "count": len(features)
                })

        if include_points:
            result = self.get_wfs_data("RESP", bbox, max_features)
            if result.success:
                features = result.data.get("geojson", {}).get("features", [])
                all_features.extend(features)
                metadata["layers"].append({
                    "type": "RESP",
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