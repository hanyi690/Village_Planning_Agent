"""
Village Planning Agent - 综合测试运行器

运行所有测试模块并生成主汇总报告。

使用方法：
    python -m tests.run_all_tests
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.logger import get_logger
from tests.test_utils import (
    ensure_output_dirs,
    get_timestamp,
    save_to_markdown,
    generate_master_summary,
    SUMMARY_OUTPUT_DIR
)

logger = get_logger(__name__)


def run_analysis_tests() -> dict:
    """运行分析子图测试"""
    print("\n" + "="*80)
    print("开始运行现状分析子图测试...")
    print("="*80 + "\n")

    results = {}

    try:
        from tests.test_analysis_subgraph import run_all_tests_and_summary
        results = run_all_tests_and_summary()
        print("✅ 现状分析子图测试完成")
    except Exception as e:
        logger.error(f"现状分析子图测试失败: {str(e)}", exc_info=True)
        print(f"❌ 现状分析子图测试失败: {str(e)}")
        results = {"错误": str(e)}

    return results


def run_concept_tests() -> dict:
    """运行概念子图测试"""
    print("\n" + "="*80)
    print("开始运行规划思路子图测试...")
    print("="*80 + "\n")

    results = {}

    try:
        from tests.test_concept_subgraph import run_all_tests_and_summary
        results = run_all_tests_and_summary()
        print("✅ 规划思路子图测试完成")
    except Exception as e:
        logger.error(f"规划思路子图测试失败: {str(e)}", exc_info=True)
        print(f"❌ 规划思路子图测试失败: {str(e)}")
        results = {"错误": str(e)}

    return results


def run_all_tests():
    """执行所有测试并生成主汇总报告"""
    print("\n" + "="*80)
    print("Village Planning Agent - 综合测试")
    print("="*80)

    # 确保输出目录存在
    ensure_output_dirs()

    all_results = {}
    start_time = datetime.now()

    # 运行所有测试模块
    analysis_results = run_analysis_tests()
    all_results["现状分析"] = analysis_results

    concept_results = run_concept_tests()
    all_results["规划思路"] = concept_results

    end_time = datetime.now()

    # 生成主汇总报告
    summary_content = generate_master_summary(all_results)

    # 添加执行时间信息
    duration = (end_time - start_time).total_seconds()
    summary_content += f"\n\n**总执行时间**: {duration:.2f} 秒\n"

    timestamp = get_timestamp()
    master_summary_file = SUMMARY_OUTPUT_DIR / f"master_summary_{timestamp}.md"
    save_to_markdown(summary_content, master_summary_file)

    # 打印最终汇总
    print("\n" + "="*80)
    print("测试完成汇总")
    print("="*80)

    # 统计总体数据
    total_tests = 0
    total_passed = 0

    for module_name, module_results in all_results.items():
        if isinstance(module_results, dict) and "错误" not in module_results:
            module_total = len(module_results)
            module_passed = sum(1 for r in module_results.values() if r.get("success", False))
            total_tests += module_total
            total_passed += module_passed

            print(f"\n{module_name}: {module_passed}/{module_total} 通过")

    print(f"\n总体: {total_passed}/{total_tests} 通过")
    print(f"主汇总报告: {master_summary_file.relative_to(Path.cwd())}")
    print("="*80 + "\n")

    return all_results


if __name__ == "__main__":
    try:
        run_all_tests()
        print("✅ 所有测试完成！")
    except Exception as e:
        logger.error(f"测试运行失败: {str(e)}", exc_info=True)
        print(f"\n❌ 测试运行失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
