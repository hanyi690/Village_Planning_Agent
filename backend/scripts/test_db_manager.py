"""
测试数据库管理器功能
Test Database Manager Functionality
"""

import asyncio
import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import sys; sys.path.insert(0, r'F:projectVillage_Planning_Agentbackend'); from backend.database.manager import get_db_manager, DBMode


async def test_database_manager():
    """测试数据库管理器"""
    print("🧪 测试数据库管理器...")

    db_manager = get_db_manager()

    # 测试 1: 初始化（同步模式）
    print("\n📋 测试 1: 初始化同步模式")
    db_manager.initialize(mode=DBMode.SYNC)

    # 测试 2: 获取引擎
    print("\n📋 测试 2: 获取同步引擎")
    sync_engine = db_manager.get_engine(mode=DBMode.SYNC)
    print(f"✅ 同步引擎已获取: {type(sync_engine)}")

    # 测试 3: 获取会话
    print("\n📋 测试 3: 获取同步会话")
    from backend.database import get_session
    with get_session() as session:
        print(f"✅ 同步会话已获取: {session}")

    # 测试 4: 初始化异步模式
    print("\n📋 测试 4: 初始化异步模式")
    await db_manager.initialize(mode=DBMode.ASYNC)

    # 测试 5: 获取异步引擎
    print("\n📋 测试 5: 获取异步引擎")
    async_engine = db_manager.get_engine(mode=DBMode.ASYNC)
    print(f"✅ 异步引擎已获取: {type(async_engine)}")

    # 测试 6: 获取异步会话
    print("\n📋 测试 6: 获取异步会话")
    from backend.database import get_session

    # 需要导入 get_async_session
    from backend.database.operations_async import get_async_session

    with get_async_session() as session:
        print(f"✅ 异步会话已获取: {session}")

    # 测试 7: execute_operation 方法
    print("\n📋 测试 7: execute_operation")

    async def dummy_async_func(session_id, event):
        return f"async_{session_id}"

    def dummy_sync_func(session_id, event):
        return f"sync_{session_id}"

    result1 = await db_manager.execute_operation(
        "test_async",
        dummy_async_func,
        dummy_sync_func,
        "test-session-1",
        {"test": "data"}
    )
    print(f"✅ 异步操作结果: {result1}")

    result2 = db_manager.execute_operation(
        "test_sync",
        dummy_sync_func,
        dummy_sync_func,
        "test-session-2",
        {"test": "data"}
    )
    print(f"✅ 同步操作结果: {result2}")

    # 测试 8: 切换模式
    print("\n📋 测试 8: 切换同步模式")
    db_manager.initialize(mode=DBMode.SYNC)

    result3 = await db_manager.execute_operation(
        "test_sync2",
        dummy_sync_func,
        dummy_sync_func,
        "test-session-3",
        {"test": "data"}
    )
    print(f"✅ 切换后同步操作: {result3}")

    print("\n✅ 所有测试完成！")


if __name__ == "__main__":
    asyncio.run(test_database_manager())
