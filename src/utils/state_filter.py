"""
状态过滤工具

根据维度依赖关系，智能组装子图需要的部分状态。
"""

from typing import Dict, List, Any, Optional
from ..core.dimension_mapping import (
    ANALYSIS_TO_CONCEPT_MAPPING,
    CONCEPT_TO_DETAILED_MAPPING,
    ANALYSIS_DIMENSION_NAMES,
    CONCEPT_DIMENSION_NAMES
)
from ..utils.logger import get_logger

logger = get_logger(__name__)


def filter_analysis_report_for_concept(
    concept_dimension: str,
    full_analysis_reports: Optional[Dict[str, str]],
    full_analysis_report: str
) -> str:
    """
    为特定规划思路维度筛选相关的现状分析信息

    Args:
        concept_dimension: 规划思路维度（如 "resource_endowment"）
        full_analysis_reports: 完整的各维度分析字典 {dimension_key: report_text}
        full_analysis_report: 完整的综合报告（降级方案）

    Returns:
        筛选后的分析报告
    """
    mapping = ANALYSIS_TO_CONCEPT_MAPPING.get(concept_dimension)

    if not mapping:
        # 未找到映射，返回完整报告
        logger.warning(f"[状态筛选] 未找到 {concept_dimension} 的映射，返回完整报告")
        return full_analysis_report

    required_analyses = mapping["required_analyses"]

    # 处理 "ALL" 标记
    if "ALL" in required_analyses:
        logger.info(f"[状态筛选] {concept_dimension} 需要全部现状分析信息")
        return full_analysis_report

    # 如果没有维度字典，降级返回完整报告
    if not full_analysis_reports:
        logger.warning(f"[状态筛选] 缺少维度报告字典，返回完整报告")
        return full_analysis_report

    # 筛选相关维度
    relevant_reports = []
    for dimension_key in required_analyses:
        if dimension_key in full_analysis_reports:
            report_text = full_analysis_reports[dimension_key]
            dimension_name = ANALYSIS_DIMENSION_NAMES.get(dimension_key, dimension_key)
            relevant_reports.append(f"### {dimension_name}\n\n{report_text}\n")
        else:
            logger.warning(f"[状态筛选] 缺少维度 {dimension_key} 的报告")

    if not relevant_reports:
        # 如果没有找到任何相关报告，降级返回完整报告
        logger.warning(f"[状态筛选] 未找到 {concept_dimension} 的相关现状报告，返回完整报告")
        return full_analysis_report

    # 拼接相关维度报告
    concept_name = CONCEPT_DIMENSION_NAMES.get(concept_dimension, concept_dimension)
    filtered_report = f"# 与 {concept_name} 相关的现状分析\n\n" + "\n".join(relevant_reports)

    logger.info(f"[状态筛选] 为 {concept_dimension} 筛选了 {len(relevant_reports)} 个现状维度")

    return filtered_report


