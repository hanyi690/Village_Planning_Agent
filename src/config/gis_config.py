"""
GIS 数据获取配置

提供缓冲区大小、数据类型配置等 GIS 相关参数。
支持村级和乡镇级两种规划精度。

使用方式:
    from src.config.gis_config import GISConfig

    # 获取村级水系数据缓冲区
    buffer_km = GISConfig.get_buffer('village', 'water')

    # 获取默认配置
    default_buffer = GISConfig.get_default_buffer('village')
"""

from typing import Dict, Any, Optional, Literal


class GISConfig:
    """GIS 数据获取配置类"""

    # 按规划级别设置缓冲区范围
    BUFFER_CONFIG: Dict[str, Dict[str, float]] = {
        'village': {
            'default_km': 1.0,    # 村级默认 1km
            'min_km': 0.5,        # 最小 500m
            'max_km': 2.0,        # 最大 2km
        },
        'township': {
            'default_km': 3.0,    # 乡镇级默认 3km
            'min_km': 2.0,        # 最小 2km
            'max_km': 5.0,        # 最大 5km
        }
    }

    # 数据类型精细化配置（覆盖默认缓冲区）
    DATA_TYPE_CONFIG: Dict[str, Dict[str, Any]] = {
        'boundary': {
            'buffer_km': 0.5,    # 行政边界精确范围
            'description': '行政边界数据',
        },
        'water': {
            'buffer_km': 1.0,    # 水系稍大范围
            'description': '河流、湖泊等水系数据',
        },
        'road': {
            'buffer_km': 0.8,    # 道路适中范围
            'description': '道路网络数据',
        },
        'residential': {
            'buffer_km': 1.0,    # 居民点规划范围
            'description': '居民点分布数据',
        },
        'poi': {
            'buffer_km': 1.5,    # POI 设施范围
            'description': '公共服务设施点位数据',
        },
        'land_use': {
            'buffer_km': 1.0,    # 土地利用范围
            'description': '土地利用类型数据',
        },
        'elevation': {
            'buffer_km': 0.5,    # 高程数据范围
            'description': '地形高程数据',
        },
    }

    # 图层样式配置（用于前端渲染）
    LAYER_COLORS: Dict[str, Dict[str, str]] = {
        'function_zone': {
            '种植区': '#A3C1AD',
            '居住组团': '#F5E6D3',
            '产业区': '#FFE4B5',
            '生态区': '#90EE90',
            '文化区': '#DDA0DD',
            'default': '#CCCCCC',
        },
        'facility_point': {
            '学校': '#4169E1',
            '医院': '#DC143C',
            '超市': '#32CD32',
            '工厂': '#FF8C00',
            '文化设施': '#9370DB',
            'default': '#808080',
        },
        'development_axis': {
            '发展主轴': '#FF6B6B',
            '发展次轴': '#FFB347',
            'default': '#FF0000',
        },
        'sensitivity_zone': {
            '高敏感区': '#FF4444',
            '中敏感区': '#FFAA44',
            '低敏感区': '#44AA44',
            'default': '#888888',
        },
        'boundary': {
            '行政边界': '#333333',
            '规划范围': '#0066CC',
            'default': '#666666',
        },
    }

    # 图层透明度配置
    LAYER_OPACITY: Dict[str, float] = {
        'function_zone': 0.4,
        'facility_point': 0.8,
        'development_axis': 1.0,
        'sensitivity_zone': 0.5,
        'boundary': 1.0,
        'isochrone': 0.3,
    }

    @classmethod
    def get_buffer(
        cls,
        planning_level: Literal['village', 'township'],
        data_type: Optional[str] = None
    ) -> float:
        """
        获取缓冲区大小（公里）

        优先使用数据类型特定配置，否则使用规划级别默认配置。

        Args:
            planning_level: 规划级别 ('village' 或 'township')
            data_type: 数据类型（可选，如 'boundary', 'water' 等）

        Returns:
            缓冲区大小（公里）
        """
        # 优先使用数据类型特定配置
        if data_type and data_type in cls.DATA_TYPE_CONFIG:
            return cls.DATA_TYPE_CONFIG[data_type]['buffer_km']

        # 使用规划级别默认配置
        level_config = cls.BUFFER_CONFIG.get(planning_level, cls.BUFFER_CONFIG['village'])
        return level_config['default_km']

    @classmethod
    def get_default_buffer(cls, planning_level: Literal['village', 'township']) -> float:
        """
        获取规划级别的默认缓冲区大小

        Args:
            planning_level: 规划级别 ('village' 或 'township')

        Returns:
            默认缓冲区大小（公里）
        """
        level_config = cls.BUFFER_CONFIG.get(planning_level, cls.BUFFER_CONFIG['village'])
        return level_config['default_km']

    @classmethod
    def get_buffer_range(cls, planning_level: Literal['village', 'township']) -> Dict[str, float]:
        """
        获取缓冲区范围配置

        Args:
            planning_level: 规划级别 ('village' 或 'township')

        Returns:
            {'min_km': float, 'max_km': float, 'default_km': float}
        """
        return cls.BUFFER_CONFIG.get(planning_level, cls.BUFFER_CONFIG['village'])

    @classmethod
    def get_layer_color(cls, layer_type: str, subtype: Optional[str] = None) -> str:
        """
        获取图层颜色

        Args:
            layer_type: 图层类型（如 'function_zone', 'facility_point'）
            subtype: 子类型（如 '种植区', '学校'）

        Returns:
            颜色值（十六进制格式）
        """
        colors = cls.LAYER_COLORS.get(layer_type, {})
        if subtype and subtype in colors:
            return colors[subtype]
        return colors.get('default', '#CCCCCC')

    @classmethod
    def get_layer_opacity(cls, layer_type: str) -> float:
        """
        获取图层透明度

        Args:
            layer_type: 图层类型

        Returns:
            透明度值（0.0 - 1.0）
        """
        return cls.LAYER_OPACITY.get(layer_type, 0.5)

    @classmethod
    def get_all_data_types(cls) -> list:
        """
        获取所有支持的数据类型列表

        Returns:
            数据类型键名列表
        """
        return list(cls.DATA_TYPE_CONFIG.keys())

    @classmethod
    def get_data_type_description(cls, data_type: str) -> str:
        """
        获取数据类型描述

        Args:
            data_type: 数据类型键名

        Returns:
            描述文本
        """
        config = cls.DATA_TYPE_CONFIG.get(data_type, {})
        return config.get('description', data_type)


# 便捷函数
def get_village_buffer(data_type: Optional[str] = None) -> float:
    """获取村级规划缓冲区大小"""
    return GISConfig.get_buffer('village', data_type)


def get_township_buffer(data_type: Optional[str] = None) -> float:
    """获取乡镇级规划缓冲区大小"""
    return GISConfig.get_buffer('township', data_type)


__all__ = [
    'GISConfig',
    'get_village_buffer',
    'get_township_buffer',
]