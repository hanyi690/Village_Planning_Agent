"""
报告工具函数

提供维度报告的动态拼接生成综合报告的功能。
用于替代存储冗余的综合报告字段，节省存储空间。

统一命名规范：
- Layer 1: analysis_reports (现状分析各维度报告)
- Layer 2: concept_reports (规划思路各维度报告)  
- Layer 3: detail_reports (详细规划各维度报告)
"""

from typing import Dict, Optional
from datetime import datetime


def generate_combined_report(
    dimension_reports: Dict[str, str],
    project_name: str,
    layer: int,
    title_suffix: str = ""
) -> str:
    """
    从维度报告字典动态生成综合报告
    
    Args:
        dimension_reports: 维度报告字典 {dimension_key: report_content}
        project_name: 项目/村庄名称
        layer: 层级编号 (1/2/3)
        title_suffix: 标题后缀（可选）
    
    Returns:
        拼接后的综合报告字符串
    """
    if not dimension_reports:
        return f"# {project_name} {title_suffix}\n\n暂无数据"
    
    # 层级标题映射
    layer_titles = {
        1: "现状分析报告",
        2: "规划思路报告", 
        3: "详细规划报告"
    }
    
    title = layer_titles.get(layer, "规划报告")
    if title_suffix:
        title = f"{title}{title_suffix}"
    
    # 构建报告
    parts = [f"# {project_name} {title}\n"]
    
    for dim_key, report_content in dimension_reports.items():
        if report_content and report_content.strip():
            parts.append(f"\n{report_content}\n")
            parts.append("\n---\n")
    
    # 添加元数据
    parts.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    return "".join(parts)


def generate_analysis_report(
    analysis_reports: Dict[str, str],
    project_name: str
) -> str:
    """
    生成 Layer 1 现状分析综合报告
    
    Args:
        analysis_reports: 现状分析维度报告字典
        project_name: 项目名称
    
    Returns:
        现状分析综合报告
    """
    return generate_combined_report(
        dimension_reports=analysis_reports,
        project_name=project_name,
        layer=1
    )


def generate_concept_report(
    concept_reports: Dict[str, str],
    project_name: str
) -> str:
    """
    生成 Layer 2 规划思路综合报告
    
    Args:
        concept_reports: 规划思路维度报告字典
        project_name: 项目名称
    
    Returns:
        规划思路综合报告
    """
    return generate_combined_report(
        dimension_reports=concept_reports,
        project_name=project_name,
        layer=2
    )


def generate_detail_report(
    detail_reports: Dict[str, str],
    project_name: str
) -> str:
    """
    生成 Layer 3 详细规划综合报告
    
    Args:
        detail_reports: 详细规划维度报告字典
        project_name: 项目名称
    
    Returns:
        详细规划综合报告
    """
    return generate_combined_report(
        dimension_reports=detail_reports,
        project_name=project_name,
        layer=3
    )


def get_legacy_field_name(layer: int) -> str:
    """
    获取旧版综合报告字段名（用于兼容性处理）
    
    Args:
        layer: 层级编号
    
    Returns:
        旧版字段名
    """
    legacy_names = {
        1: "analysis_report",
        2: "planning_concept",
        3: "detailed_plan"
    }
    return legacy_names.get(layer, "")


def normalize_dimension_reports(
    reports: Dict[str, str],
    layer: int
) -> Dict[str, str]:
    """
    规范化维度报告字典键名
    
    处理可能存在的键名不一致问题，确保键名统一。
    
    Args:
        reports: 原始维度报告字典
        layer: 层级编号
    
    Returns:
        规范化后的维度报告字典
    """
    if not reports:
        return {}
    
    normalized = {}
    for key, value in reports.items():
        # 移除可能的前缀（如 dimension_industry -> industry）
        clean_key = key
        if layer == 3 and key.startswith("dimension_"):
            clean_key = key[len("dimension_"):]
        
        if value and value.strip():
            normalized[clean_key] = value
    
    return normalized


__all__ = [
    "generate_combined_report",
    "generate_analysis_report",
    "generate_concept_report", 
    "generate_detail_report",
    "get_legacy_field_name",
    "normalize_dimension_reports",
]
