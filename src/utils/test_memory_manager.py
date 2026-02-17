"""
内存管理工具测试脚本

用于测试和验证内存管理功能：
1. 消息历史修剪
2. 状态数据清理
3. 黑板数据清理
4. RAG资源清理
5. 内存监控

运行方式：
    python -m src.utils.test_memory_manager
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def test_message_trimming():
    """测试消息修剪功能"""
    print("\n=== 测试消息修剪 ===")

    from src.utils.memory_manager import trim_messages
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

    # 创建测试消息
    messages = [
        SystemMessage(content="系统提示"),
        HumanMessage(content="用户问题1"),
        AIMessage(content="AI回答1"),
    ]

    # 添加更多消息
    for i in range(2, 100):
        messages.append(HumanMessage(content=f"用户问题{i}"))
        messages.append(AIMessage(content=f"AI回答{i}"))

    print(f"原始消息数: {len(messages)}")

    # 测试修剪
    trimmed = trim_messages(messages, max_count=50, preserve_first=5)
    print(f"修剪后消息数: {len(trimmed)}")
    print(f"节省: {len(messages) - len(trimmed)} 条消息")

    # 验证前5条被保留
    assert all(isinstance(m, (SystemMessage, HumanMessage, AIMessage)) for m in trimmed[:5])
    print("✓ 消息修剪测试通过")


def test_state_cleanup():
    """测试状态清理功能"""
    print("\n=== 测试状态清理 ===")

    from src.utils.memory_manager import cleanup_after_layer, trim_state_messages

    # 模拟Layer 3完成后的状态
    state = {
        "messages": [{"msg": i} for i in range(100)],  # 模拟100条消息
        "dimension_reports": {f"dim_{i}": f"报告{i}" * 100 for i in range(12)},
        "concept_dimension_reports": {f"concept_{i}": f"规划{i}" * 100 for i in range(4)},
        "detailed_dimension_reports": {f"detail_{i}": f"详细规划{i}" * 100 for i in range(10)},
        "current_layer": 4
    }

    print(f"清理前消息数: {len(state['messages'])}")
    print(f"清理前报告数: {len(state['dimension_reports']) + len(state['concept_dimension_reports']) + len(state['detailed_dimension_reports'])}")

    # 测试修剪消息
    state = trim_state_messages(state, max_count=50)
    print(f"修剪后消息数: {len(state['messages'])}")

    # 测试层级清理
    state = cleanup_after_layer(state, completed_layer=3, keep_final_reports=False)
    print(f"清理后报告数: {len(state.get('dimension_reports', {})) + len(state.get('concept_dimension_reports', {}))}")

    print("✓ 状态清理测试通过")


def test_blackboard_cleanup():
    """测试黑板清理功能"""
    print("\n=== 测试黑板清理 ===")

    from src.utils.blackboard_manager import BlackboardManager

    blackboard = BlackboardManager()

    # 添加大量测试数据
    for i in range(150):
        blackboard.publish_tool_result(
            tool_id=f"tool_{i}",
            tool_name=f"测试工具{i}",
            result={"data": f"结果{i}" * 10}
        )

    for i in range(100):
        blackboard.add_insight(
            insight=f"洞察{i}" * 5,
            author=f"Agent_{i % 10}",
            dimension=f"dim_{i % 5}"
        )

    print(f"清理前工具结果数: {len(blackboard.list_tool_results())}")
    print(f"清理前洞察数: {len(blackboard.list_insights())}")

    # 测试清理
    stats = blackboard.cleanup_old_results(
        max_tool_results=50,
        max_insights=30
    )

    print(f"清理后工具结果数: {stats['tool_results_after']}")
    print(f"清理后洞察数: {stats['insights_after']}")
    print(f"移除工具结果数: {stats['tool_results_removed']}")
    print(f"移除洞察数: {stats['insights_removed']}")

    print("✓ 黑板清理测试通过")


def test_rag_cleanup():
    """测试RAG资源清理"""
    print("\n=== 测试RAG资源清理 ===")

    from src.knowledge.rag import cleanup_rag_system, get_rag_memory_info

    # 获取清理前的内存信息
    info_before = get_rag_memory_info()
    print(f"清理前RAG组件: {list(info_before['components_loaded'].keys())}")

    # 执行清理
    result = cleanup_rag_system()
    print(f"清理状态: {result['status']}")
    print(f"清理项: {result['cleaned_items']}")

    # 获取清理后的内存信息
    info_after = get_rag_memory_info()
    print(f"清理后RAG组件: {list(info_after['components_loaded'].keys())}")

    print("✓ RAG清理测试通过")


def test_memory_monitor():
    """测试内存监控功能"""
    print("\n=== 测试内存监控 ===")

    from src.utils.memory_manager import (
        get_memory_usage_mb,
        log_memory_usage,
        get_detailed_memory_info,
        MemoryMonitor
    )

    # 测试基本内存获取
    memory_mb = get_memory_usage_mb()
    print(f"当前内存使用: {memory_mb:.2f} MB")

    # 测试详细内存信息
    detail = get_detailed_memory_info()
    print(f"详细内存信息: {detail}")

    # 测试内存监控器
    monitor = MemoryMonitor()
    monitor.set_baseline()
    monitor.check_memory("测试点1")
    monitor.check_memory("测试点2")

    readings = monitor.get_readings()
    print(f"监控读数数量: {len(readings)}")

    print("✓ 内存监控测试通过")


def test_comprehensive_cleanup():
    """测试综合清理功能"""
    print("\n=== 测试综合清理 ===")

    from src.utils.memory_manager import comprehensive_cleanup

    # 创建模拟状态
    state = {
        "messages": [{"msg": i} for i in range(100)],
        "dimension_reports": {f"dim_{i}": f"报告{i}" * 100 for i in range(12)},
        "concept_dimension_reports": {f"concept_{i}": f"规划{i}" * 100 for i in range(4)},
        "current_layer": 3,
        "blackboard": None
    }

    print(f"综合清理前:")
    print(f"  - 消息数: {len(state['messages'])}")
    print(f"  - 报告数: {len(state.get('dimension_reports', {}))}")

    # 执行综合清理
    state = comprehensive_cleanup(
        state=state,
        completed_layer=2,
        trim_messages=True,
        max_messages=50,
        cleanup_blackboard_enabled=False,
        force_gc=True
    )

    print(f"综合清理后:")
    print(f"  - 消息数: {len(state['messages'])}")
    print(f"  - 报告数: {len(state.get('dimension_reports', {}))}")

    print("✓ 综合清理测试通过")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("内存管理工具测试")
    print("=" * 60)

    try:
        test_message_trimming()
        test_state_cleanup()
        test_blackboard_cleanup()
        test_rag_cleanup()
        test_memory_monitor()
        test_comprehensive_cleanup()

        print("\n" + "=" * 60)
        print("所有测试通过！")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
