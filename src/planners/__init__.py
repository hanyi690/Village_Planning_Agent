"""
维度规划器层

提供统一的规划器架构，支持所有 28 个维度。

架构：
- GenericPlanner: 通用规划器，支持 Layer 1/2/3 所有维度
- GenericPlannerFactory: 统一工厂入口
- StreamingCallback: 流式输出回调

已整合原 UnifiedPlannerBase 的功能。

向后兼容别名：
- AnalysisPlannerFactory, ConceptPlannerFactory, DetailedPlannerFactory
"""

from .generic_planner import (
    GenericPlanner,
    GenericPlannerFactory,
    StreamingCallback,
    # 向后兼容
    AnalysisPlannerFactory,
    ConceptPlannerFactory,
    DetailedPlannerFactory,
)

__all__ = [
    # 核心类
    "GenericPlanner",
    "GenericPlannerFactory",
    "StreamingCallback",

    # 向后兼容（已废弃，建议迁移到 GenericPlannerFactory）
    "AnalysisPlannerFactory",
    "ConceptPlannerFactory",
    "DetailedPlannerFactory",
]