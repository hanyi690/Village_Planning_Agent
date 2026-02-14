"""
验证数据库迁移结果
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import aiosqlite
from backend.database.engine import DB_PATH


async def verify():
    print("验证数据库迁移结果...")
    print(f"数据库路径: {DB_PATH}\n")

    async with aiosqlite.connect(DB_PATH) as conn:
        # 检查关键表
        required_tables = ['checkpoints', 'writes', 'checkpoint_migrations', 'checkpoints_legacy']

        for table in required_tables:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            result = await cursor.fetchone()

            if result:
                print(f"✅ {table} 表存在")

                # 显示表结构
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                columns = await cursor.fetchall()
                print(f"   列: {', '.join([col[1] for col in columns])}")
            else:
                print(f"❌ {table} 表不存在")

        # 检查 checkpoints 表是否有 thread_id 列
        cursor = await conn.execute("PRAGMA table_info(checkpoints)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        print(f"\n✅ checkpoints 表的列: {', '.join(column_names)}")

        if 'thread_id' in column_names:
            print("✅ thread_id 列存在（迁移成功）")
        else:
            print("❌ thread_id 列不存在（迁移失败）")


if __name__ == "__main__":
    asyncio.run(verify())
