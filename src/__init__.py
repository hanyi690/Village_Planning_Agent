"""
村庄规划Agent - 新架构

V4.0.0 - 分层架构重构

架构层次：
- tools/: 统一工具层（遵循tool pattern）
- orchestration/: 编排层（纯业务逻辑）
- cli/: CLI层
- core/: 核心组件（LLM、配置等）
- subgraphs/: 子图（分析、规划思路、详细规划）
- utils/: 工具函数
- knowledge/: 知识库

检查点管理：统一使用 LangGraph AsyncSqliteSaver
"""

# 核心接口
from .agent import (
    run_village_planning,
    run_analysis_only,
    run_concept_only,
    quick_analysis,
    quick_planning,
    VillageDataManager,
    read_village_data,
    __version__,
    __architecture__
)

# 编排层
from .orchestration import (
    VillagePlanningState,
    run_village_planning as orchestration_run_village_planning,
    resume_from_checkpoint,
    create_village_planning_graph
)

# CLI层
from .cli import main as cli_main

# 工具层（仅导出新工具）
from .tools import (
    # 修复
    RevisionTool,
    parse_feedback,
    revise_dimension,
    revise_dimensions,
    # 文件管理
    VillageDataManager,
    read_village_data,
    # 知识库
    knowledge_query,
)

__all__ = [
    # 核心接口
    "run_village_planning",
    "run_analysis_only",
    "run_concept_only",
    "quick_analysis",
    "quick_planning",
    "__version__",
    "__architecture__",
    # 编排层
    "VillagePlanningState",
    "resume_from_checkpoint",
    "create_village_planning_graph",
    # CLI层
    "cli_main",
    # 工具层
    "RevisionTool",
    "parse_feedback",
    "revise_dimension",
    "revise_dimensions",
    # 文件管理
    "VillageDataManager",
    "read_village_data",
    # 知识库
    "knowledge_query",
]
