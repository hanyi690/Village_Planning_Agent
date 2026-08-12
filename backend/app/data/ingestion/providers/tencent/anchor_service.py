"""腾讯地图外源锚点服务 — 行政村 + 设施 + 道路 + 水体

依赖 TencentMapProvider.search_region/search_nearby.
输出与 AmapAnchorService 同结构的 4 类数据.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.data.ingestion.providers.tencent.provider import TencentMapProvider
from app.data.catalog.dedup import SimpleCache
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# 设施搜索关键字 (与高德类型码对齐)
FACILITY_KEYWORDS: List[str] = ["学校", "医院", "公交站", "村委会"]
# 道路名
ROAD_KEYWORDS: List[str] = ["路", "公路", "街道"]
# 水体
WATER_KEYWORDS: List[str] = ["水库", "河"]

# 行政村 (搜 "村")
VILLAGE_KEYWORD = "村"


class TencentAnchorService:
    """腾讯地图外源 POI 锚点拉取与转换."""

    def __init__(self, provider: Optional[TencentMapProvider] = None,
                 cache_ttl_s: float = 3600.0):
        self._provider = provider or TencentMapProvider()
        self._cache = SimpleCache(cache_ttl_s)

    def fetch_all(
        self,
        center: Tuple[float, float],
        region: str,
        radius_m: int = 1000,  # 腾讯 nearby 上限
    ) -> Dict[str, Any]:
        """并发拉取 4 类数据.

        Args:
            center: (lon, lat) WGS84
            region: 行政区名 (例: "梅州市平远县") 或 adcode
            radius_m: 周边搜索半径 (200-1000)

        Returns:
          {
            "village_committees": [poi dicts],
            "facilities": [poi dicts],
            "roads_named": [poi dicts],
            "water_named": [poi dicts],
            "errors": [...],
            "source": "tencent_map",
          }
        """
        cache_key = ("tencent_anchors", round(center[0], 3), round(center[1], 3),
                     radius_m, region)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result: Dict[str, Any] = {
            "village_committees": [],
            "facilities": [],
            "roads_named": [],
            "water_named": [],
            "errors": [],
            "source": "tencent_map",
        }

        # A. 行政村村委会 (region 搜 "村")
        r = self._provider.search_region(
            keyword=VILLAGE_KEYWORD, region=region,
            page_size=20, coord_type="wgs84",
        )
        if r.success:
            result["village_committees"] = r.data.get("pois", [])
        else:
            result["errors"].append(f"village_committee: {r.error}")

        # B. 设施 (周边 search_nearby, radius 上限 1000)
        for kw in FACILITY_KEYWORDS:
            r = self._provider.search_nearby(
                keyword=kw, center=center, radius_m=radius_m,
                page_size=20, coord_type="wgs84",
            )
            if r.success:
                result["facilities"].extend(r.data.get("pois", []))
            else:
                result["errors"].append(f"facility_{kw}: {r.error}")

        # C. 道路名
        for kw in ROAD_KEYWORDS:
            r = self._provider.search_nearby(
                keyword=kw, center=center, radius_m=radius_m,
                page_size=20, coord_type="wgs84",
            )
            if r.success:
                result["roads_named"].extend(r.data.get("pois", []))
            else:
                result["errors"].append(f"road_{kw}: {r.error}")

        # D. 水体
        for kw in WATER_KEYWORDS:
            r = self._provider.search_nearby(
                keyword=kw, center=center, radius_m=radius_m,
                page_size=20, coord_type="wgs84",
            )
            if r.success:
                result["water_named"].extend(r.data.get("pois", []))
            else:
                result["errors"].append(f"water_{kw}: {r.error}")

        self._cache.set(cache_key, result)
        logger.info(
            f"[TencentAnchorService] fetched: villages={len(result['village_committees'])} "
            f"facilities={len(result['facilities'])} "
            f"roads={len(result['roads_named'])} "
            f"water={len(result['water_named'])} "
            f"errors={len(result['errors'])}"
        )
        return result


__all__ = ["TencentAnchorService", "FACILITY_KEYWORDS",
           "ROAD_KEYWORDS", "WATER_KEYWORDS", "VILLAGE_KEYWORD"]