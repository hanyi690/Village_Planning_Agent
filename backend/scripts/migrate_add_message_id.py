"""
数据迁移脚本：为 ui_messages 表添加 message_id 字段

迁移目的：
- 添加 message_id 字段（前端消息 ID），用于 upsert
- 从现有 message_metadata 中提取 message_id
- 创建唯一索引 (session_id, message_id)

使用方法：
    cd backend
    python -m scripts.migrate_add_message_id
"""

import asyncio
import json
import sqlite3
from pathlib import Path


def get_db_path() -> Path:
    """获取数据库路径"""
    return Path(__file__).parent.parent.parent / "data" / "village_planning.db"


def migrate():
    """执行迁移"""
    db_path = get_db_path()
    
    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        return
    
    print(f"开始迁移数据库: {db_path}")
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # 1. 检查 message_id 列是否已存在
        cursor.execute("PRAGMA table_info(ui_messages)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "message_id" in columns:
            print("message_id 列已存在，跳过迁移")
            return
        
        # 2. 添加 message_id 列
        print("添加 message_id 列...")
        cursor.execute("ALTER TABLE ui_messages ADD COLUMN message_id TEXT")
        
        # 3. 从现有 metadata 提取 message_id
        print("从 metadata 提取 message_id...")
        cursor.execute("SELECT id, message_metadata FROM ui_messages WHERE message_metadata IS NOT NULL")
        rows = cursor.fetchall()
        
        for row_id, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json) if metadata_json else {}
                msg_id = metadata.get("id")
                if msg_id and isinstance(msg_id, str):
                    cursor.execute(
                        "UPDATE ui_messages SET message_id = ? WHERE id = ?",
                        (msg_id, row_id)
                    )
            except (json.JSONDecodeError, TypeError):
                pass
        
        # 4. 为没有 message_id 的记录生成 ID
        print("为没有 message_id 的记录生成 ID...")
        cursor.execute(
            "UPDATE ui_messages SET message_id = 'msg-' || id WHERE message_id IS NULL"
        )
        
        # 5. 创建唯一索引
        print("创建唯一索引...")
        try:
            cursor.execute(
                "CREATE UNIQUE INDEX uq_session_message ON ui_messages(session_id, message_id)"
            )
        except sqlite3.OperationalError as e:
            if "already exists" in str(e):
                print("索引已存在，跳过")
            else:
                raise
        
        conn.commit()
        print("迁移完成！")
        
        # 6. 验证
        cursor.execute("SELECT COUNT(*) FROM ui_messages WHERE message_id IS NULL")
        null_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM ui_messages")
        total_count = cursor.fetchone()[0]
        
        print(f"验证: 总消息数={total_count}, message_id为空的消息数={null_count}")
        
    except Exception as e:
        conn.rollback()
        print(f"迁移失败: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
