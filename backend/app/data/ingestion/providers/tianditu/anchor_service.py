"""天地图 WFS 锚点服务 — 国家级矢量数据注入

依赖已有 WfsService, 拉取:
  - HYDA (水系面): 水库/湖泊 Polygon
  - HYDL (水系线): 河流 LineString
  - LRDL (公路): LineString
  - LRRL (铁路): LineString (本地无铁路, 默认跳过)

数据特点:
  - 1:100万地形图比例尺 (国家级矢量)
  - 含 NAME 字段 (水库名/河流名/公路名)
  - RESP/RESA 在村级尺度无数据, 跳过
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.data.ingestion.providers.tianditu.wfs import WfsService
from app.data.catalog.dedup import SimpleCache
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 默认拉取的 WFS layer (按需扩展)
DEFAULT_LAYERS: List[Tuple[str, str, str]] = [
    # (layer_name, 中文名, 几何类型)
    ("TDTService:HYDA", "水系面", "Polygon"),
    ("TDTService:HYDL", "水系线", "LineString"),
    ("TDTService:LRDL", "公路", "LineString"),
    # RESP/RESA/LRRL 在该尺度无村级数据, 默认跳过
]


class TiandituWfsAnchorService:
    """天地图 WFS 锚点拉取与转换."""

    def __init__(self, wfs: Optional[WfsService] = None,
                 max_features: int = 500,
                 cache_ttl_s: float = 3600.0):
        self._wfs = wfs or WfsService(api_key="")
        self._max_features = max_features
        self._cache = SimpleCache(cache_ttl_s)

    def _get_wfs(self) -> WfsService:
        if not self._wfs.api_key:
            from app.data.ingestion.providers.tianditu.wfs import WfsService
            from app.core.settings import TIANDITU_API_KEY
            self._wfs = WfsService(api_key=TIANDITU_API_KEY)
        return self._wfs

    # ==================== Public API ====================

    def fetch_all(
        self,
        bbox: Tuple[float, float, float, float],
        layers: Optional[List[Tuple[str, str, str]]] = None,
    ) -> Dict[str, Any]:
        """拉取多个 WFS layer, 返回 GeoJSON features.

        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat)
            layers: 自定义 layer 列表; None 用默认

        Returns:
          {
            "water_bodies": [features],  # HYDA
            "water_lines": [features],   # HYDL
            "roads": [features],         # LRDL
            "errors": [...],
            "source": "tianditu_wfs",
          }
        """
        bbox_key = (round(bbox[0], 2), round(bbox[1], 2),
                    round(bbox[2], 2), round(bbox[3], 2))
        cache_key = ("tianditu_wfs", bbox_key)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        wfs = self._get_wfs()
        target_layers = layers or DEFAULT_LAYERS

        result: Dict[str, Any] = {
            "water_bodies": [],
            "water_lines": [],
            "roads": [],
            "errors": [],
            "source": "tianditu_wfs",
        }

        # layer → result key 映射
        layer_to_key = {
            "TDTService:HYDA": "water_bodies",
            "TDTService:HYDL": "water_lines",
            "TDTService:LRDL": "roads",
            "TDTService:LRRL": "railways",
        }

        for layer_name, label, geom_type in target_layers:
            try:
                r = wfs.get_wfs_data(layer_name, bbox, self._max_features)
            except Exception as e:
                result["errors"].append(f"{layer_name}: {e}")
                continue

            if not r.success:
                result["errors"].append(f"{layer_name}: {r.error}")
                continue

            geojson = r.data.get("geojson", {})
            features = geojson.get("features", [])
            key = layer_to_key.get(layer_name)
            if key:
                result[key].extend(features)
            else:
                # 未知 layer → 放到 generic
                result.setdefault(layer_name, []).extend(features)

            logger.info(
                f"[TiandituWfsAnchorService] {layer_name}: "
                f"{len(features)} features"
            )

        self._cache.set(cache_key, result)
        return result


__all__ = ["TiandituWfsAnchorService", "DEFAULT_LAYERS"]