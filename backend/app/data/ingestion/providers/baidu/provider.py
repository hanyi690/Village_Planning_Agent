"""百度地图核心 API 封装

坐标系说明:
    - 百度默认 bd09ll (百度坐标系)
    - 通过 coord_type=1 强制返回 WGS84, 避免后续 GCJ02 转换
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .constants import (
    REGION_V3_URL,
    SEARCH_V2_URL,
    SUGGESTION_URL,
    EVENTSEARCH_URL,
    DETAIL_URL,
    COORD_TYPE_WGS84,
    DEFAULT_PAGE_SIZE,
    OUTPUT_JSON,
)
from .types import BaiduResult

from app.data.ingestion.connections import RateLimiter
from app.core.settings import (
    BAIDU_API_KEY,
    BAIDU_RATE_LIMIT,
    BAIDU_MAX_RETRIES,
    GIS_TIMEOUT,
)
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BaiduProvider:
    """百度地图 API 封装"""

    def __init__(self):
        self.api_key = BAIDU_API_KEY
        self.rate_limit = BAIDU_RATE_LIMIT
        self.max_retries = BAIDU_MAX_RETRIES
        self.timeout = GIS_TIMEOUT

        self._rate_limiter = RateLimiter.get_instance("baidu", self.rate_limit)

        if not self.api_key:
            logger.warning("[BaiduProvider] BAIDU_API_KEY 未配置")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0",
        }

    def _rate_limit_wait(self):
        self._rate_limiter.wait()

    def _request(self, url: str, params: Dict[str, Any]) -> BaiduResult:
        if not self.api_key:
            return BaiduResult(
                success=False, data={}, metadata={},
                error="BAIDU_API_KEY 未配置",
            )

        params["ak"] = self.api_key
        params["output"] = OUTPUT_JSON

        for attempt in range(self.max_retries):
            self._rate_limit_wait()

            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                )

                if resp.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"[BaiduProvider] 429 速率限制，等待 {wait_time}s")
                    time.sleep(wait_time)
                    continue

                if resp.status_code >= 500:
                    wait_time = 2 ** attempt
                    logger.warning(f"[BaiduProvider] {resp.status_code} 错误，等待 {wait_time}s 重试")
                    time.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    return BaiduResult(
                        success=False, data={}, metadata={},
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )

                data = resp.json()

                # 百度 API: status=0 表示成功, message="ok"
                status = data.get("status")
                message = data.get("message", "")
                if status is not None and status != 0:
                    return BaiduResult(
                        success=False, data={}, metadata={},
                        error=f"API 错误 ({status}): {message}",
                    )

                return BaiduResult(
                    success=True, data=data,
                    metadata={"source": "baidu", "url": url},
                )

            except requests.Timeout:
                logger.warning(
                    f"[BaiduProvider] 请求超时，重试 {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return BaiduResult(
                    success=False, data={}, metadata={},
                    error="请求超时",
                )

            except requests.RequestException as e:
                logger.error(f"[BaiduProvider] 请求异常: {e}")
                return BaiduResult(
                    success=False, data={}, metadata={},
                    error=str(e),
                )

        return BaiduResult(
            success=False, data={}, metadata={},
            error="重试次数耗尽",
        )

    # ==================== Place Search v3 region ====================

    def search_region(
        self,
        query: str,
        region: str,
        region_limit: bool = True,
        tag: Optional[str] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_num: int = 0,
    ) -> BaiduResult:
        """行政区划区域检索 (place/v3/region)

        Args:
            query: 检索关键字 (单关键字)
            region: 行政区划 (支持到区县级)
            region_limit: 仅召回 region 区域内数据
            tag: 分类偏好 (与 query 组合)
            page_size: 每页条数 (最大 20)
            page_num: 页码 (从 0 开始)
        """
        params = {
            "query": query,
            "region": region,
            "region_limit": "true" if region_limit else "false",
            "coord_type": COORD_TYPE_WGS84,
            "page_size": str(page_size),
            "page_num": str(page_num),
        }
        if tag:
            params["tag"] = tag

        result = self._request(REGION_V3_URL, params)
        if not result.success:
            return result

        return BaiduResult(
            success=True,
            data={
                "results": result.data.get("results", []),
                "total": result.data.get("total", 0),
                "result_type": result.data.get("result_type", ""),
            },
            metadata={
                **result.metadata,
                "query": query, "region": region,
                "tag": tag,
            },
        )

    # ==================== Place Search v2 city ====================

    def search_city(
        self,
        query: str,
        region: str,
        city_limit: bool = True,
        tag: Optional[str] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_num: int = 0,
    ) -> BaiduResult:
        """行政区划区域检索 v2 (place/v2/search)

        支持 region 限定到城市级 + city_limit + tag 偏好。
        """
        params = {
            "query": query,
            "region": region,
            "city_limit": "true" if city_limit else "false",
            "coord_type": COORD_TYPE_WGS84,
            "page_size": str(page_size),
            "page_num": str(page_num),
        }
        if tag:
            params["tag"] = tag

        result = self._request(SEARCH_V2_URL, params)
        if not result.success:
            return result

        return BaiduResult(
            success=True,
            data={
                "results": result.data.get("results", []),
                "total": result.data.get("total", 0),
            },
            metadata={**result.metadata, "query": query, "region": region},
        )

    # ==================== Place Suggestion v2 ====================

    def search_suggestion(
        self,
        query: str,
        region: str,
        region_limit: bool = True,
        location: Optional[str] = None,
        radius: Optional[int] = None,
    ) -> BaiduResult:
        """地点输入提示 (place/v2/suggestion)

        输入关键字 → 返回联想 POI 列表。轻量级。
        """
        params = {
            "query": query,
            "region": region,
            "region_limit": "true" if region_limit else "false",
            "coord_type": COORD_TYPE_WGS84,
        }
        if location:
            params["location"] = location
        if radius:
            params["radius"] = str(radius)

        result = self._request(SUGGESTION_URL, params)
        if not result.success:
            return result

        # 解析 suggestion result
        results = []
        for r in result.data.get("result", []):
            entry = {
                "name": r.get("name", ""),
                "city": r.get("city", ""),
                "district": r.get("district", ""),
                "business": r.get("business", ""),
                "cityid": r.get("cityid", ""),
            }
            # 部分有 location 字段
            loc = r.get("location") or {}
            if loc.get("lat") and loc.get("lng"):
                entry["lon"] = float(loc["lng"])
                entry["lat"] = float(loc["lat"])
            results.append(entry)

        return BaiduResult(
            success=True,
            data={"results": results, "count": len(results)},
            metadata={
                **result.metadata, "query": query, "region": region,
                "kind": "suggestion",
            },
        )

    # ==================== Parse ====================

    @staticmethod
    def _parse_pois(results: List[Dict]) -> List[Dict[str, Any]]:
        """解析百度 place API 的 results 列表。

        百度 place API 返回字段:
          name, location{lat,lng}, address, province, city, area, adcode,
          uid, telephone, detail_info{distance, type, tag, ...}
        """
        pois = []
        for r in results:
            loc = r.get("location") or {}
            lat = loc.get("lat")
            lng = loc.get("lng")
            if lat is None or lng is None:
                continue

            detail = r.get("detail_info") or {}
            pois.append({
                "id": r.get("uid", ""),
                "name": r.get("name", ""),
                "lon": float(lng),
                "lat": float(lat),
                "address": r.get("address", ""),
                "province": r.get("province", ""),
                "city": r.get("city", ""),
                "area": r.get("area", ""),
                "adcode": r.get("adcode", ""),
                "telephone": r.get("telephone", ""),
                "type": detail.get("type", ""),
                "tag": detail.get("tag", ""),
                "distance": detail.get("distance", 0),
                "result_type": r.get("result_type", ""),
            })
        return pois


__all__ = ["BaiduProvider"]