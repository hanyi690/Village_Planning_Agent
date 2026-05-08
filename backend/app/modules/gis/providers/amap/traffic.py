"""高德地图交通态势服务"""
import time
import requests
from typing import Dict, Any, Tuple, Optional, List

from .types import AmapResult
from .constants import (
    TRAFFIC_RECT_URL,
    TRAFFIC_CIRCLE_URL,
    TRAFFIC_ROAD_URL,
    TRAFFIC_STATUS_LEVELS,
)
from ....core.config import (
    AMAP_API_KEY,
    AMAP_RATE_LIMIT,
    AMAP_MAX_RETRIES,
    GIS_TIMEOUT,
)
from ....utils.logger import get_logger

logger = get_logger(__name__)


class TrafficService:
    """高德地图交通态势 API"""

    def __init__(self):
        self.api_key = AMAP_API_KEY
        self.rate_limit = AMAP_RATE_LIMIT
        self.max_retries = AMAP_MAX_RETRIES
        self.timeout = GIS_TIMEOUT
        self._last_request_time = 0

        if not self.api_key:
            logger.warning("[TrafficService] AMAP_API_KEY 未配置")

    def _rate_limit_wait(self):
        """速率限制等待"""
        if self.rate_limit <= 0:
            return
        min_interval = 1.0 / self.rate_limit
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _request(self, url: str, params: Dict[str, Any]) -> AmapResult:
        """发送请求"""
        if not self.api_key:
            return AmapResult(
                success=False,
                data={},
                metadata={},
                error="AMAP_API_KEY 未配置",
            )

        params["key"] = self.api_key
        params["output"] = "JSON"

        for attempt in range(self.max_retries):
            self._rate_limit_wait()

            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json"},
                    timeout=self.timeout,
                )

                if resp.status_code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"[TrafficService] 429 速率限制，等待 {wait_time}s")
                    time.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    return AmapResult(
                        success=False,
                        data={},
                        metadata={},
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )

                data = resp.json()
                status = data.get("status", "0")
                infocode = data.get("infocode", "0")

                if status != "1" or infocode != "10000":
                    error_msg = data.get("info", "未知错误")
                    return AmapResult(
                        success=False,
                        data={},
                        metadata={},
                        error=f"API 错误 ({infocode}): {error_msg}",
                    )

                return AmapResult(
                    success=True,
                    data=data,
                    metadata={"source": "amap_traffic", "url": url},
                )

            except requests.Timeout:
                logger.warning(f"[TrafficService] 请求超时，重试 {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return AmapResult(
                    success=False,
                    data={},
                    metadata={},
                    error="请求超时",
                )

            except requests.RequestException as e:
                logger.error(f"[TrafficService] 请求异常: {e}")
                return AmapResult(
                    success=False,
                    data={},
                    metadata={},
                    error=str(e),
                )

        return AmapResult(
            success=False,
            data={},
            metadata={},
            error="重试次数耗尽",
        )

    def get_traffic_rectangle(
        self,
        bounds: Tuple[float, float, float, float],
        level: int = 5,
    ) -> AmapResult:
        """矩形区域交通态势查询

        Args:
            bounds: 矩形区域左下和右上坐标 (min_lon, min_lat, max_lon, max_lat)
            level: 道路等级（0=全部，1=高速，2=城市快速路，3=主干道，4=次干道，5=支路）

        Returns:
            AmapResult with traffic data
        """
        coords_str = f"{bounds[0]},{bounds[1]};{bounds[2]},{bounds[3]}"
        params = {
            "rectangle": coords_str,
            "level": str(level),
            "extensions": "all",
        }

        result = self._request(TRAFFIC_RECT_URL, params)

        if not result.success:
            return result

        data = result.data
        trafficinfo = data.get("trafficinfo", {})

        evaluation = self.parse_traffic_evaluation(trafficinfo)

        roads = trafficinfo.get("roads", [])
        road_list = self._parse_road_traffic(roads)

        return AmapResult(
            success=True,
            data={"evaluation": evaluation, "roads": road_list},
            metadata={
                "bounds": bounds,
                "level": level,
                "source": "amap_traffic",
            },
        )

    def get_traffic_circle(
        self,
        center: Tuple[float, float],
        radius: int = 1000,
        level: int = 5,
    ) -> AmapResult:
        """圆形区域交通态势查询

        Args:
            center: 中心点坐标 (lon, lat)
            radius: 搜索半径（米）
            level: 道路等级

        Returns:
            AmapResult with traffic data
        """
        params = {
            "location": f"{center[0]},{center[1]}",
            "radius": str(radius),
            "level": str(level),
            "extensions": "all",
        }

        result = self._request(TRAFFIC_CIRCLE_URL, params)

        if not result.success:
            return result

        data = result.data
        trafficinfo = data.get("trafficinfo", {})

        evaluation = self.parse_traffic_evaluation(trafficinfo)

        roads = trafficinfo.get("roads", [])
        road_list = self._parse_road_traffic(roads)

        return AmapResult(
            success=True,
            data={"evaluation": evaluation, "roads": road_list},
            metadata={
                "center": center,
                "radius": radius,
                "level": level,
                "source": "amap_traffic",
            },
        )

    def get_traffic_road(
        self,
        road_name: str,
        city: Optional[str] = None,
    ) -> AmapResult:
        """指定道路交通态势查询

        Args:
            road_name: 道路名称
            city: 城市名称（可选）

        Returns:
            AmapResult with road traffic info
        """
        params = {"name": road_name}
        if city:
            params["city"] = city

        result = self._request(TRAFFIC_ROAD_URL, params)

        if not result.success:
            return result

        data = result.data
        trafficinfo = data.get("trafficinfo", {})

        roads = trafficinfo.get("roads", [])
        road_list = self._parse_road_traffic(roads)

        return AmapResult(
            success=True,
            data={"roads": road_list},
            metadata={
                "road_name": road_name,
                "city": city,
                "source": "amap_traffic",
            },
        )

    def parse_traffic_evaluation(self, trafficinfo: Dict) -> Dict[str, Any]:
        """解析交通态势评估信息

        Args:
            trafficinfo: 高德返回的交通信息

        Returns:
            Dict with evaluation percentages
        """
        evaluation = trafficinfo.get("evaluation", {})

        # 解析各状态占比
        status_levels = {
            "excellent": "畅通",
            "congested": "缓行",
            "blocked": "拥堵",
            "seriousBlocked": "严重拥堵",
        }

        result = {
            "description": evaluation.get("description", ""),
            "status": TRAFFIC_STATUS_LEVELS.get(evaluation.get("status", 5), "无数据"),
        }

        for key, label in status_levels.items():
            value = evaluation.get(key, 0)
            if isinstance(value, str):
                try:
                    value = int(value)
                except ValueError:
                    value = 0
            result[label] = value

        return result

    def _parse_road_traffic(self, roads: List[Dict]) -> List[Dict[str, Any]]:
        """解析道路交通信息"""
        road_list = []
        for road in roads:
            road_item = {
                "name": road.get("name", ""),
                "status": TRAFFIC_STATUS_LEVELS.get(road.get("status", 5), "无数据"),
                "direction": road.get("direction", ""),
                "angle": road.get("angle", ""),
                "speed": int(road.get("speed", 0)) if road.get("speed") else 0,
                "lcodes": road.get("lcodes", ""),
            }

            # 解析道路 polyline
            polyline = road.get("polyline", "")
            if polyline:
                coords = []
                for coord_pair in polyline.split(";"):
                    if "," in coord_pair:
                        parts = coord_pair.split(",")
                        coords.append([float(parts[0]), float(parts[1])])
                road_item["coords"] = coords

            road_list.append(road_item)

        return road_list


__all__ = ["TrafficService"]