"""
配置模块

包含 GIS 配置、YAML 配置加载器、依赖计算器等。
"""

from .gis_config import GISConfig, get_village_buffer, get_township_buffer

# 从 loader 导入的内容（新实现）
from .loader import (
    load_config,
    PlanningConfig,
    PhaseConfig,
    DimensionConfig,
    get_phase_by_id,
    get_dimension_by_key,
    get_dimension_config,
    get_dimension_name,
    list_dimensions,
    get_layer_dimensions,
    get_dimension_layer,
    dimension_exists,
    get_analysis_dimension_names,
    get_concept_dimension_names,
    get_detailed_dimension_names,
    filter_reports_by_dependency,
)

# 从 dependency_calculator 导入的内容（新实现）
from .dependency_calculator import (
    calculate_waves,
    get_wave_dimensions,
    get_total_waves,
    get_downstream_dependencies,
    get_impact_tree,
    get_analysis_to_concept_mapping,
    get_concept_to_detailed_mapping,
    get_full_dependency_chain,
    get_full_dependency_chain_func,
    get_execution_wave,
    check_detailed_dependencies_ready,
    get_revision_wave_dimensions,
    get_wave_config,
)

# DIMENSIONS_METADATA 兼容（从 YAML 加载）
def _get_dimensions_metadata():
    """获取维度元数据字典（兼容旧 API）"""
    from .loader import _get_cached_config
    config = _get_cached_config()
    metadata = {}
    for phase in config.phases:
        for dim in phase.dimensions:
            metadata[dim.key] = {
                "key": dim.key,
                "name": dim.name,
                "layer": int(phase.id.replace("layer", "")),
                "tools": dim.tools,
                "rag_query": dim.rag_query,
            }
    return metadata

DIMENSIONS_METADATA = _get_dimensions_metadata()

__all__ = [
    'GISConfig',
    'get_village_buffer',
    'get_township_buffer',
    # 从 loader 导入的内容
    'load_config',
    'PlanningConfig',
    'PhaseConfig',
    'DimensionConfig',
    'get_phase_by_id',
    'get_dimension_by_key',
    'get_dimension_config',
    'get_dimension_name',
    'list_dimensions',
    'get_layer_dimensions',
    'get_dimension_layer',
    'dimension_exists',
    'get_analysis_dimension_names',
    'get_concept_dimension_names',
    'get_detailed_dimension_names',
    'filter_reports_by_dependency',
    # 从 dependency_calculator 导入的内容
    'calculate_waves',
    'get_wave_dimensions',
    'get_total_waves',
    'get_downstream_dependencies',
    'get_impact_tree',
    'get_analysis_to_concept_mapping',
    'get_concept_to_detailed_mapping',
    'get_full_dependency_chain',
    'get_full_dependency_chain_func',
    'get_execution_wave',
    'check_detailed_dependencies_ready',
    'get_revision_wave_dimensions',
    'get_wave_config',
    # 兼容
    'DIMENSIONS_METADATA',
]