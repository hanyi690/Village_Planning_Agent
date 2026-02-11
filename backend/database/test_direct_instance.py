"""直接创建 DatabaseManager 实例测试"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.database.manager import DatabaseManager, DBMode

async def test():
    db_manager = DatabaseManager()
    await db_manager.initialize(mode=DBMode.SYNC)
    print('✅ DatabaseManager 实例创建成功')
    return True

asyncio.run(test())
