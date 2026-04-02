"""
地理编码服务基类

定义统一的地理编码接口和结果结构。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
import requests


class ProviderName:
    """
    地理编码服务提供者名称常量
    """
    TIANDITU = "tianditu"
    GAODE = "gaode"
    BAIDU = "baidu"
    NOMINATIM = "nominatim"


@dataclass
class GeocodingResult:
    """
    地理编码结果

    Attributes:
        success: 是否成功
        longitude: 经度 (WGS-84)
        latitude: 纬度 (WGS-84)
        address: 标准化地址
        provider: 提供者名称
        raw_response: 原始响应数据
        error: 错误信息
    """
    success: bool
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    address: Optional[str] = None
    provider: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "success": self.success,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "address": self.address,
            "provider": self.provider,
            "error": self.error,
        }


class BaseGeocodingProvider(ABC):
    """
    地理编码服务基类

    所有地理编码服务需要继承此类并实现 geocode 方法。
    """

    # 坐标系类型
    COORD_SYSTEM: str = "unknown"  # "wgs84", "gcj02", "bd09"

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        """
        初始化地理编码服务

        Args:
            api_key: API 密钥
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key
        self.timeout = timeout
        self._is_available = None

    @abstractmethod
    def geocode(self, address: str) -> GeocodingResult:
        """
        地理编码：地址 -> 坐标

        Args:
            address: 地址字符串

        Returns:
            GeocodingResult 对象
        """
        pass

    @property
    def is_available(self) -> bool:
        """
        检查服务是否可用

        Returns:
            True 如果服务可用（有 API Key 且网络可达）
        """
        if self._is_available is None:
            self._is_available = self._check_availability()
        return self._is_available

    @abstractmethod
    def _check_availability(self) -> bool:
        """检查服务可用性"""
        pass

    def _check_availability_default(self) -> bool:
        """
        默认的服务可用性检查

        仅检查 API Key 是否配置。子类可以覆盖此方法添加额外的网络检查。
        """
        return bool(self.api_key)

    def _create_error_result(self, error: str) -> GeocodingResult:
        """
        创建错误结果

        Args:
            error: 错误信息

        Returns:
            包含错误信息的 GeocodingResult
        """
        return GeocodingResult(
            success=False,
            error=error,
            provider=self.get_name()
        )

    def _handle_request_exception(self, exception: Exception, address: str) -> GeocodingResult:
        """
        处理 HTTP 请求异常

        Args:
            exception: 捕获的异常
            address: 请求的地址

        Returns:
            包含错误信息的 GeocodingResult
        """
        if isinstance(exception, requests.Timeout):
            return self._create_error_result("请求超时")
        elif isinstance(exception, requests.RequestException):
            return self._create_error_result(str(exception))
        else:
            return self._create_error_result(str(exception))

    def get_name(self) -> str:
        """获取服务名称"""
        return self.__class__.__name__