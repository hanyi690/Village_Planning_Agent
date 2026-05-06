"""
GIS 数据管理模块

管理数据来源优先级：用户上传 > 缓存 > 自动获取。
支持会话级数据存储和数据状态追踪。
"""

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Set
from pathlib import Path

logger = logging.getLogger(__name__)

# 支持的数据类型常量
ALL_DATA_TYPES: Set[str] = {'boundary', 'water', 'road', 'residential', 'poi', 'land_use'}

# 会话管理配置
_MAX_STORES = 100
_STORE_TTL_SECONDS = 3600  # 1 小时


@dataclass
class GISDataStore:
    """会话级 GIS 数据存储"""
    village_name: str
    user_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    cached_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class GISDataManager:
    """GIS 数据来源优先级管理器"""

    # 会话存储（每个村庄一个）
    _stores: Dict[str, GISDataStore] = {}
    _lock = threading.Lock()

    @classmethod
    def _cleanup_expired_stores(cls) -> None:
        """清理过期的存储"""
        now = time.time()
        expired = [
            k for k, v in cls._stores.items()
            if now - v.created_at > _STORE_TTL_SECONDS
        ]
        for k in expired:
            del cls._stores[k]
            logger.info(f"[数据管理] 清理过期存储: {k}")

    @classmethod
    def get_store(cls, village_name: str) -> GISDataStore:
        """
        获取指定村庄的数据存储

        Args:
            village_name: 村庄名称

        Returns:
            GISDataStore 实例
        """
        with cls._lock:
            if village_name not in cls._stores:
                # 清理过期存储
                if len(cls._stores) >= _MAX_STORES:
                    cls._cleanup_expired_stores()
                cls._stores[village_name] = GISDataStore(village_name=village_name)
                logger.debug(f"[数据管理] 创建新存储: {village_name}")
            return cls._stores[village_name]

    @classmethod
    def get_data(
        cls,
        data_type: str,
        village_name: str,
        context: Optional[Dict[str, Any]] = None,
        auto_fetch: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        按优先级获取数据

        优先级：用户上传 > 会话缓存 > 自动获取

        Args:
            data_type: 数据类型（boundary/water/road/residential/poi）
            village_name: 村庄名称
            context: 上下文（用于自动获取）
            auto_fetch: 是否允许自动获取

        Returns:
            GeoJSON 数据字典，未找到返回 None
        """
        store = cls.get_store(village_name)

        # 1. 用户上传数据（最高优先级）
        if data_type in store.user_data:
            logger.info(f"[数据管理] 使用用户数据: {village_name}/{data_type}")
            return store.user_data[data_type]

        # 2. 会话缓存数据
        if data_type in store.cached_data:
            logger.info(f"[数据管理] 使用缓存数据: {village_name}/{data_type}")
            return store.cached_data[data_type]

        # 3. 自动获取（懒加载）
        if auto_fetch and context:
            auto_data = cls._auto_fetch_data(data_type, village_name, context)
            if auto_data:
                store.cached_data[data_type] = auto_data
                logger.info(f"[数据管理] 自动获取成功: {village_name}/{data_type}")
                return auto_data

        logger.warning(f"[数据管理] 数据未找到: {village_name}/{data_type}")
        return None

    @classmethod
    def set_user_data(
        cls,
        data_type: str,
        village_name: str,
        geojson: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        设置用户上传数据

        用户数据优先级最高，会覆盖同类型的缓存数据。

        Args:
            data_type: 数据类型
            village_name: 村庄名称
            geojson: GeoJSON 数据
            metadata: 元数据（可选）
        """
        store = cls.get_store(village_name)
        store.user_data[data_type] = geojson

        # 存储元数据
        if metadata:
            store.metadata[data_type] = {
                'source': 'user_upload',
                'uploaded_at': metadata.get('uploaded_at'),
                'file_name': metadata.get('file_name'),
                'feature_count': metadata.get('feature_count', 0),
            }

        # 清空同类型缓存（用户数据优先）
        store.cached_data.pop(data_type, None)

        logger.info(f"[数据管理] 用户数据已设置: {village_name}/{data_type}")

    @classmethod
    def set_cached_data(
        cls,
        data_type: str,
        village_name: str,
        geojson: Dict[str, Any]
    ) -> None:
        """
        设置缓存数据（用于自动获取结果）

        Args:
            data_type: 数据类型
            village_name: 村庄名称
            geojson: GeoJSON 数据
        """
        store = cls.get_store(village_name)

        # 用户数据存在时不覆盖
        if data_type in store.user_data:
            logger.debug(f"[数据管理] 用户数据已存在，跳过缓存: {village_name}/{data_type}")
            return

        store.cached_data[data_type] = geojson
        logger.info(f"[数据管理] 缓存数据已设置: {village_name}/{data_type}")

    @classmethod
    def clear_user_data(cls, village_name: str, data_type: str) -> None:
        """
        清除用户数据，恢复使用缓存/自动获取

        Args:
            village_name: 村庄名称
            data_type: 数据类型
        """
        store = cls.get_store(village_name)
        store.user_data.pop(data_type, None)
        store.metadata.pop(data_type, None)
        logger.info(f"[数据管理] 用户数据已清除: {village_name}/{data_type}")

    @classmethod
    def clear_cache(cls, village_name: str, data_type: Optional[str] = None) -> None:
        """
        清除缓存数据

        Args:
            village_name: 村庄名称
            data_type: 数据类型（可选，不指定则清除所有）
        """
        store = cls.get_store(village_name)

        if data_type:
            store.cached_data.pop(data_type, None)
            logger.info(f"[数据管理] 缓存已清除: {village_name}/{data_type}")
        else:
            store.cached_data.clear()
            logger.info(f"[数据管理] 所有缓存已清除: {village_name}")

    @classmethod
    def clear_all(cls, village_name: str) -> None:
        """
        清除指定村庄的所有数据

        Args:
            village_name: 村庄名称
        """
        if village_name in cls._stores:
            del cls._stores[village_name]
            logger.info(f"[数据管理] 存储已删除: {village_name}")

    @classmethod
    def get_data_status(cls, village_name: str) -> Dict[str, Any]:
        """
        获取数据状态概览

        Args:
            village_name: 村庄名称

        Returns:
            状态字典，包含 user_uploaded, cached, missing 列表
        """
        store = cls.get_store(village_name)

        available = set(store.user_data.keys()) | set(store.cached_data.keys())

        return {
            'village_name': village_name,
            'user_uploaded': list(store.user_data.keys()),
            'cached': list(store.cached_data.keys()),
            'missing': list(ALL_DATA_TYPES - available),
            'metadata': store.metadata,
        }

    @classmethod
    def has_data(cls, village_name: str, data_type: str) -> bool:
        """
        检查是否有数据

        Args:
            village_name: 村庄名称
            data_type: 数据类型

        Returns:
            是否存在数据
        """
        store = cls.get_store(village_name)
        return data_type in store.user_data or data_type in store.cached_data

    @classmethod
    def get_all_data(cls, village_name: str) -> Dict[str, Dict[str, Any]]:
        """
        获取所有数据（合并用户数据和缓存）

        Args:
            village_name: 村庄名称

        Returns:
            所有数据的字典
        """
        store = cls.get_store(village_name)

        # 合并数据，用户数据优先
        all_data = {**store.cached_data, **store.user_data}
        return all_data

    @classmethod
    def _auto_fetch_data(
        cls,
        data_type: str,
        village_name: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        自动获取数据

        Args:
            data_type: 数据类型
            village_name: 村庄名称
            context: 上下文

        Returns:
            GeoJSON 数据，失败返回 None
        """
        try:
            from ..core.gis_data_fetcher import get_fetcher
            from ...config.gis_config import GISConfig

            fetcher = get_fetcher()
            buffer_km = GISConfig.get_buffer('village', data_type)

            # 根据数据类型选择获取方法
            # Note: land_use 需要用户上传，不支持自动获取
            fetch_methods = {
                'boundary': fetcher.get_admin_boundary,
                'water': fetcher.get_water_system,
                'road': fetcher.get_road_network,
                'residential': fetcher.get_residential_points,
                'poi': fetcher.search_pois,
            }

            method = fetch_methods.get(data_type)
            if method is None:
                logger.debug(f"[数据管理] 数据类型 {data_type} 不支持自动获取，需用户上传")
                return None

            # 调用获取方法
            result = method(village_name, buffer_km=buffer_km)

            if result and result.get('success'):
                geojson = result.get('geojson', {})
                if geojson and 'features' in geojson:
                    return geojson

            logger.warning(f"[数据管理] 自动获取无有效数据: {data_type}")
            return None

        except Exception as e:
            logger.error(f"[数据管理] 自动获取失败: {data_type}, 错误: {e}")
            return None


def get_gis_data(
    data_type: str,
    village_name: str,
    context: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    便捷函数：获取 GIS 数据

    Args:
        data_type: 数据类型
        village_name: 村庄名称
        context: 上下文（可选）

    Returns:
        GeoJSON 数据
    """
    return GISDataManager.get_data(data_type, village_name, context)


def set_user_gis_data(
    data_type: str,
    village_name: str,
    geojson: Dict[str, Any]
) -> None:
    """
    便捷函数：设置用户 GIS 数据

    Args:
        data_type: 数据类型
        village_name: 村庄名称
        geojson: GeoJSON 数据
    """
    GISDataManager.set_user_data(data_type, village_name, geojson)


def get_data_status(village_name: str) -> Dict[str, Any]:
    """
    便捷函数：获取数据状态

    Args:
        village_name: 村庄名称

    Returns:
        状态字典
    """
    return GISDataManager.get_data_status(village_name)


__all__ = [
    'GISDataManager',
    'GISDataStore',
    'get_gis_data',
    'set_user_gis_data',
    'get_data_status',
]