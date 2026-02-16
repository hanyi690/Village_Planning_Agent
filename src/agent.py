"""
村庄规划 Agent - 接口层

提供统一的接口访问村庄规划功能。

## 接口说明

### 主要接口
- `run_village_planning()` - 完整规划流程（推荐）
- `run_analysis_only()` - 仅现状分析
- `run_concept_only()` - 仅规划思路（新增）
- `quick_analysis()` - 快速分析
- `quick_planning()` - 快速规划

### 文件工具
- `VillageDataManager` - 统一文件管理工具
- `read_village_data()` - 便捷数据读取接口
"""

from typing import Dict, Any, Union
from pathlib import Path
import warnings

# 导入新版接口
from .orchestration.main_graph import run_village_planning as _run_main_graph
from .subgraphs.analysis_subgraph import call_analysis_subgraph
from .subgraphs.concept_subgraph import call_concept_subgraph
from .tools.file_manager import VillageDataManager, read_village_data as _read_village_data

# 导入配置
from .core.config import (
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    DEFAULT_ENABLE_REVIEW,
    DEFAULT_STREAM_MODE,
    DEFAULT_STEP_MODE,
)
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
    village_data: Union[str, Path],
    task_description: str = DEFAULT_TASK_DESCRIPTION,
    constraints: str = DEFAULT_CONSTRAINTS,
    need_human_review: bool = DEFAULT_ENABLE_REVIEW,
    stream_mode: bool = DEFAULT_STREAM_MODE,
    output_manager=None,
    custom_output_path: str = None,
    step_mode: bool = DEFAULT_STEP_MODE,
    step_level: str = "layer"
) -> Dict[str, Any]:
    """
    执行村庄规划主流程（新版接口）

    使用层级化 LangGraph 架构，包含三层规划流程：
    1. 现状分析（10个维度并行）
    2. 规划思路生成
    3. 详细规划方案

    village_data 现在支持：
    - 文件路径（自动检测格式：txt, pdf, docx等）
    - 直接文本数据

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据（文件路径或结构化文本）
        task_description: 规划任务描述
        constraints: 约束条件
        need_human_review: 是否需要人工审核
        stream_mode: 是否使用流式输出
        output_manager: 输出管理器实例（可选）
        custom_output_path: 自定义输出路径（可选）
        step_mode: 是否启用逐步执行模式（新增）
        step_level: 逐步执行的暂停级别（layer/dimension/skill）（新增）

    Returns:
        Dict 包含：
        - success (bool): 是否成功
        - final_output (str): 最终规划成果
        - analysis_report (str): 现状分析报告
        - planning_concept (str): 规划思路
        - detailed_plan (str): 详细规划方案
        - all_layers_completed (bool): 所有层级是否完成
        - output_manager: 输出管理器实例
        - final_output_path: 最终报告路径

    Example:
        >>> # 使用文件路径
        >>> result = run_village_planning(
        ...     project_name="某某村",
        ...     village_data="data/village.pdf",
        ...     task_description="制定乡村振兴规划"
        ... )
        >>>
        >>> # 使用直接文本
        >>> result = run_village_planning(
        ...     project_name="某某村",
        ...     village_data="人口：1200人\\n面积：5.2平方公里",
        ...     task_description="制定乡村振兴规划"
        ... )
        >>> print(result['final_output'])
    """
    # 智能加载：如果看起来像文件路径，尝试加载
    manager = VillageDataManager()
    result = manager.load_data(village_data)
    if result["success"]:
        village_data = result["content"]
        logger.info(f"[Agent] 从文件加载数据: {result['metadata'].get('filename', 'unknown')}")

    return _run_main_graph(
        project_name=project_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints,
        need_human_review=need_human_review,
        stream_mode=stream_mode,
        output_manager=output_manager,
        custom_output_path=custom_output_path,
        step_mode=step_mode,
        step_level=step_level
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


def run_concept_only(
    project_name: str,
    village_data: Union[str, Path],
    task_description: str = "制定村庄规划思路"
) -> Dict[str, Any]:
    """
    仅执行规划思路分析（Layer 1 + Layer 2）

    执行现状分析后生成规划思路，不包含详细规划。

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据（文件路径或结构化文本）
        task_description: 规划任务描述

    Returns:
        Dict 包含：
        - success (bool): 是否成功
        - analysis_report (str): 现状分析报告
        - concept_report (str): 规划思路报告

    Example:
        >>> result = run_concept_only("某某村", "data/village.txt")
        >>> print(result['concept_report'])
    """
    logger.info(f"[Agent] 执行规划思路分析: {project_name}")

    # 智能加载数据
    manager = VillageDataManager()
    load_result = manager.load_data(village_data)
    if load_result["success"]:
        village_data = load_result["content"]

    # 执行现状分析
    analysis_result = call_analysis_subgraph(
        raw_data=village_data,
        project_name=project_name
    )

    if not analysis_result["success"]:
        return {
            "success": False,
            "analysis_report": "",
            "concept_report": "",
            "error": "现状分析失败"
        }

    # 执行规划思路生成
    concept_result = call_concept_subgraph(
        project_name=project_name,
        analysis_report=analysis_result["analysis_report"],
        dimension_reports=analysis_result.get("dimension_reports", {}),
        task_description=task_description,
        constraints="无特殊约束"
    )

    return {
        "success": concept_result["success"],
        "analysis_report": analysis_result["analysis_report"],
        "concept_report": concept_result.get("concept_report", ""),
        "error": concept_result.get("error", "")
    }


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
# 文件工具接口
# ==========================================

def read_village_data(source: Union[str, Path]) -> str:
    """
    从文件读取村庄数据（兼容旧接口）

    建议使用 VillageDataManager.load_data() 获取更多功能

    Args:
        source: 文件路径或文本内容

    Returns:
        str: 提取的文本内容

    Example:
        >>> data = read_village_data("data/village.txt")
        >>> print(data)
    """
    return _read_village_data(source)


# ==========================================
# 版本信息
# ==========================================

__version__ = "2.1.0"
__architecture__ = "hierarchical-langgraph"

# 导出列表
__all__ = [
    # 新版接口（推荐）
    "run_village_planning",
    "run_analysis_only",
    "run_concept_only",       # 新增
    "quick_analysis",
    "quick_planning",

    # 文件工具
    "VillageDataManager",     # 新增
    "read_village_data",      # 新增

    # 版本信息
    "__version__",
    "__architecture__",
]
