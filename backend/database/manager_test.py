import sys
import asyncio
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.database.manager import get_db_manager

async def test():
    db_manager = get_db_manager()
    await db_manager.initialize(mode='SYNC')
    print('✅ 测试完成')
    return True

if __name__ == '__main__':
    asyncio.run(test())