def filter_state_for_detailed_dimension(
    detailed_dimension: str,
    full_analysis_reports: Optional[Dict[str, str]],
    full_analysis_report: str,
    full_concept_reports: Optional[Dict[str, str]],
    full_concept_report: str
) -> Dict[str, str]:
    """
    为特定详细规划维度筛选相关的现状分析和规划思路信息

    Args:
        detailed_dimension: 详细规划维度（如 "industry"）
        full_analysis_reports: 完整的各维度现状分析字典
        full_analysis_report: 完整的现状综合报告（降级方案）
        full_concept_reports: 完整的各维度规划思路字典
        full_concept_report: 完整的规划思路综合报告（降级方案）

    Returns:
        包含 filtered_analysis 和 filtered_concept 的字典
    """
    mapping = CONCEPT_TO_DETAILED_MAPPING.get(detailed_dimension)

    if not mapping:
        # 未找到映射，返回完整报告
        logger.warning(f"[状态筛选] 未找到 {detailed_dimension} 的映射，返回完整报告")
        return {
            "filtered_analysis": full_analysis_report,
            "filtered_concept": full_concept_report
        }

    # 筛选现状分析
    required_analyses = mapping["required_analyses"]
    if "ALL" in required_analyses or not full_analysis_reports:
        filtered_analysis = full_analysis_report
        logger.info(f"[状态筛选] {detailed_dimension} 使用完整现状分析报告")
    else:
        relevant_reports = []
        for dimension_key in required_analyses:
            if dimension_key in full_analysis_reports:
                report_text = full_analysis_reports[dimension_key]
                dimension_name = ANALYSIS_DIMENSION_NAMES.get(dimension_key, dimension_key)
                relevant_reports.append(f"### {dimension_name}\n\n{report_text}\n")

        if relevant_reports:
            filtered_analysis = "# 相关现状分析\n\n" + "\n".join(relevant_reports)
            logger.info(f"[状态筛选] 为 {detailed_dimension} 筛选了 {len(relevant_reports)} 个现状维度")
        else:
            filtered_analysis = full_analysis_report
            logger.warning(f"[状态筛选] 未找到相关现状报告，使用完整报告")

    # 筛选规划思路
    required_concepts = mapping["required_concepts"]
    if "ALL" in required_concepts or not full_concept_reports:
        filtered_concept = full_concept_report
        logger.info(f"[状态筛选] {detailed_dimension} 使用完整规划思路报告")
    else:
        relevant_concepts = []
        for dimension_key in required_concepts:
            if dimension_key in full_concept_reports:
                concept_text = full_concept_reports[dimension_key]
                concept_name = CONCEPT_DIMENSION_NAMES.get(dimension_key, dimension_key)
                relevant_concepts.append(f"### {concept_name}\n\n{concept_text}\n")

        if relevant_concepts:
            filtered_concept = "# 相关规划思路\n\n" + "\n".join(relevant_concepts)
            logger.info(f"[状态筛选] 为 {detailed_dimension} 筛选了 {len(relevant_concepts)} 个规划维度")
        else:
            filtered_concept = full_concept_report
            logger.warning(f"[状态筛选] 未找到相关规划思路，使用完整报告")

    return {
        "filtered_analysis": filtered_analysis,
        "filtered_concept": filtered_concept
    }


def estimate_token_reduction(
    concept_dimension: str,
    full_report_length: int,
    filtered_report_length: int
) -> Dict[str, Any]:
    """
    估算 Token 使用优化效果

    Args:
        concept_dimension: 规划维度名称
        full_report_length: 完整报告长度（字符数）
        filtered_report_length: 筛选后报告长度（字符数）

    Returns:
        包含优化统计信息的字典
    """
    if full_report_length == 0:
        return {
            "dimension": concept_dimension,
            "reduction_percent": 0,
            "tokens_saved": 0,
            "original_length": 0,
            "filtered_length": 0
        }

    reduction_percent = (1 - filtered_report_length / full_report_length) * 100
    tokens_saved = full_report_length - filtered_report_length

    return {
        "dimension": concept_dimension,
        "reduction_percent": round(reduction_percent, 2),
        "tokens_saved": tokens_saved,
        "original_length": full_report_length,
        "filtered_length": filtered_report_length
    }


def log_optimization_results(results: List[Dict[str, Any]]):
    """
    记录优化结果统计

    Args:
        results: 优化结果列表（每个维度的统计信息）
    """
    if not results:
        return

    total_original = sum(r["original_length"] for r in results)
    total_filtered = sum(r["filtered_length"] for r in results)
    total_saved = total_original - total_filtered
    avg_reduction = (1 - total_filtered / total_original) * 100 if total_original > 0 else 0

    logger.info("[状态筛选优化统计]")
    logger.info(f"  总维度数: {len(results)}")
    logger.info(f"  原始总长度: {total_original} 字符")
    logger.info(f"  优化后长度: {total_filtered} 字符")
    logger.info(f"  节省字符数: {total_saved} 字符")
    logger.info(f"  平均优化率: {avg_reduction:.2f}%")

    for result in results:
        logger.info(f"  {result['dimension']}: 优化 {result['reduction_percent']}% "
                   f"({result['tokens_saved']} 字符)")
