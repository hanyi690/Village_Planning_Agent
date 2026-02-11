"""
Redis Client for Village Planning System
Redis 客户端（用于缓存维度报告）

Features:
- Async operations with connection pooling
- Automatic retry on connection failure
- Graceful degradation when Redis is unavailable
- TTL-based cache expiration
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

try:
    import redis.asyncio as aioredis
    from redis.exceptions import RedisError, ConnectionError as RedisConnectionError
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None
    RedisError = Exception
    RedisConnectionError = Exception

logger = logging.getLogger(__name__)

# Redis 配置
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
REDIS_TTL_SECONDS = int(os.getenv('REDIS_TTL_SECONDS', 604800))

USE_REDIS_CACHE = os.getenv('USE_REDIS_CACHE', 'true').lower() == 'true'


class RedisClient:
    """
    Redis 客户端（异步）

    单例模式，支持连接池和自动重连。
    """

    _instance: RedisClient | None = None
    _client: aioredis.Redis | None = None
    _is_connected: bool = False

    def __new__(cls) -> RedisClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not REDIS_AVAILABLE:
            logger.warning("[Redis] Redis package not installed. Install with: pip install redis")
            self._enabled = False
            return

        if not USE_REDIS_CACHE:
            logger.info("[Redis] Redis cache disabled by USE_REDIS_CACHE environment variable")
            self._enabled = False
            return

        self._enabled = True
        self._connection_url = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

    async def _get_client(self) -> aioredis.Redis:
        """获取 Redis 客户端（懒加载）"""
        if not self._enabled:
            raise RuntimeError("Redis cache is disabled or not available")

        if self._client is None or not self._is_connected:
            try:
                logger.info(f"[Redis] Connecting to Redis at {self._connection_url}")
                self._client = await aioredis.from_url(
                    self._connection_url,
                    password=REDIS_PASSWORD,
                    db=REDIS_DB,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                )
                await self._client.ping()
                self._is_connected = True
                logger.info("[Redis] ✓ Connected successfully")
            except RedisConnectionError as e:
                logger.error(f"[Redis] ✗ Connection failed: {e}")
                self._is_connected = False
                self._client = None
                raise

        return self._client

    async def close(self) -> None:
        """关闭 Redis 连接"""
        if self._client:
            await self._client.close()
            self._is_connected = False
            logger.info("[Redis] Connection closed")

    async def ping(self) -> bool:
        """测试 Redis 连接"""
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except Exception as e:
            logger.warning(f"[Redis] Ping failed: {e}")
            return False

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """
        设置键值（带过期时间）

        Args:
            key: Redis 键
            value: 值（自动 JSON 序列化）
            ttl: 过期时间（秒），默认使用 REDIS_TTL_SECONDS

        Returns:
            bool: True if successful
        """
        if not self._enabled:
            return False

        try:
            client = await self._get_client()
            json_value = json.dumps(value, ensure_ascii=False)

            if ttl is None:
                ttl = REDIS_TTL_SECONDS

            await client.setex(key, ttl, json_value)
            logger.debug(f"[Redis] Set key: {key} (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"[Redis] Failed to set key {key}: {e}")
            self._is_connected = False
            return False

    async def get(self, key: str) -> Any | None:
        """获取键值"""
        if not self._enabled:
            return None

        try:
            client = await self._get_client()
            value = await client.get(key)

            if value is None:
                return None

            return json.loads(value)

        except Exception as e:
            logger.error(f"[Redis] Failed to get key {key}: {e}")
            self._is_connected = False
            return None

    async def hset(self, name: str, key: str, value: Any) -> bool:
        """设置哈希字段"""
        if not self._enabled:
            return False

        try:
            client = await self._get_client()
            json_value = json.dumps(value, ensure_ascii=False)
            await client.hset(name, key, json_value)
            logger.debug(f"[Redis] HSet {name}.{key}")
            return True

        except Exception as e:
            logger.error(f"[Redis] Failed to hset {name}.{key}: {e}")
            self._is_connected = False
            return False

    async def hget(self, name: str, key: str) -> Any | None:
        """获取哈希字段"""
        if not self._enabled:
            return None

        try:
            client = await self._get_client()
            value = await client.hget(name, key)

            if value is None:
                return None

            return json.loads(value)

        except Exception as e:
            logger.error(f"[Redis] Failed to hget {name}.{key}: {e}")
            self._is_connected = False
            return None

    async def hgetall(self, name: str) -> dict[str, Any]:
        """获取哈希表所有字段"""
        if not self._enabled:
            return {}

        try:
            client = await self._get_client()
            values = await client.hgetall(name)

            result: dict[str, Any] = {}
            for key, value in values.items():
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = value

            return result

        except Exception as e:
            logger.error(f"[Redis] Failed to hgetall {name}: {e}")
            self._is_connected = False
            return {}

    async def delete(self, *keys: str) -> int:
        """删除键"""
        if not self._enabled:
            return 0

        try:
            client = await self._get_client()
            count = await client.delete(*keys)
            logger.debug(f"[Redis] Deleted {count} keys")
            return count

        except Exception as e:
            logger.error(f"[Redis] Failed to delete keys: {e}")
            self._is_connected = False
            return 0

    async def exists(self, *keys: str) -> int:
        """检查键是否存在"""
        if not self._enabled:
            return 0

        try:
            client = await self._get_client()
            return await client.exists(*keys)

        except Exception as e:
            logger.error(f"[Redis] Failed to check keys existence: {e}")
            self._is_connected = False
            return 0

    # Village Planning specific methods

    async def save_dimension_report(
        self,
        session_id: str,
        layer: int,
        dimension_key: str,
        dimension_name: str,
        content: str
    ) -> bool:
        """保存维度报告到 Redis"""
        hash_key = f"session:reports:{session_id}"
        field_key = f"layer{layer}:{dimension_key}"

        data = {
            "layer": layer,
            "dimension_key": dimension_key,
            "dimension_name": dimension_name,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }

        return await self.hset(hash_key, field_key, data)

    async def get_dimension_report(
        self,
        session_id: str,
        layer: int,
        dimension_key: str
    ) -> dict[str, Any] | None:
        """获取维度报告"""
        hash_key = f"session:reports:{session_id}"
        field_key = f"layer{layer}:{dimension_key}"
        return await self.hget(hash_key, field_key)

    async def get_all_session_reports(self, session_id: str) -> dict[str, Any]:
        """获取会话的所有维度报告"""
        hash_key = f"session:reports:{session_id}"
        return await self.hgetall(hash_key)

    async def save_layer_report(
        self,
        session_id: str,
        layer: int,
        combined_report: str,
        dimension_reports: dict[str, str]
    ) -> bool:
        """保存完整的层级报告（综合报告 + 维度报告）"""
        combined_key = f"session:reports:{session_id}:layer{layer}:combined"
        success1 = await self.set(combined_key, {
            "layer": layer,
            "content": combined_report,
            "timestamp": datetime.now().isoformat()
        })

        success2 = True
        for dimension_key, content in dimension_reports.items():
            if not await self.save_dimension_report(
                session_id, layer, dimension_key,
                dimension_key, content
            ):
                success2 = False

        return success1 and success2

    async def get_layer_report(
        self,
        session_id: str,
        layer: int
    ) -> dict[str, Any] | None:
        """获取层级报告（综合报告 + 维度报告）"""
        combined_key = f"session:reports:{session_id}:layer{layer}:combined"
        combined = await self.get(combined_key)

        all_reports = await self.get_all_session_reports(session_id)

        dimension_reports: dict[str, str] = {}
        prefix = f"layer{layer}:"
        for key, value in all_reports.items():
            if key.startswith(prefix):
                dimension_key = key[len(prefix):]
                dimension_reports[dimension_key] = value.get("content", "")

        if combined or dimension_reports:
            return {
                "combined": combined.get("content", "") if combined else "",
                "dimensions": dimension_reports
            }

        return None

    @property
    def enabled(self) -> bool:
        """检查 Redis 是否启用"""
        return self._enabled and REDIS_AVAILABLE


# 全局单例
redis_client: RedisClient | None = None


def get_redis_client() -> RedisClient:
    """获取 Redis 客户端单例"""
    global redis_client
    if redis_client is None:
        redis_client = RedisClient()
    return redis_client


async def init_redis() -> None:
    """初始化 Redis 连接（可选）"""
    client = get_redis_client()
    if client.enabled:
        try:
            await client.ping()
            logger.info("[Redis] ✓ Initialized successfully")
        except Exception as e:
            logger.warning(f"[Redis] Initialization failed (will retry later): {e}")


async def close_redis() -> None:
    """关闭 Redis 连接"""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


__all__ = [
    "RedisClient",
    "get_redis_client",
    "init_redis",
    "close_redis",
    "USE_REDIS_CACHE",
    "REDIS_AVAILABLE",
]
