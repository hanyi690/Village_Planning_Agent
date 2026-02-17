"""
报告生成工具 - 按需生成综合报告

此模块提供从维度报告字典生成综合报告的功能，
用于替代状态中存储冗余的综合报告字段。
"""

from datetime import datetime
from typing import Dict, Optional

from .output_manager import OutputManager
from ..config.dimension_metadata import (
    get_analysis_dimension_names,
    get_concept_dimension_names,
    get_detailed_dimension_names,
)
from .logger import get_logger

logger = get_logger(__name__)


def generate_combined_report(
    dimension_reports: Dict[str, str],
    project_name: str,
    layer_number: int,
    report_type: Optional[str] = None
) -> str:
    """
    从维度报告字典生成综合报告

    Args:
        dimension_reports: 维度报告字典 {dimension_key: content}
        project_name: 项目名称
        layer_number: 层级编号 (1=现状分析, 2=规划思路, 3=详细规划)
        report_type: 报告类型名称（可选，默认根据层级自动确定）

    Returns:
        拼接后的综合报告
    """
    if not dimension_reports:
        return f"# {project_name} {report_type or '报告'}\n\n暂无内容\n"

    # 确定报告类型名称
    if report_type is None:
        report_type = {
            1: "现状分析",
            2: "规划思路",
            3: "详细规划"
        }.get(layer_number, "报告")

    # 获取维度名称映射
    dimension_names_map = _get_dimension_names_map(layer_number)

    # 生成报告头部
    report = f"# {project_name} {report_type}报告\n\n"

    # 使用标准顺序（而非字母顺序）
    standard_order = OutputManager._get_dimension_order(layer_number)

    # 按标准顺序拼接维度报告
    for dimension_key in standard_order:
        if dimension_key not in dimension_reports:
            continue
        content = dimension_reports[dimension_key]
        display_name = dimension_names_map.get(dimension_key, dimension_key)

        # 检测内容是否已包含"## 标题"
        if content.startswith("## "):
            report += f"{content}\n\n"
        else:
            report += f"## {display_name}\n\n{content}\n\n"

    report += f"---\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

    return report


def generate_analysis_report(
    dimension_reports: Dict[str, str],
    project_name: str
) -> str:
    """生成现状分析综合报告 (Layer 1)"""
    return generate_combined_report(
        dimension_reports=dimension_reports,
        project_name=project_name,
        layer_number=1,
        report_type="现状分析"
    )


def generate_concept_report(
    dimension_reports: Dict[str, str],
    project_name: str
) -> str:
    """生成规划思路综合报告 (Layer 2)"""
    return generate_combined_report(
        dimension_reports=dimension_reports,
        project_name=project_name,
        layer_number=2,
        report_type="规划思路"
    )


def generate_detailed_plan_report(
    dimension_reports: Dict[str, str],
    project_name: str
) -> str:
    """生成详细规划综合报告 (Layer 3)"""
    return generate_combined_report(
        dimension_reports=dimension_reports,
        project_name=project_name,
        layer_number=3,
        report_type="详细规划"
    )


def _get_dimension_names_map(layer_number: int) -> Dict[str, str]:
    """
    获取维度的英文名到中文名的映射

    Args:
        layer_number: 层级编号

    Returns:
        英文键到中文名称的映射字典
    """
    mapping = {
        1: get_analysis_dimension_names(),
        2: get_concept_dimension_names(),
        3: get_detailed_dimension_names(),
    }
    return mapping.get(layer_number, {})


# 向后兼容的别名
def get_combined_report_from_dimensions(
    dimension_reports: Dict[str, str],
    project_name: str,
    layer_number: int
) -> str:
    """
    向后兼容函数：从维度报告生成综合报告

    Deprecated: 请使用 generate_combined_report()
    """
    return generate_combined_report(
        dimension_reports=dimension_reports,
        project_name=project_name,
        layer_number=layer_number
    )
