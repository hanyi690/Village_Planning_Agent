"""全局速率限制器

提供线程安全的单例速率限制器，确保所有 API 客户端共享同一速率限制实例，
避免多实例导致的 QPS 超限问题。
"""
import time
import asyncio
import threading
from typing import Dict

from src.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """线程安全的单例速率限制器

    每个服务名称对应一个全局唯一的速率限制器实例。
    例如：天地图和高德分别有独立的限制器，但天地图的多个组件共享同一实例。

    Attributes:
        name: 限制器名称（如 "tianditu", "amap"）
        rate_limit: 每秒最大请求数 (QPS)
        min_interval: 两次请求之间的最小间隔时间（秒）
    """

    # 类级别存储：所有服务名称对应的限制器实例
    _instances: Dict[str, 'RateLimiter'] = {}
    # 全局锁：保护实例创建过程
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, name: str, rate_limit: float) -> 'RateLimiter':
        """获取指定服务的全局速率限制器实例

        Args:
            name: 服务名称（如 "tianditu", "amap"）
            rate_limit: 每秒最大请求数 (QPS)

        Returns:
            RateLimiter 实例（单例模式）
        """
        with cls._lock:
            if name not in cls._instances:
                cls._instances[name] = RateLimiter(name, rate_limit)
                logger.info(f"[RateLimiter] 创建全局限制器: {name}, QPS={rate_limit}")
            return cls._instances[name]

    @classmethod
    def get_existing_instance(cls, name: str) -> 'RateLimiter':
        """获取已存在的限制器实例（不创建新的）

        Args:
            name: 服务名称

        Returns:
            已存在的 RateLimiter 实例，不存在则返回 None
        """
        with cls._lock:
            return cls._instances.get(name)

    def __init__(self, name: str, rate_limit: float):
        """初始化速率限制器

        Args:
            name: 限制器名称
            rate_limit: 每秒最大请求数 (QPS)
        """
        self.name = name
        self.rate_limit = rate_limit
        self.min_interval = 1.0 / rate_limit if rate_limit > 0 else 0
        self._last_request_time = 0.0
        # 实例级锁：保护请求时间更新
        self._instance_lock = threading.Lock()

    def wait(self) -> float:
        """等待直到可以发送下一个请求

        Returns:
            实际等待的时间（秒）
        """
        if self.rate_limit <= 0:
            return 0.0

        with self._instance_lock:
            elapsed = time.time() - self._last_request_time
            wait_time = 0.0

            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                time.sleep(wait_time)

            self._last_request_time = time.time()
            return wait_time

    async def async_wait(self) -> float:
        """异步等待，适用于异步上下文

        使用 asyncio.sleep() 而非阻塞的 time.sleep()，
        避免阻塞异步事件循环。

        Returns:
            实际等待的时间（秒）
        """
        if self.rate_limit <= 0:
            return 0.0

        with self._instance_lock:
            elapsed = time.time() - self._last_request_time
            wait_time = 0.0
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
            self._last_request_time = time.time()

        if wait_time > 0:
            await asyncio.sleep(wait_time)
        return wait_time

    def reset(self):
        """重置速率限制器状态"""
        with self._instance_lock:
            self._last_request_time = 0.0

    def get_stats(self) -> Dict:
        """获取限制器状态信息"""
        with self._instance_lock:
            return {
                "name": self.name,
                "rate_limit": self.rate_limit,
                "min_interval": self.min_interval,
                "last_request_time": self._last_request_time,
            }


__all__ = ["RateLimiter"]