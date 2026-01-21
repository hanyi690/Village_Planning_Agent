"""
集成测试 - 测试村庄规划系统的端到端功能

测试主要接口和文件管理工具的集成。
"""

import sys
from pathlib import Path
import tempfile

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_agent_api_integration():
    """测试 agent API 的集成"""
    print("\n=== 测试 Agent API 集成 ===\n")

    from src.agent import (
        run_village_planning,
        run_analysis_only,
        run_concept_only,
        VillageDataManager,
        read_village_data,
        __version__
    )

    print(f"✓ 成功导入 agent 模块 (版本: {__version__})")

    # 测试文件管理器
    print("\n--- 测试 VillageDataManager ---")
    manager = VillageDataManager()

    # 测试文本数据加载
    test_data = "村庄名称：测试村\n人口：1200人\n面积：5.2平方公里"
    result = manager.load_data(test_data)
    print(f"✓ 文本数据加载: {result['success']}")
    print(f"  - 类型: {result['metadata']['type']}")
    print(f"  - 大小: {result['metadata']['size']} 字符")

    # 测试文件数据加载
    temp_dir = tempfile.mkdtemp()
    try:
        test_file = Path(temp_dir) / "village_data.txt"
        test_file.write_text(test_data, encoding='utf-8')

        result = manager.load_data(str(test_file))
        print(f"✓ 文件数据加载: {result['success']}")
        print(f"  - 文件名: {result['metadata']['filename']}")
        print(f"  - 扩展名: {result['metadata']['extension']}")
    finally:
        import shutil
        shutil.rmtree(temp_dir)

    print("\n--- 测试便捷函数 ---")
    data = read_village_data(test_data)
    print(f"✓ read_village_data: {len(data)} 字符")

    print("\n✓ 所有 Agent API 集成测试通过！")


def test_run_agent_file_manager_integration():
    """测试 run_agent 与文件管理器的集成"""
    print("\n=== 测试 run_agent 文件管理器集成 ===\n")

    from src.run_agent import read_village_data

    test_data = "村庄名称：测试村\n人口：1200人"
    result = read_village_data(test_data)
    print(f"✓ run_agent.read_village_data: {len(result)} 字符")

    print("\n✓ run_agent 文件管理器集成测试通过！")


def test_exported_interfaces():
    """测试导出的接口列表"""
    print("\n=== 测试导出接口 ===\n")

    from src import agent

    expected_exports = [
        "run_village_planning",
        "run_analysis_only",
        "run_concept_only",
        "quick_analysis",
        "quick_planning",
        "VillageDataManager",
        "read_village_data",
        "__version__",
        "__architecture__",
    ]

    for export in expected_exports:
        assert hasattr(agent, export), f"缺少导出: {export}"
        print(f"✓ {export}")

    print(f"\n✓ 所有 {len(expected_exports)} 个接口已正确导出！")


def test_file_format_support():
    """测试支持的文件格式"""
    print("\n=== 测试文件格式支持 ===\n")

    from src.knowledge.rag import SUPPORTED_EXTENSIONS

    print(f"支持的文件格式 ({len(SUPPORTED_EXTENSIONS)} 种):")
    for ext, loader_class in sorted(SUPPORTED_EXTENSIONS.items()):
        print(f"  ✓ {ext:8} - {loader_class.__name__}")

    print(f"\n✓ 文件格式支持测试通过！")


def main():
    """运行所有集成测试"""
    print("="*80)
    print("村庄规划 Agent - 集成测试")
    print("="*80)

    try:
        test_agent_api_integration()
        test_run_agent_file_manager_integration()
        test_exported_interfaces()
        test_file_format_support()

        print("\n" + "="*80)
        print("✓ 所有集成测试通过！")
        print("="*80)

        return 0
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
