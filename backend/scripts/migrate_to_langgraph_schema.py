"""
迁移脚本：将自定义 checkpoint schema 迁移到 LangGraph 标准架构

此脚本执行以下操作：
1. 备份现有数据库
2. 将现有的 'checkpoints' 表重命名为 'checkpoints_legacy'（保留数据）
3. 调用 LangGraph 的 AsyncSqliteSaver.setup() 创建标准 schema
4. 验证新表结构

作者：iFlow CLI
日期：2026-02-14
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import aiosqlite
import os
import shutil
from datetime import datetime
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from backend.database.engine import DB_PATH


def backup_database(db_path: Path) -> Path:
    """
    备份数据库文件

    Args:
        db_path: 数据库文件路径

    Returns:
        备份文件路径
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.stem}_backup_{timestamp}{db_path.suffix}"

    print(f"📦 正在备份数据库: {db_path}")
    print(f"   备份到: {backup_path}")

    shutil.copy2(db_path, backup_path)
    print(f"✅ 数据库备份成功")

    return backup_path


async def check_existing_tables(conn: aiosqlite.Connection) -> list[str]:
    """
    检查现有表结构

    Args:
        conn: 数据库连接

    Returns:
        表名列表
    """
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    rows = await cursor.fetchall()
    tables = [row[0] for row in rows]

    print(f"\n📋 现有表:")
    for table in tables:
        print(f"   - {table}")

    return tables


async def rename_old_checkpoints_table(conn: aiosqlite.Connection) -> bool:
    """
    将旧的 checkpoints 表重命名为 checkpoints_legacy

    Args:
        conn: 数据库连接

    Returns:
        是否成功重命名
    """
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
    )
    result = await cursor.fetchone()

    if not result:
        print("\nℹ️  'checkpoints' 表不存在，无需重命名")
        return True

    # 检查是否已存在备份表
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints_legacy'"
    )
    legacy_exists = await cursor.fetchone()

    if legacy_exists:
        print("\n⚠️  'checkpoints_legacy' 表已存在")
        print("   正在删除旧的备份表...")
        await conn.execute("DROP TABLE IF EXISTS checkpoints_legacy")
        await conn.commit()
        print("   ✅ 旧备份表已删除")

    print("\n🔄 正在将 'checkpoints' 表重命名为 'checkpoints_legacy'...")
    try:
        await conn.execute("ALTER TABLE checkpoints RENAME TO checkpoints_legacy")
        await conn.commit()
        print("✅ 表重命名成功")

        # 显示旧表中的记录数
        cursor = await conn.execute("SELECT COUNT(*) FROM checkpoints_legacy")
        count = await cursor.fetchone()
        print(f"   保留了 {count[0]} 条旧检查点记录")

        return True
    except Exception as e:
        print(f"❌ 重命名失败: {e}")
        return False


async def create_langgraph_schema(conn: aiosqlite.Connection) -> bool:
    """
    使用 LangGraph 的 AsyncSqliteSaver.setup() 创建标准 schema

    Args:
        conn: 数据库连接

    Returns:
        是否成功创建
    """
    print("\n🏗️  正在调用 LangGraph AsyncSqliteSaver.setup()...")
    print("   这将创建包含 'thread_id' 列的标准表结构")

    try:
        saver = AsyncSqliteSaver(conn)
        await saver.setup()

        print("✅ LangGraph schema 创建成功")

        # 验证新表
        print("\n📋 新创建的表:")
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = await cursor.fetchall()
        tables = [row[0] for row in rows]

        for table in tables:
            print(f"   - {table}")

            # 显示表结构
            print(f"     结构:")
            cursor = await conn.execute(f"PRAGMA table_info({table})")
            columns = await cursor.fetchall()
            for col in columns:
                print(f"       {col[1]} ({col[2]})")

        return True
    except Exception as e:
        print(f"❌ 创建 LangGraph schema 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def verify_migration(conn: aiosqlite.Connection) -> bool:
    """
    验证迁移是否成功

    Args:
        conn: 数据库连接

    Returns:
        是否验证通过
    """
    print("\n🔍 验证迁移结果...")

    # 检查关键表是否存在
    required_tables = ['checkpoints', 'writes', 'checkpoint_migrations']
    all_exist = True

    for table in required_tables:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        result = await cursor.fetchone()

        if result:
            print(f"   ✅ {table} 表存在")
        else:
            print(f"   ❌ {table} 表不存在")
            all_exist = False

    # 检查 checkpoints 表是否有 thread_id 列
    cursor = await conn.execute("PRAGMA table_info(checkpoints)")
    columns = await cursor.fetchall()
    column_names = [col[1] for col in columns]

    print(f"\n   checkpoints 表的列: {', '.join(column_names)}")

    if 'thread_id' in column_names:
        print("   ✅ 'thread_id' 列存在")
    else:
        print("   ❌ 'thread_id' 列不存在")
        all_exist = False

    return all_exist


async def migrate():
    """
    主迁移函数
    """
    print("=" * 60)
    print("数据库架构迁移：自定义 Schema → LangGraph 标准 Schema")
    print("=" * 60)

    # 1. 检查数据库文件
    if not DB_PATH.exists():
        print(f"\n❌ 数据库文件不存在: {DB_PATH}")
        return False

    print(f"\n📁 数据库路径: {DB_PATH}")
    print(f"   文件大小: {DB_PATH.stat().st_size / 1024:.2f} KB")

    # 2. 备份数据库
    backup_path = backup_database(DB_PATH)

    # 3. 连接数据库并执行迁移
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            # 3.1 检查现有表
            await check_existing_tables(conn)

            # 3.2 重命名旧表
            if not await rename_old_checkpoints_table(conn):
                print("\n❌ 重命名旧表失败，迁移中止")
                return False

            # 3.3 创建 LangGraph schema
            if not await create_langgraph_schema(conn):
                print("\n❌ 创建 LangGraph schema 失败，迁移中止")
                return False

            # 3.4 验证迁移
            if not await verify_migration(conn):
                print("\n❌ 迁移验证失败")
                return False

        print("\n" + "=" * 60)
        print("🎉 迁移成功完成！")
        print("=" * 60)
        print(f"\n✅ 数据库已迁移到 LangGraph 标准架构")
        print(f"✅ 备份文件: {backup_path}")
        print(f"✅ 旧检查点数据已保留在 'checkpoints_legacy' 表中")
        print(f"\n后续步骤:")
        print(f"   1. 重启后端服务")
        print(f"   2. 测试规划流程")
        print(f"   3. 监控日志确认无错误")

        return True

    except Exception as e:
        print(f"\n❌ 迁移过程中发生错误: {e}")
        import traceback
        traceback.print_exc()

        print(f"\n⚠️  数据库可能处于不一致状态")
        print(f"💡 请从备份恢复: {backup_path}")

        return False


if __name__ == "__main__":
    success = asyncio.run(migrate())
    exit(0 if success else 1)