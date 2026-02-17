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

logger = get_logger(__name__)


def run_file_manager_tests() -> dict:
    """运行文件管理器测试"""
    print("\n" + "="*80)
    print("开始运行文件管理器测试...")
    print("="*80 + "\n")

    results = {}

    try:
        import pytest
        result = pytest.main(["tests/test_file_manager.py", "-v", "--tb=short"])
        results["文件管理器测试"] = {"success": result == 0, "exit_code": result}
        print("✅ 文件管理器测试完成")
    except Exception as e:
        logger.error(f"文件管理器测试失败: {str(e)}", exc_info=True)
        print(f"❌ 文件管理器测试失败: {str(e)}")
        results["文件管理器测试"] = {"success": False, "error": str(e)}

    return results


def run_integration_tests() -> dict:
    """运行集成测试"""
    print("\n" + "="*80)
    print("开始运行集成测试...")
    print("="*80 + "\n")

    results = {}

    try:
        import pytest
        result = pytest.main(["tests/test_integration.py", "-v", "--tb=short"])
        results["集成测试"] = {"success": result == 0, "exit_code": result}
        print("✅ 集成测试完成")
    except Exception as e:
        logger.error(f"集成测试失败: {str(e)}", exc_info=True)
        print(f"❌ 集成测试失败: {str(e)}")
        results["集成测试"] = {"success": False, "error": str(e)}

    return results


def run_langsmith_tests() -> dict:
    """运行LangSmith集成测试"""
    print("\n" + "="*80)
    print("开始运行LangSmith集成测试...")
    print("="*80 + "\n")

    results = {}

    try:
        import pytest
        result = pytest.main(["tests/test_langsmith_integration.py", "-v", "--tb=short"])
        results["LangSmith集成测试"] = {"success": result == 0, "exit_code": result}
        print("✅ LangSmith集成测试完成")
    except Exception as e:
        logger.error(f"LangSmith集成测试失败: {str(e)}", exc_info=True)
        print(f"❌ LangSmith集成测试失败: {str(e)}")
        results["LangSmith集成测试"] = {"success": False, "error": str(e)}

    return results


def run_planner_tests() -> dict:
    """运行规划器测试"""
    print("\n" + "="*80)
    print("开始运行规划器测试...")
    print("="*80 + "\n")

    results = {}

    try:
        import pytest
        result = pytest.main(["tests/planners/test_generic_planner.py", "-v", "--tb=short"])
        results["规划器测试"] = {"success": result == 0, "exit_code": result}
        print("✅ 规划器测试完成")
    except Exception as e:
        logger.error(f"规划器测试失败: {str(e)}", exc_info=True)
        print(f"❌ 规划器测试失败: {str(e)}")
        results["规划器测试"] = {"success": False, "error": str(e)}

    return results


def run_all_tests():
    """执行所有测试并生成主汇总报告"""
    print("\n" + "="*80)
    print("Village Planning Agent - 综合测试")
    print("="*80)

    all_results = {}
    start_time = datetime.now()

    # 运行所有测试模块
    all_results["文件管理器"] = run_file_manager_tests()
    all_results["集成测试"] = run_integration_tests()
    all_results["LangSmith"] = run_langsmith_tests()
    all_results["规划器"] = run_planner_tests()

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # 打印最终汇总
    print("\n" + "="*80)
    print("测试完成汇总")
    print("="*80)

    # 统计总体数据
    total_passed = 0
    total_failed = 0

    for module_name, module_results in all_results.items():
        for test_name, result in module_results.items():
            if result.get("success", False):
                total_passed += 1
                print(f"✅ {module_name} - {test_name}")
            else:
                total_failed += 1
                print(f"❌ {module_name} - {test_name}")

    print(f"\n总体: {total_passed} 通过, {total_failed} 失败")
    print(f"总执行时间: {duration:.2f} 秒")
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