"""
Village Planning Agent - 子图模块

Prompts 模板（核心内容）：
- analysis_prompts: 现状分析 Prompt 模板
- concept_prompts: 规划思路 Prompt 模板
- detailed_plan_prompts: 详细规划 Prompt 模板
- spatial_layout_prompts: 空间布局解析 Prompt 模板

注意：
1. revision_subgraph 已合并到 orchestration/nodes/revision_node.py
2. analysis_subgraph、concept_subgraph、detailed_plan_subgraph 已被
   新的维度节点 (dimension_node.py) 替代
"""

# 向后兼容：从 revision_node 导入修复子图相关内容
from ..orchestration.nodes.revision_node import (
    create_revision_subgraph,
    call_revision_subgraph,
    RevisionState,
    RevisionDimensionState,
)

# 空间布局解析 Prompt
from .spatial_layout_prompts import (
    SPATIAL_LAYOUT_PARSE_PROMPT,
    format_parse_prompt,
    ZONE_TYPE_COLORS,
    FACILITY_STATUS_COLORS,
)

__all__ = [
    # 向后兼容导出
    'create_revision_subgraph',
    'call_revision_subgraph',
    'RevisionState',
    'RevisionDimensionState',
    # 空间布局解析
    'SPATIAL_LAYOUT_PARSE_PROMPT',
    'format_parse_prompt',
    'ZONE_TYPE_COLORS',
    'FACILITY_STATUS_COLORS',
]