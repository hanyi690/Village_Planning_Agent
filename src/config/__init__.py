"""
配置模块

包含维度元数据、GIS 配置、YAML 配置加载器等。
"""

from .dimension_metadata import *
from .gis_config import GISConfig, get_village_buffer, get_township_buffer
from .loader import (
    load_config,
    PlanningConfig,
    PhaseConfig,
    DimensionConfig,
    get_phase_by_id,
    get_dimension_by_key,
)

__all__ = [
    'GISConfig',
    'get_village_buffer',
    'get_township_buffer',
    # 从 dimension_metadata 导入的内容
    'DIMENSIONS_METADATA',
    'get_dimension_config',
    'list_dimensions',
    # 从 loader 导入的内容
    'load_config',
    'PlanningConfig',
    'PhaseConfig',
    'DimensionConfig',
    'get_phase_by_id',
    'get_dimension_by_key',
]