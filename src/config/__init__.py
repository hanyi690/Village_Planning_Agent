"""
配置模块

包含维度元数据、GIS 配置等。
"""

from .dimension_metadata import *
from .gis_config import GISConfig, get_village_buffer, get_township_buffer

__all__ = [
    'GISConfig',
    'get_village_buffer',
    'get_township_buffer',
    # 从 dimension_metadata 导入的内容
    'DIMENSIONS_METADATA',
    'get_dimension_config',
    'list_dimensions',
]