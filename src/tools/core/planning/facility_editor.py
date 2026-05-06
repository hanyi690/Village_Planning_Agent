"""
Facility Editor - 设施点编辑模块

提供设施点创建、发展轴创建、图层合并等功能。
"""

# 从原始 vector_editor 导入功能（拆分迁移阶段）
from ..vector_editor import (
    create_facility_points,
    create_development_axis,
    merge_vector_layers,
    format_vector_result,
    FACILITY_STATUS,
)

__all__ = [
    'create_facility_points',
    'create_development_axis',
    'merge_vector_layers',
    'format_vector_result',
    'FACILITY_STATUS',
]