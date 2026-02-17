"""
维度规划器层

提供统一的规划器架构，支持所有 28 个维度。

架构：
- UnifiedPlannerBase: 统一基类（LLM调用、错误处理、RAG、流式输出）
- GenericPlanner: 通用规划器，支持 Layer 1/2/3 所有维度
- GenericPlannerFactory: 统一工厂入口

已废弃（保留向后兼容导入）：
- AnalysisPlannerFactory, ConceptPlannerFactory, DetailedPlannerFactory
"""

# 统一架构（推荐使用）
from .unified_base_planner import UnifiedPlannerBase
from .generic_planner import GenericPlanner, GenericPlannerFactory

# 向后兼容：将旧工厂类名映射到 GenericPlannerFactory
AnalysisPlannerFactory = GenericPlannerFactory
ConceptPlannerFactory = GenericPlannerFactory
DetailedPlannerFactory = GenericPlannerFactory

__all__ = [
    # 统一架构
    "UnifiedPlannerBase",
    "GenericPlanner",
    "GenericPlannerFactory",

    # 向后兼容（已废弃，建议迁移到 GenericPlannerFactory）
    "AnalysisPlannerFactory",
    "ConceptPlannerFactory",
    "DetailedPlannerFactory",
]