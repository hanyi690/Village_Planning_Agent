"""
GIS 数据管理模块

管理用户上传的 GIS 数据，提供内存缓存存储。
支持按 village_name + data_type 组织数据。

数据优先级：用户上传 > 会话缓存 > API 自动获取
"""

import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CachedGISData:
    """缓存的 GIS 数据结构"""
    data_type: str
    village_name: str
    geojson: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    uploaded_at: float = field(default_factory=time.time)
    source: str = "user_upload"


class GISDataManager:
    """
    GIS 数据管理器 - 管理用户上传数据缓存

    使用内存缓存存储用户上传的 GeoJSON 数据。
    支持按 village_name + data_type 组织数据。

    类方法设计，无需实例化即可使用。
    """

    # 内存缓存: {village_name: {data_type: CachedGISData}}
    _cache: Dict[str, Dict[str, CachedGISData]] = {}

    # 支持的数据类型（需与 shared_gis_context.GIS_DATA_TYPES 保持同步）
    DATA_TYPES = ['boundary', 'water', 'road', 'residential', 'poi', 'landuse',
                  'protection_zone', 'geological_hazard', 'custom']

    @classmethod
    def set_user_data(
        cls,
        data_type: str,
        village_name: str,
        geojson: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> CachedGISData:
        """
        存储用户上传的 GIS 数据

        Args:
            data_type: 数据类型 (boundary/water/road/residential/poi/...)
            village_name: 村庄名称
            geojson: GeoJSON 数据
            metadata: 元数据 (文件名、特征数等)

        Returns:
            CachedGISData 缓存的数据对象
        """
        if village_name not in cls._cache:
            cls._cache[village_name] = {}

        cached = CachedGISData(
            data_type=data_type,
            village_name=village_name,
            geojson=geojson,
            metadata=metadata or {},
            uploaded_at=time.time(),
            source="user_upload",
        )

        cls._cache[village_name][data_type] = cached
        logger.info(f"[GISDataManager] 用户数据已缓存: {village_name}/{data_type}, "
                    f"特征数: {cached.metadata.get('feature_count', 'N/A')}")

        return cached

    @classmethod
    def get_user_data(
        cls,
        village_name: str,
        data_type: str
    ) -> Optional[CachedGISData]:
        """
        获取用户上传的 GIS 数据

        Args:
            village_name: 村庄名称
            data_type: 数据类型

        Returns:
            CachedGISData 或 None
        """
        village_cache = cls._cache.get(village_name, {})
        return village_cache.get(data_type)

    @classmethod
    def get_all_user_data(cls, village_name: str) -> Dict[str, CachedGISData]:
        """
        获取指定村庄的所有用户上传数据

        Args:
            village_name: 村庄名称

        Returns:
            {data_type: CachedGISData} 字典
        """
        return cls._cache.get(village_name, {})

    @classmethod
    def clear_user_data(cls, village_name: str, data_type: str) -> bool:
        """
        清除指定数据类型的用户上传数据

        Args:
            village_name: 村庄名称
            data_type: 数据类型

        Returns:
            是否成功清除
        """
        village_cache = cls._cache.get(village_name, {})
        if data_type in village_cache:
            del village_cache[data_type]
            logger.info(f"[GISDataManager] 用户数据已清除: {village_name}/{data_type}")
            return True
        return False

    @classmethod
    def clear_village_data(cls, village_name: str) -> bool:
        """
        清除指定村庄的所有用户数据

        Args:
            village_name: 村庄名称

        Returns:
            是否成功清除
        """
        if village_name in cls._cache:
            del cls._cache[village_name]
            logger.info(f"[GISDataManager] 村庄数据已清除: {village_name}")
            return True
        return False

    @classmethod
    def get_data_status(cls, village_name: str) -> Dict[str, Any]:
        """
        获取指定村庄的 GIS 数据状态

        Args:
            village_name: 村庄名称

        Returns:
            数据状态字典，包含：
            - village_name: 村庄名称
            - user_uploaded: 已上传的数据类型列表
            - cached: 缓存的数据类型列表
            - missing: 缺失的数据类型列表
            - metadata: 各数据类型的元数据
        """
        village_cache = cls._cache.get(village_name, {})

        user_uploaded = list(village_cache.keys())

        # 计算缺失的数据类型（排除 custom）
        required_types = ['boundary', 'water', 'road', 'residential', 'poi']
        missing = [t for t in required_types if t not in user_uploaded]

        # 获取各数据类型的元数据
        metadata = {}
        for data_type, cached in village_cache.items():
            metadata[data_type] = {
                'file_name': cached.metadata.get('file_name', ''),
                'feature_count': cached.metadata.get('feature_count', 0),
                'uploaded_at': cached.uploaded_at,
                'source': cached.source,
            }

        return {
            'village_name': village_name,
            'user_uploaded': user_uploaded,
            'cached': user_uploaded,  # 当前 user_uploaded = cached
            'missing': missing,
            'metadata': metadata,
        }

    @classmethod
    def has_user_data(cls, village_name: str, data_type: str) -> bool:
        """
        检查是否有用户上传数据

        Args:
            village_name: 村庄名称
            data_type: 数据类型

        Returns:
            是否存在用户上传数据
        """
        village_cache = cls._cache.get(village_name, {})
        return data_type in village_cache

    @classmethod
    def get_geojson(cls, village_name: str, data_type: str) -> Optional[Dict[str, Any]]:
        """
        直接获取 GeoJSON 数据（便捷方法）

        Args:
            village_name: 村庄名称
            data_type: 数据类型

        Returns:
            GeoJSON 字典或 None
        """
        cached = cls.get_user_data(village_name, data_type)
        return cached.geojson if cached else None


# 便捷导出
__all__ = ['GISDataManager', 'CachedGISData']