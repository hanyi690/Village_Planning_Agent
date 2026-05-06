"""
Zone Editor - 功能区编辑模块

提供功能区创建、规划边界创建、整合代理边界生成等功能。
"""

# 从原始 vector_editor 导入功能（拆分迁移阶段）
from ..vector_editor import (
    create_function_zones,
    create_planning_boundary,
    generate_integrated_proxy_boundary,
    ZONE_TYPE_DEFINITIONS,
)

__all__ = [
    'create_function_zones',
    'create_planning_boundary',
    'generate_integrated_proxy_boundary',
    'ZONE_TYPE_DEFINITIONS',
]