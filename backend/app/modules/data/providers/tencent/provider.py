"""腾讯地图核心 API 封装

坐标系说明:
    - 腾讯默认返回 GCJ02 坐标 (火星坐标系)
    - 通过 `coord_type=wgs84` 参数可直接返回 WGS84
    - 也可使用坐标转换 API 进行批量转换

关键 API 格式 (重要!):
    URL: https://apis.map.qq.com/ws/place/v1/search
    必填参数:
        - keyword: 单关键字
        - boundary: 格式 "region(city_name, [auto_extend], [lat,lng])"
                                或 "nearby(lat,lng,radius)" (lat 在前!)
                                或 "rectangle(lat1,lng1,lat2,lng2)"
    可选参数:
        - filter: "category=分类1,分类2" 或 "category<>排除"
        - page_size: 最大 20
        - page_index: 从 1 开始
        - orderby=_distance (仅 nearby)
        - coord_type: wgs84 | gcj02
    返回: {status:0, message:"ok", data:[...], count}

POI 字段:
    id, title, address, tel, category, type
    (0=普通/1=公交/2=地铁/3=公交线路/4=行政区划)
    location: {lat, lng}  (lat 在前!)
    _distance: 周边搜索距离
    ad_info: {adcode, province, city, district}
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from .constants import (
    SEARCH_URL,
    SUGGESTION_URL,
    COORD_TYPE_WGS84,
    DEFAULT_PAGE_SIZE,
)
from .types import TencentMapResult

from app.modules.data.connections import RateLimiter
from app.core.settings import (
    TECENT_MAP_API_KEY,
    TECENT_MAP_RATE_LIMIT,
    TECENT_MAP_MAX_RETRIES,
    GIS_TIMEOUT,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class TencentMapProvider:
    """腾讯地图 API 封装"""

    def __init__(self):
        self.api_key = TECENT_MAP_API_KEY
        self.rate_limit = TECENT_MAP_RATE_LIMIT
        self.max_retries = TECENT_MAP_MAX_RETRIES
        self.timeout = GIS_TIMEOUT

        self._rate_limiter = RateLimiter.get_instance("tencent_map", self.rate_limit)

        if not self.api_key:
            logger.warning("[TencentMapProvider] TECENT_MAP_API_KEY 未配置")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "VillagePlanningAgent/1.0",
        }

    def _rate_limit_wait(self):
        self._rate_limiter.wait()

    def _request(self, url: str, params: Dict[str, Any]) -> TencentMapResult:
        if not self.api_key:
            return TencentMapResult(
                success=False, data={}, metadata={},
                error="TECENT_MAP_API_KEY 未配置",
            )

        params["key"] = self.api_key

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
                    logger.warning(f"[TencentMapProvider] 429 速率限制，等待 {wait_time}s")
                    time.sleep(wait_time)
                    continue

                if resp.status_code >= 500:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"[TencentMapProvider] {resp.status_code} 错误，等待 {wait_time}s 重试"
                    )
                    time.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    return TencentMapResult(
                        success=False, data={}, metadata={},
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )

                data = resp.json()

                # 腾讯 API: status=0 表示成功
                status = data.get("status")
                message = data.get("message", "")
                if status != 0:
                    return TencentMapResult(
                        success=False, data={}, metadata={},
                        error=f"API 错误 ({status}): {message}",
                    )

                return TencentMapResult(
                    success=True, data=data,
                    metadata={"source": "tencent_map", "url": url},
                )

            except requests.Timeout:
                logger.warning(
                    f"[TencentMapProvider] 请求超时，重试 {attempt + 1}/{self.max_retries}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return TencentMapResult(
                    success=False, data={}, metadata={},
                    error="请求超时",
                )

            except requests.RequestException as e:
                logger.error(f"[TencentMapProvider] 请求异常: {e}")
                return TencentMapResult(
                    success=False, data={}, metadata={},
                    error=str(e),
                )

        return TencentMapResult(
            success=False, data={}, metadata={},
            error="重试次数耗尽",
        )

    # ==================== Search ====================

    def search_region(
        self,
        keyword: str,
        region: str,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_index: int = 1,
        coord_type: str = COORD_TYPE_WGS84,
        filter_category: str = "",
        orderby: str = "",
    ) -> TencentMapResult:
        """指定区域搜索 (行政区 / adcode).

        Args:
            keyword: 单关键字
            region: 行政区名 (如 "梅州市平远县") 或 adcode (如 "441426")
                    或 "梅州市" 等
            page_size: 每页条数 (最大 20)
            page_index: 页码 (从 1 开始)
            coord_type: 输出坐标系 ("wgs84" | "gcj02")
            filter_category: 分类过滤 ("中学,小学" 或 "学校") - 自动包 category=
            orderby: 排序 ("" | "_distance")
        """
        # boundary 格式: region(city_name, auto_extend)
        auto_extend = 0  # 0=仅当前城市, 1=自动扩大
        boundary = f"region({region},{auto_extend})"

        params = {
            "keyword": keyword,
            "boundary": boundary,
            "page_size": str(page_size),
            "page_index": str(page_index),
            "coord_type": coord_type,
        }
        if filter_category:
            params["filter"] = f"category={filter_category}"
        if orderby:
            params["orderby"] = orderby

        return self._search_impl(params, keyword, boundary)

    def search_nearby(
        self,
        keyword: str,
        center: Tuple[float, float],
        radius_m: int = 1000,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_index: int = 1,
        coord_type: str = COORD_TYPE_WGS84,
        filter_category: str = "",
        auto_extend: int = 1,
    ) -> TencentMapResult:
        """周边搜索.

        Args:
            keyword: 单关键字
            center: (lon, lat) WGS84, 内部转换为 (lat,lng)
            radius_m: 半径 (米, 范围 200-1000)
            auto_extend: 0=不扩大, 1=自动扩大 (默认)
        """
        # 腾讯 nearby 格式: nearby(lat,lng,radius[, auto_extend])
        # 注意: lat 在前!
        boundary = f"nearby({center[1]},{center[0]},{radius_m},{auto_extend})"

        params = {
            "keyword": keyword,
            "boundary": boundary,
            "page_size": str(page_size),
            "page_index": str(page_index),
            "coord_type": coord_type,
            "orderby": "_distance",
        }
        if filter_category:
            params["filter"] = f"category={filter_category}"

        return self._search_impl(params, keyword, boundary)

    def _search_impl(self, params: Dict[str, Any],
                     keyword: str, boundary: str) -> TencentMapResult:
        result = self._request(SEARCH_URL, params)
        if not result.success:
            return result

        # 腾讯返回结构: {status:0, message, data:[...], count}
        data_list = result.data.get("data", [])
        count = result.data.get("count", 0)

        pois = self._parse_pois(data_list)
        return TencentMapResult(
            success=True,
            data={"pois": pois, "count": count, "raw": data_list},
            metadata={
                **result.metadata,
                "keyword": keyword, "boundary": boundary,
                "filter": params.get("filter", ""),
            },
        )

    # ==================== Parse ====================

    @staticmethod
    def _parse_pois(data_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """解析腾讯 POI 数据为统一格式.

        腾讯 POI 字段:
          id, title, address, tel, category, type,
          location: {lat, lng}  (lat 在前!)
          _distance: 周边搜索距离
          ad_info: {adcode, province, city, district}
        """
        pois = []
        for r in data_list:
            loc = r.get("location") or {}
            lat = loc.get("lat")
            lng = loc.get("lng")
            if lat is None or lng is None:
                continue

            ad_info = r.get("ad_info") or {}
            pois.append({
                "id": r.get("id", ""),
                "name": r.get("title", ""),
                "lon": float(lng),
                "lat": float(lat),
                "address": r.get("address", ""),
                "tel": r.get("tel", ""),
                "category": r.get("category", ""),
                "type": r.get("type", 0),
                "distance": r.get("_distance", 0),
                "adcode": ad_info.get("adcode", ""),
                "province": ad_info.get("province", ""),
                "city": ad_info.get("city", ""),
                "district": ad_info.get("district", ""),
            })
        return pois


__all__ = ["TencentMapProvider"]