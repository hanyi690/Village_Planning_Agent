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
from .dependency_calculator import (
    calculate_waves,
    get_wave_dimensions,
    get_total_waves,
    get_downstream_dependencies,
    get_impact_tree,
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
    # 从 dependency_calculator 导入的内容
    'calculate_waves',
    'get_wave_dimensions',
    'get_total_waves',
    'get_downstream_dependencies',
    'get_impact_tree',
]