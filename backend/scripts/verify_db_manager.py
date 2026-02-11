"""
验证 DatabaseManager 功能
"""

# 添加项目路径
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.database import manager

db_manager = manager.get_db_manager()
print("✅ DatabaseManager 导入成功")

# 测试初始化
async def test():
    await db_manager.initialize(mode=manager.DBMode.SYNC)
    print("✅ 同步模式初始化成功")

    # 测试执行操作
    result = await db_manager.execute_operation(
        "test_operation",
        lambda: "test_result",
        lambda: "test_result",
        "test-session-1",
        {"test": "data"}
    )
    print(f"✅ 执行操作成功: {result}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test())
