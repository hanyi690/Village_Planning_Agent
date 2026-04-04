"""
村庄规划 Agent - Router Agent 架构

V5.0.0 - 统一 Agent 架构重构

架构特点：
- 单一 State，消灭双写问题
- conversation_node 作为中央路由（大脑）
- Send API 实现维度并行分发
- Checkpoint 完整记录聊天+规划
"""

# 核心接口
from .agent import (
    run_village_planning,
    run_village_planning_async,
    run_analysis_only,
    quick_analysis,
    quick_planning,
    VillageDataManager,
    read_village_data,
    __version__,
    __architecture__
)

# 编排层
from .orchestration import (
    UnifiedPlanningState,
    PlanningPhase,
    create_unified_planning_graph,
    run_unified_planning,
    run_unified_planning_async,
    resume_from_checkpoint,
)

__all__ = [
    # 核心接口
    "run_village_planning",
    "run_village_planning_async",
    "run_analysis_only",
    "quick_analysis",
    "quick_planning",
    "__version__",
    "__architecture__",
    # 编排层
    "UnifiedPlanningState",
    "PlanningPhase",
    "create_unified_planning_graph",
    "run_unified_planning",
    "run_unified_planning_async",
    "resume_from_checkpoint",
    # 文件管理
    "VillageDataManager",
    "read_village_data",
]