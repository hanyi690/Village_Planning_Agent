"""
村庄规划 Agent - 接口层

提供统一的接口访问村庄规划功能。
"""

from typing import Dict, Any, Union
from pathlib import Path
import asyncio

from .orchestration.main_graph import run_unified_planning, run_unified_planning_async
from .orchestration.state import create_initial_state, get_layer_dimensions
from .orchestration.nodes.dimension_node import analyze_dimension_for_send
from .tools.file_manager import VillageDataManager, read_village_data as _read_village_data
from .core.config import OPENAI_API_KEY, LLM_MODEL, MAX_TOKENS
from .utils.logger import get_logger
import os

logger = get_logger(__name__)

if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY


def _load_village_data(village_data: Union[str, Path]) -> str:
    """智能加载村庄数据"""
    manager = VillageDataManager()
    result = manager.load_data(village_data)
    if result["success"]:
        logger.info(f"[Agent] 从文件加载数据：{result['metadata'].get('filename', 'unknown')}")
        return result["content"]
    return village_data if isinstance(village_data, str) else str(village_data)


def run_village_planning(
    project_name: str,
    village_data: Union[str, Path],
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束"
) -> Dict[str, Any]:
    """
    执行村庄规划主流程

    使用 Router Agent 架构，包含三层规划流程：
    1. 现状分析（12 维度并行）
    2. 规划思路生成
    3. 详细规划方案

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据（文件路径或结构化文本）
        task_description: 规划任务描述
        constraints: 约束条件

    Returns:
        包含规划结果的字典

    Example:
        >>> result = run_village_planning(
        ...     project_name="某某村",
        ...     village_data="data/village.pdf",
        ...     task_description="制定乡村振兴规划"
        ... )
    """
    village_data = _load_village_data(village_data)

    return run_unified_planning(
        session_id=project_name,
        project_name=project_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints
    )


async def run_village_planning_async(
    project_name: str,
    village_data: Union[str, Path],
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束"
) -> Dict[str, Any]:
    """异步执行村庄规划主流程"""
    village_data = _load_village_data(village_data)

    return await run_unified_planning_async(
        session_id=project_name,
        project_name=project_name,
        village_data=village_data,
        task_description=task_description,
        constraints=constraints
    )


def run_analysis_only(
    project_name: str,
    village_data: str
) -> Dict[str, Any]:
    """
    仅执行现状分析（Layer 1）

    Args:
        project_name: 项目/村庄名称
        village_data: 村庄基础数据

    Returns:
        包含分析报告的字典
    """
    logger.info(f"[Agent] 执行现状分析：{project_name}")

    async def _run():
        dimensions = get_layer_dimensions(1)
        reports = {}

        config = {
            "village_data": village_data,
            "task_description": "",
            "constraints": "无特殊约束",
        }

        for dim in dimensions:
            dim_state = {
                "dimension_key": dim,
                "session_id": project_name,
                "project_name": project_name,
                "config": config,
                "reports": {"layer1": reports, "layer2": {}, "layer3": {}},
            }

            result = await analyze_dimension_for_send(dim_state)
            if result.get("dimension_results"):
                dim_result = result["dimension_results"][0]
                if dim_result.get("success"):
                    reports[dim] = dim_result.get("result", "")

        return reports

    reports = asyncio.run(_run())

    return {
        "success": len(reports) > 0,
        "analysis_reports": reports,
    }


def quick_analysis(village_data: str, project_name: str = "村庄") -> str:
    """快速分析村庄现状"""
    result = run_analysis_only(project_name, village_data)
    reports = result.get("analysis_reports", {})

    if not reports:
        return "分析失败"

    lines = [f"# {project_name} 现状分析\n"]
    for dim, content in reports.items():
        lines.append(f"\n## {dim}\n\n{content}\n")

    return "\n".join(lines)


def quick_planning(project_name: str, village_data: str, task: str = "制定村庄规划") -> str:
    """快速生成村庄规划"""
    result = run_village_planning(
        project_name=project_name,
        village_data=village_data,
        task_description=task
    )

    reports = result.get("reports", {})
    layer3_reports = reports.get("layer3", {})

    if not layer3_reports:
        return "规划失败"

    lines = [f"# {project_name} 规划成果\n"]
    for dim, content in layer3_reports.items():
        lines.append(f"\n## {dim}\n\n{content}\n")

    return "\n".join(lines)


def read_village_data(source: Union[str, Path]) -> str:
    """从文件读取村庄数据"""
    return _read_village_data(source)


__version__ = "3.0.0"
__architecture__ = "router-agent"

__all__ = [
    "run_village_planning",
    "run_village_planning_async",
    "run_analysis_only",
    "quick_analysis",
    "quick_planning",
    "VillageDataManager",
    "read_village_data",
    "__version__",
    "__architecture__",
]