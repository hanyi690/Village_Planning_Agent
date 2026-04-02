"""
天地图地理编码服务

天地图是国家测绘地理信息局官方地图服务，使用 WGS-84 坐标系。
免费额度：1万次/天

API 文档：http://lbs.tianditu.gov.cn/home/guide/guide.html
"""

import json
import requests
from typing import Dict, Any

from .base_provider import BaseGeocodingProvider, GeocodingResult
from ...utils.logger import get_logger

logger = get_logger(__name__)


class TiandituGeocodingProvider(BaseGeocodingProvider):
    """
    天地图地理编码服务

    特点：
    - 坐标系为 WGS-84，无需转换
    - 官方权威数据，地名准确
    - 免费额度 1万次/天
    """

    COORD_SYSTEM = "wgs84"
    API_BASE = "http://api.tianditu.gov.cn"

    def __init__(self, api_key: str, timeout: int = 30):
        """
        初始化天地图地理编码服务

        Args:
            api_key: 天地图 API Key
            timeout: 请求超时时间（秒）
        """
        super().__init__(api_key, timeout)

    def geocode(self, address: str) -> GeocodingResult:
        """
        地理编码：地址 -> 坐标

        Args:
            address: 地址字符串（如 "广东省梅州市平远县泗水镇金田村"）

        Returns:
            GeocodingResult 对象
        """
        if not self.api_key:
            return GeocodingResult(
                success=False,
                error="天地图 API Key 未配置",
                provider=self.get_name()
            )

        try:
            # 构建请求参数
            # 天地图地理编码 API 格式
            params = {
                "postStr": json.dumps({"keyWord": address}, ensure_ascii=False),
                "type": "geocode",
                "tk": self.api_key
            }

            url = f"{self.API_BASE}/search"
            logger.info(f"[Tianditu] 发送地理编码请求: {address}")

            response = requests.get(
                url,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            response.raise_for_status()

            data = response.json()
            logger.debug(f"[Tianditu] 响应数据: {data}")

            return self._parse_response(data, address)

        except requests.Timeout:
            logger.warning(f"[Tianditu] 请求超时: {address}")
            return self._create_error_result("请求超时")
        except requests.RequestException as e:
            logger.warning(f"[Tianditu] 请求失败: {e}")
            return self._create_error_result(str(e))
        except Exception as e:
            logger.error(f"[Tianditu] 解析失败: {e}")
            return self._create_error_result(str(e))

    def _parse_response(self, data: Dict[str, Any], address: str) -> GeocodingResult:
        """
        解析天地图 API 响应

        Args:
            data: API 响应数据
            address: 原始地址

        Returns:
            GeocodingResult 对象
        """
        # 天地图返回格式示例：
        # {
        #   "status": "0",  # 0 表示成功
        #   "data": [
        #     {
        #       "keyWord": "...",
        #       "lon": "116.391",
        #       "lat": "39.901",
        #       ...
        #     }
        #   ]
        # }

        if data.get("status") != "0":
            return GeocodingResult(
                success=False,
                error=f"API 返回错误: {data.get('status')}",
                provider=self.get_name(),
                raw_response=data
            )

        result_list = data.get("data", [])
        if not result_list:
            return GeocodingResult(
                success=False,
                error="未找到匹配地址",
                provider=self.get_name(),
                raw_response=data
            )

        # 取第一个结果
        first_result = result_list[0]

        try:
            lon = float(first_result.get("lon", 0))
            lat = float(first_result.get("lat", 0))

            if lon == 0 or lat == 0:
                return GeocodingResult(
                    success=False,
                    error="坐标数据无效",
                    provider=self.get_name(),
                    raw_response=data
                )

            return GeocodingResult(
                success=True,
                longitude=lon,
                latitude=lat,
                address=first_result.get("keyWord", address),
                provider=self.get_name(),
                raw_response=data
            )
        except (ValueError, TypeError) as e:
            return GeocodingResult(
                success=False,
                error=f"坐标解析失败: {e}",
                provider=self.get_name(),
                raw_response=data
            )

    def _check_availability(self) -> bool:
        """检查服务可用性"""
        return self._check_availability_default()