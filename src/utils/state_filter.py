"""
状态过滤工具

根据维度依赖关系，智能组装子图需要的部分状态。
支持完整依赖链追踪和Token优化统计。
"""

from typing import Dict, List, Any, Optional
from ..core.dimension_config import (
    ANALYSIS_TO_CONCEPT_MAPPING,
    CONCEPT_TO_DETAILED_MAPPING,
    ANALYSIS_DIMENSION_NAMES,
    CONCEPT_DIMENSION_NAMES,
    DETAILED_DIMENSION_NAMES,
    FULL_DEPENDENCY_CHAIN,
    get_full_dependency_chain_func
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
    mapping = ANALYSIS_TO_CONCEPT_MAPPING().get(concept_dimension)

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
            dimension_name = ANALYSIS_DIMENSION_NAMES().get(dimension_key, dimension_key)
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
    mapping = CONCEPT_TO_DETAILED_MAPPING().get(detailed_dimension)

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
                dimension_name = ANALYSIS_DIMENSION_NAMES().get(dimension_key, dimension_key)
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


# ==========================================
# 增强的状态筛选函数 - 支持完整依赖链
# ==========================================

def filter_state_for_detailed_dimension_v2(
    detailed_dimension: str,
    full_analysis_reports: Optional[Dict[str, str]],
    full_analysis_report: str,
    full_concept_reports: Optional[Dict[str, str]],
    full_concept_report: str,
    completed_detailed_reports: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    增强的状态筛选函数，支持完整依赖链和Token统计

    Args:
        detailed_dimension: 详细规划维度（如 "industry"）
        full_analysis_reports: 完整的各维度现状分析字典
        full_analysis_report: 完整的现状综合报告（降级方案）
        full_concept_reports: 完整的各维度规划思路字典
        full_concept_report: 完整的规划思路综合报告（降级方案）
        completed_detailed_reports: 已完成的前序详细规划字典（project_bank需要）

    Returns:
        {
            "filtered_analysis": str,      # 筛选后的现状分析
            "filtered_concepts": str,       # 筛选后的规划思路
            "filtered_detailed": dict,      # 筛选后的前序详细规划（如需要）
            "dependency_chain": dict,       # 完整依赖链
            "token_stats": dict            # Token节省统计
        }
    """
    # 获取完整依赖链
    dependency_chain = get_full_dependency_chain_func(detailed_dimension)

    if not dependency_chain:
        logger.warning(f"[状态筛选v2] 未找到 {detailed_dimension} 的依赖链，返回完整报告")
        return {
            "filtered_analysis": full_analysis_report,
            "filtered_concepts": full_concept_report,
            "filtered_detailed": {},
            "dependency_chain": {},
            "token_stats": {
                "dimension": detailed_dimension,
                "analysis_original": len(full_analysis_report),
                "analysis_filtered": len(full_analysis_report),
                "concepts_original": len(full_concept_report),
                "concepts_filtered": len(full_concept_report),
                "total_original": len(full_analysis_report) + len(full_concept_report),
                "total_filtered": len(full_analysis_report) + len(full_concept_report),
                "reduction_percent": 0,
                "tokens_saved": 0
            }
        }

    # 筛选现状分析
    required_analyses = dependency_chain.get("layer1_analyses", [])
    filtered_analysis, analysis_stats = _filter_with_stats(
        dimension_name=detailed_dimension,
        required_dims=required_analyses,
        full_reports=full_analysis_reports,
        full_report=full_analysis_report,
        dimension_names=ANALYSIS_DIMENSION_NAMES,
        report_type="现状分析"
    )

    # 筛选规划思路
    required_concepts = dependency_chain.get("layer2_concepts", [])
    if "ALL" in required_concepts or not full_concept_reports:
        filtered_concepts = full_concept_report
        concepts_original = len(full_concept_report)
        concepts_filtered = len(full_concept_report)
        logger.info(f"[状态筛选v2] {detailed_dimension} 使用完整规划思路报告")
    else:
        relevant_concepts = []
        for dim_key in required_concepts:
            if dim_key in full_concept_reports:
                concept_text = full_concept_reports[dim_key]
                concept_name = CONCEPT_DIMENSION_NAMES.get(dim_key, dim_key)
                relevant_concepts.append(f"### {concept_name}\n\n{concept_text}\n")

        if relevant_concepts:
            filtered_concepts = "# 相关规划思路\n\n" + "\n".join(relevant_concepts)
            concepts_original = len(full_concept_report)
            concepts_filtered = len(filtered_concepts)
            logger.info(f"[状态筛选v2] 为 {detailed_dimension} 筛选了 {len(relevant_concepts)} 个规划维度")
        else:
            filtered_concepts = full_concept_report
            concepts_original = len(full_concept_report)
            concepts_filtered = len(full_concept_report)
            logger.warning(f"[状态筛选v2] 未找到相关规划思路，使用完整报告")

    # 筛选已完成的前序详细规划（仅project_bank需要）
    depends_on_detailed = dependency_chain.get("depends_on_detailed", [])
    filtered_detailed = {}
    detailed_stats = {}

    if depends_on_detailed and completed_detailed_reports:
        for dep_dim in depends_on_detailed:
            if dep_dim in completed_detailed_reports:
                filtered_detailed[dep_dim] = completed_detailed_reports[dep_dim]
                logger.info(f"[状态筛选v2] {detailed_dimension} 包含前序规划: {DETAILED_DIMENSION_NAMES.get(dep_dim, dep_dim)}")

        detailed_stats = {
            "depends_on_count": len(depends_on_detailed),
            "available_count": len(filtered_detailed),
            "total_length": sum(len(v) for v in filtered_detailed.values())
        }

    # 计算Token统计
    total_original = analysis_stats["original"] + concepts_original
    total_filtered = analysis_stats["filtered"] + concepts_filtered
    total_saved = total_original - total_filtered
    reduction_percent = (1 - total_filtered / total_original) * 100 if total_original > 0 else 0

    token_stats = {
        "dimension": detailed_dimension,
        "analysis_original": analysis_stats["original"],
        "analysis_filtered": analysis_stats["filtered"],
        "analysis_reduction": analysis_stats["reduction_percent"],
        "concepts_original": concepts_original,
        "concepts_filtered": concepts_filtered,
        "detailed_included": detailed_stats.get("available_count", 0),
        "total_original": total_original,
        "total_filtered": total_filtered,
        "tokens_saved": total_saved,
        "reduction_percent": round(reduction_percent, 2)
    }

    logger.info(f"[状态筛选v2] {detailed_dimension}: "
                f"原始 {total_original} → 筛选后 {total_filtered} "
                f"(节省 {token_stats['reduction_percent']}%)")

    return {
        "filtered_analysis": filtered_analysis,
        "filtered_concepts": filtered_concepts,
        "filtered_detailed": filtered_detailed,
        "dependency_chain": dependency_chain,
        "token_stats": token_stats
    }


def _filter_with_stats(
    dimension_name: str,
    required_dims: List[str],
    full_reports: Optional[Dict[str, str]],
    full_report: str,
    dimension_names: Dict[str, str],
    report_type: str
) -> tuple:
    """
    辅助函数：筛选报告并返回统计信息

    Returns:
        (filtered_report, stats_dict)
    """
    original_length = len(full_report)

    if "ALL" in required_dims or not full_reports:
        return full_report, {
            "original": original_length,
            "filtered": original_length,
            "reduction_percent": 0
        }

    relevant_reports = []
    for dim_key in required_dims:
        if dim_key in full_reports:
            report_text = full_reports[dim_key]
            dim_name = dimension_names.get(dim_key, dim_key)
            relevant_reports.append(f"### {dim_name}\n\n{report_text}\n")

    if relevant_reports:
        filtered_report = f"# 与{DETAILED_DIMENSION_NAMES.get(dimension_name, dimension_name)}相关的{report_type}\n\n" + "\n".join(relevant_reports)
        filtered_length = len(filtered_report)
        reduction_percent = (1 - filtered_length / original_length) * 100 if original_length > 0 else 0
        logger.info(f"[状态筛选v2] 为 {dimension_name} 筛选了 {len(relevant_reports)} 个{report_type}维度")
        return filtered_report, {
            "original": original_length,
            "filtered": filtered_length,
            "reduction_percent": round(reduction_percent, 2)
        }
    else:
        logger.warning(f"[状态筛选v2] 未找到相关{report_type}报告，使用完整报告")
        return full_report, {
            "original": original_length,
            "filtered": original_length,
            "reduction_percent": 0
        }


def visualize_filtering_result(
    detailed_dimension: str,
    filtering_result: Dict[str, Any]
) -> str:
    """
    可视化状态筛选结果（用于调试）

    Args:
        detailed_dimension: 详细规划维度
        filtering_result: filter_state_for_detailed_dimension_v2 的返回值

    Returns:
        格式化的可视化字符串
    """
    lines = [f"\n{'='*60}", f"状态筛选结果: {DETAILED_DIMENSION_NAMES.get(detailed_dimension, detailed_dimension)}", f"{'='*60}"]

    # 依赖链
    chain = filtering_result.get("dependency_chain", {})
    if chain:
        lines.append("\n【依赖关系】")
        lines.append(f"  - 现状维度: {', '.join(chain.get('layer1_analyses', []))}")
        lines.append(f"  - 思路维度: {', '.join(chain.get('layer2_concepts', []))}")
        lines.append(f"  - 执行波次: Wave {chain.get('wave', 0)}")
        depends_on = chain.get('depends_on_detailed', [])
        if depends_on:
            lines.append(f"  - 前置规划: {', '.join(depends_on)}")

    # Token统计
    stats = filtering_result.get("token_stats", {})
    if stats:
        lines.append("\n【Token优化统计】")
        lines.append(f"  原始总长度: {stats.get('total_original', 0)} 字符")
        lines.append(f"  筛选后长度: {stats.get('total_filtered', 0)} 字符")
        lines.append(f"  节省字符数: {stats.get('tokens_saved', 0)} 字符")
        lines.append(f"  优化率: {stats.get('reduction_percent', 0)}%")
        lines.append(f"  现状分析: {stats.get('analysis_original', 0)} → {stats.get('analysis_filtered', 0)} "
                    f"({stats.get('analysis_reduction', 0)}%)")
        lines.append(f"  思路规划: {stats.get('concepts_original', 0)} → {stats.get('concepts_filtered', 0)}")

    # 筛选结果
    detailed = filtering_result.get("filtered_detailed", {})
    if detailed:
        lines.append(f"\n【包含的前序规划】")
        for dim, report in detailed.items():
            dim_name = DETAILED_DIMENSION_NAMES.get(dim, dim)
            lines.append(f"  - {dim_name}: {len(report)} 字符")

    lines.append(f"{'='*60}\n")
    return "\n".join(lines)
