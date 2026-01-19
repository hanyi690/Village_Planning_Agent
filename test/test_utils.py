"""
测试工具模块

提供测试文件操作的共享工具函数。
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Directory constants
TEST_OUTPUT_DIR = Path(__file__).parent / "output"
ANALYSIS_OUTPUT_DIR = TEST_OUTPUT_DIR / "analysis"
CONCEPT_OUTPUT_DIR = TEST_OUTPUT_DIR / "concept"
SUMMARY_OUTPUT_DIR = TEST_OUTPUT_DIR / "summary"


def ensure_output_dirs() -> None:
    """确保所有输出目录存在"""
    for dir_path in [TEST_OUTPUT_DIR, ANALYSIS_OUTPUT_DIR, CONCEPT_OUTPUT_DIR, SUMMARY_OUTPUT_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)


def get_timestamp() -> str:
    """获取用于文件名的时间戳"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_to_markdown(content: str, filepath: Path, title: str = "") -> Path:
    """
    将内容保存为 Markdown 文件

    Args:
        content: 要保存的内容
        filepath: 目标文件路径
        title: 可选的文档标题

    Returns:
        保存的文件路径
    """
    # 确保目录存在
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 添加标题（如果提供）
    if title and not content.startswith("#"):
        content = f"# {title}\n\n{content}"

    # 写入文件
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


def format_duration(start_time: datetime, end_time: datetime) -> str:
    """格式化时间差"""
    duration = end_time - start_time
    seconds = duration.total_seconds()
    if seconds < 60:
        return f"{seconds:.2f}秒"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}分{secs}秒"


def generate_analysis_summary(test_results: Dict[str, Any]) -> str:
    """
    生成分析子图测试汇总报告

    Args:
        test_results: 包含所有测试结果的字典

    Returns:
        Markdown 格式的汇总报告
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_tests = len(test_results)
    passed = sum(1 for r in test_results.values() if r.get("success", False))
    failed = total_tests - passed

    lines = [
        "# 现状分析子图测试汇总报告\n",
        f"**生成时间**: {timestamp}",
        f"**测试模块**: 现状分析 (Analysis Subgraph)\n",
        "## 测试概况",
        f"- 总测试数: {total_tests}",
        f"- 成功: {passed}",
        f"- 失败: {failed}\n",
        "## 各测试结果\n"
    ]

    for test_name, result in test_results.items():
        status_icon = "✅" if result.get("success", False) else "❌"
        report_length = result.get("report_length", 0)
        output_file = result.get("output_file", "无")

        lines.extend([
            f"### 测试: {test_name}",
            f"- 状态: {status_icon}",
            f"- 报告长度: {report_length} 字符",
            f"- 输出文件: `{output_file}`\n"
        ])

    lines.extend([
        "## 详细输出文件",
        "---",
        "以上测试报告均已保存在 `test/output/analysis/` 目录下。\n"
    ])

    return "\n".join(lines)


def generate_concept_summary(test_results: Dict[str, Any]) -> str:
    """
    生成概念子图测试汇总报告

    Args:
        test_results: 包含所有测试结果的字典

    Returns:
        Markdown 格式的汇总报告
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_tests = len(test_results)
    passed = sum(1 for r in test_results.values() if r.get("success", False))
    failed = total_tests - passed

    lines = [
        "# 规划思路子图测试汇总报告\n",
        f"**生成时间**: {timestamp}",
        f"**测试模块**: 规划思路 (Concept Subgraph)\n",
        "## 测试概况",
        f"- 总测试数: {total_tests}",
        f"- 成功: {passed}",
        f"- 失败: {failed}\n",
        "## 各测试结果\n"
    ]

    for test_name, result in test_results.items():
        status_icon = "✅" if result.get("success", False) else "❌"
        report_length = result.get("report_length", 0)
        output_file = result.get("output_file", "无")

        lines.extend([
            f"### 测试: {test_name}",
            f"- 状态: {status_icon}",
            f"- 报告长度: {report_length} 字符",
            f"- 输出文件: `{output_file}`\n"
        ])

    lines.extend([
        "## 详细输出文件",
        "---",
        "以上测试报告均已保存在 `test/output/concept/` 目录下。\n"
    ])

    return "\n".join(lines)


def generate_master_summary(all_results: Dict[str, Dict[str, Any]]) -> str:
    """
    生成所有测试的主汇总报告

    Args:
        all_results: 包含所有模块测试结果的字典

    Returns:
        Markdown 格式的主汇总报告
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Village Planning Agent - 测试主汇总报告\n",
        f"**生成时间**: {timestamp}",
        "---\n"
    ]

    # 统计总体数据
    total_tests = 0
    total_passed = 0
    total_failed = 0

    for module_name, module_results in all_results.items():
        total_tests += len(module_results)
        total_passed += sum(1 for r in module_results.values() if r.get("success", False))

    total_failed = total_tests - total_passed

    lines.extend([
        "## 总体概况",
        f"- 测试模块数: {len(all_results)}",
        f"- 总测试数: {total_tests}",
        f"- 成功: {total_passed}",
        f"- 失败: {total_failed}\n"
    ])

    # 各模块详情
    for module_name, module_results in all_results.items():
        module_passed = sum(1 for r in module_results.values() if r.get("success", False))
        module_total = len(module_results)

        lines.extend([
            f"## {module_name} 模块",
            f"- 测试数: {module_total}",
            f"- 成功: {module_passed}",
            f"- 失败: {module_total - module_passed}\n"
        ])

        for test_name, result in module_results.items():
            status_icon = "✅" if result.get("success", False) else "❌"
            output_file = result.get("output_file", "无")
            lines.append(f"- {test_name}: {status_icon} (`{output_file}`)")

        lines.append("")

    lines.extend([
        "---",
        "## 输出目录",
        "- 分析子图测试: `test/output/analysis/`",
        "- 概念子图测试: `test/output/concept/`",
        "- 汇总报告: `test/output/summary/`\n"
    ])

    return "\n".join(lines)


def format_test_output(
    test_name: str,
    test_type: str,
    project_name: str,
    test_data: str,
    report_content: str,
    start_time: datetime,
    end_time: datetime,
    additional_info: Dict[str, Any] = None
) -> str:
    """
    格式化测试输出为 Markdown

    Args:
        test_name: 测试名称
        test_type: 测试类型 (direct/wrapper/stream)
        project_name: 项目名称
        test_data: 测试数据
        report_content: 报告内容
        start_time: 开始时间
        end_time: 结束时间
        additional_info: 额外信息字典

    Returns:
        格式化后的 Markdown 内容
    """
    timestamp = start_time.strftime("%Y-%m-%d %H:%M:%S")
    duration = format_duration(start_time, end_time)

    lines = [
        f"# 测试报告: {test_name}",
        "",
        f"**测试时间**: {timestamp}",
        f"**测试类型**: {test_type}",
        f"**项目名称**: {project_name}",
        f"**耗时**: {duration}",
        "",
        "## 测试数据",
        "```",
        test_data[:500] + "..." if len(test_data) > 500 else test_data,
        "```",
        "",
        "## 执行结果"
    ]

    if additional_info:
        for key, value in additional_info.items():
            lines.append(f"- **{key}**: {value}")

    lines.extend([
        "",
        "## 分析报告",
        "---",
        report_content,
        "",
        "## 元数据",
        f"- 开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 耗时: {duration}"
    ])

    return "\n".join(lines)
