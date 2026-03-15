"""
数据迁移脚本：为 dimension_revisions 表添加 previous_content 字段

迁移目的：
- 添加 previous_content 列（TEXT 类型），用于保存修订前的完整内容
- 支持前端显示修复前后的内容对比

使用方法：
    cd backend
    python -m scripts.migrate_add_previous_content
"""

import sqlite3
from pathlib import Path


def get_db_path() -> Path:
    """获取数据库路径"""
    return Path(__file__).parent.parent.parent / "data" / "village_planning.db"


def migrate():
    """执行迁移"""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"数据库不存在：{db_path}")
        return

    print(f"开始迁移数据库：{db_path}")

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        # 1. 检查 previous_content 列是否已存在
        cursor.execute("PRAGMA table_info(dimension_revisions)")
        columns = [col[1] for col in cursor.fetchall()]

        if "previous_content" in columns:
            print("previous_content 列已存在，跳过迁移")
            return

        # 2. 添加 previous_content 列
        print("添加 previous_content 列...")
        cursor.execute("ALTER TABLE dimension_revisions ADD COLUMN previous_content TEXT")

        conn.commit()
        print("迁移完成！")

        # 3. 验证
        cursor.execute("PRAGMA table_info(dimension_revisions)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"验证：dimension_revisions 表的列：{columns}")

        if "previous_content" in columns:
            print("✓ previous_content 列已成功添加")
        else:
            print("✗ previous_content 列添加失败")

    except Exception as e:
        conn.rollback()
        print(f"迁移失败：{e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
