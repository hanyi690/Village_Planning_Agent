"""AMap 外源锚点服务 — 行政村村委会 + 设施 + 道路名 + 水库名

依赖已有 AmapProvider, 调用:
  - search_poi_nearby("村", center, radius) → 行政村村委会
  - search_poi_by_types("141200|090100|150700", center, radius) → 设施
  - search_poi_by_types("190000", center, radius) → 道路交叉口名
  - search_poi_nearby("水库", center, radius) → 水库
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.data.ingestion.providers.amap.provider import AmapProvider
from app.data.catalog.dedup import SimpleCache
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 设施 typecode (学校/医院/公交/政府)
FACILITY_TYPECODES: List[str] = ["141200", "090100", "150700", "130106"]

# 道路名 typecode (190000 大类)
ROAD_NAMED_TYPECODES: List[str] = ["190000"]

# 关键词 (兜底)
WATER_KEYWORDS: List[str] = ["水库", "河"]


class AmapAnchorService:
    """AMap 外源 POI 锚点拉取与转换."""

    def __init__(self, amap: Optional[AmapProvider] = None,
                 cache_ttl_s: float = 3600.0):
        self._amap = amap or AmapProvider()
        self._cache = SimpleCache(cache_ttl_s)

    # ==================== Public API ====================

    def fetch_all(
        self,
        center: Tuple[float, float],
        radius_m: int = 8000,
        county_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """并发拉取 4 类数据.

        Returns:
          {
            "village_committees": [poi dicts],
            "facilities": [poi dicts],
            "roads_named": [poi dicts],
            "water_named": [poi dicts],
            "errors": [...],
            "source": "amap_poi",
          }
        """
        cache_key = ("amap_anchors", round(center[0], 3), round(center[1], 3),
                     radius_m)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result: Dict[str, Any] = {
            "village_committees": [],
            "facilities": [],
            "roads_named": [],
            "water_named": [],
            "errors": [],
            "source": "amap_poi",
        }

        # A. 行政村村委会 (搜 "村" 关键词)
        try:
            r = self._amap.search_poi_nearby(
                "村", center, radius_m, page_size=25,
            )
            if r.success:
                result["village_committees"] = r.data.get("pois", [])
            else:
                result["errors"].append(f"village_committee: {r.error}")
        except Exception as e:
            result["errors"].append(f"village_committee: {e}")

        # B. 设施 typecode 扫描
        for tc in FACILITY_TYPECODES:
            try:
                r = self._amap.search_poi_by_types(
                    tc, center, radius_m, page_size=25,
                )
                if r.success:
                    result["facilities"].extend(r.data.get("pois", []))
                else:
                    result["errors"].append(f"facility_{tc}: {r.error}")
            except Exception as e:
                result["errors"].append(f"facility_{tc}: {e}")

        # C. 道路名 (190000 大类)
        for tc in ROAD_NAMED_TYPECODES:
            try:
                r = self._amap.search_poi_by_types(
                    tc, center, radius_m, page_size=25,
                )
                if r.success:
                    result["roads_named"].extend(r.data.get("pois", []))
                else:
                    result["errors"].append(f"roads_{tc}: {r.error}")
            except Exception as e:
                result["errors"].append(f"roads_{tc}: {e}")

        # D. 水体 (水库/河)
        for kw in WATER_KEYWORDS:
            try:
                r = self._amap.search_poi_nearby(
                    kw, center, radius_m, page_size=25,
                )
                if r.success:
                    result["water_named"].extend(r.data.get("pois", []))
                else:
                    result["errors"].append(f"water_{kw}: {r.error}")
            except Exception as e:
                result["errors"].append(f"water_{kw}: {e}")

        self._cache.set(cache_key, result)
        logger.info(
            f"[AmapAnchorService] fetched: villages={len(result['village_committees'])} "
            f"facilities={len(result['facilities'])} "
            f"roads={len(result['roads_named'])} "
            f"water={len(result['water_named'])} "
            f"errors={len(result['errors'])}"
        )
        return result


__all__ = ["AmapAnchorService", "FACILITY_TYPECODES",
           "ROAD_NAMED_TYPECODES", "WATER_KEYWORDS"]