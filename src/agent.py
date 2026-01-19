"""
村庄规划 Agent - 接口层

提供统一的接口访问村庄规划功能。

## 接口说明

### 主要接口
- `run_village_planning()` - 完整规划流程（推荐）
- `run_analysis_only()` - 仅现状分析
- `quick_analysis()` - 快速分析
- `quick_planning()` - 快速规划

### 旧版接口（已弃用）
- `run_task()` - 旧版单一任务接口
"""

from typing import Dict, Any
import warnings

# 导入新版接口
from .main_graph import run_village_planning as _run_main_graph
from .subgraphs.analysis_subgraph import call_analysis_subgraph

# 导入配置
from .core.config import OPENAI_API_KEY, LLM_MODEL, MAX_TOKENS
from .utils.logger import get_logger
import os

logger = get_logger(__name__)

# 确保 OPENAI_API_KEY 在环境中可用
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# ==========================================
# 新版接口（推荐使用）
# ==========================================

def run_village_planning(
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    need_human_review: bool = False,
    stream_mode: bool = False
) -> Dict[str, Any]:
    """
    执行村庄规划主流程（新版接口）

    使用层级化 LangGraph 架构，包含三层规划流程：
    1. 现状分析（10个维度并行）
    2. 规划思路生成
    3. 详细规划方案

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据（结构化文本）
        task_description: 规划任务描述
        constraints: 约束条件
        need_human_review: 是否需要人工审核
        stream_mode: 是否使用流式输出

    Returns:
        Dict 包含：
        - success (bool): 是否成功
        - final_output (str): 最终规划成果
        - analysis_report (str): 现状分析报告
        - planning_concept (str): 规划思路
        - detailed_plan (str): 详细规划方案
        - all_layers_completed (bool): 所有层级是否完成

    Example:
        >>> result = run_village_planning(
        ...     project_name="某某村",
        ...     village_data="人口：1200人\\n面积：5.2平方公里",
        ...     task_description="制定乡村振兴规划"
        ... )
        >>> print(result['final_output'])
    """
    return _run_main_graph(
        project_name=project_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints,
        need_human_review=need_human_review,
        stream_mode=stream_mode
    )


def run_analysis_only(
    project_name: str,
    village_data: str
) -> Dict[str, Any]:
    """
    仅执行现状分析（新版接口）

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据

    Returns:
        Dict 包含：
        - success (bool): 是否成功
        - analysis_report (str): 现状分析报告

    Example:
        >>> result = run_analysis_only("某某村", village_data)
        >>> print(result['analysis_report'])
    """
    logger.info(f"[Agent] 执行现状分析: {project_name}")
    return call_analysis_subgraph(
        raw_data=village_data,
        project_name=project_name
    )


# ==========================================
# 便捷接口
# ==========================================

def quick_analysis(village_data: str, project_name: str = "村庄") -> str:
    """
    快速分析村庄现状

    便捷接口，直接返回分析报告文本。

    Args:
        village_data: 村庄数据
        project_name: 村庄名称

    Returns:
        str: 分析报告文本
    """
    result = run_analysis_only(project_name, village_data)
    return result.get("analysis_report", "分析失败")


def quick_planning(project_name: str, village_data: str, task: str = "制定村庄规划") -> str:
    """
    快速生成村庄规划

    便捷接口，直接返回规划成果文本。

    Args:
        project_name: 村庄名称
        village_data: 村庄数据
        task: 规划任务

    Returns:
        str: 规划成果文本
    """
    result = run_village_planning(
        project_name=project_name,
        village_data=village_data,
        task_description=task
    )
    return result.get("final_output", "规划失败")


# ==========================================
# 旧版接口（已弃用）
# ==========================================

def run_task(task: str, constraints: Dict = None, use_knowledge: bool = True) -> str:
    """
    旧版接口：执行单一任务（已弃用）

    ⚠️ **已弃用**：请迁移到 `run_village_planning()` 以获得更好的性能和功能。

    迁移指南：
    ```python
    # 旧版（已弃用）
    result = run_task("制定村庄规划")

    # 新版（推荐）
    result = run_village_planning(
        project_name="村庄",
        village_data=village_data,
        task_description="制定村庄规划"
    )
    ```

    详见 MIGRATION_GUIDE.md

    Args:
        task: 任务描述
        constraints: 约束条件（字典）
        use_knowledge: 是否使用知识库

    Returns:
        str: 任务执行结果
    """
    # 发出迁移提示
    warnings.warn(
        "run_task() 已弃用，请迁移到 run_village_planning()。"
        "详见 MIGRATION_GUIDE.md 了解迁移步骤。",
        DeprecationWarning,
        stacklevel=2
    )

    logger.warning(f"[Agent-旧版] 使用已弃用的接口: {task}")

    # 简化版实现，仅返回提示信息
    return (
        "⚠️ run_task() 接口已弃用。\n\n"
        "请使用新版接口 run_village_planning() 以获得：\n"
        "  • 10个维度的专业分析\n"
        "  • 7.5倍的性能提升\n"
        "  • 更好的结果质量\n\n"
        "快速迁移示例：\n"
        "```python\n"
        "from src.agent import run_village_planning\n"
        "result = run_village_planning(\n"
        "    project_name='村庄',\n"
        "    village_data=village_data,\n"
        "    task_description='制定村庄规划'\n"
        ")\n"
        "```\n\n"
        "详见 MIGRATION_GUIDE.md"
    )


# ==========================================
# 版本信息
# ==========================================

__version__ = "2.0.0"
__architecture__ = "hierarchical-langgraph"

# 导出列表
__all__ = [
    # 新版接口（推荐）
    "run_village_planning",
    "run_analysis_only",
    "quick_analysis",
    "quick_planning",

    # 旧版接口（已弃用）
    "run_task",

    # 版本信息
    "__version__",
    "__architecture__",
]
