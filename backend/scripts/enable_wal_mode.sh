#!/bin/bash
# SQLite WAL 模式启用脚本
# 用于消除数据库写入锁，提升并发性能

set -e

# 数据库目录
DB_DIR="/data"
DB_FILE="${DB_DIR}/village_planning.db"

echo "🗄️ 启用 SQLite WAL 模式..."
echo "数据库文件: ${DB_FILE}"

# 检查数据库文件是否存在
if [ ! -f "$DB_FILE" ]; then
    echo "❌ 数据库文件不存在: ${DB_FILE}"
    echo "请先初始化数据库"
    exit 1
fi

# 启用 WAL 模式
sqlite3 "$DB_FILE" "PRAGMA journal_mode=WAL"
sqlite3 "$DB_FILE" "PRAGMA synchronous=NORMAL"

# 验证 WAL 模式
RESULT=$(sqlite3 "$DB_FILE" "PRAGMA journal_mode")
if [ "$RESULT" = "wal" ]; then
    echo "✅ WAL 模式已启用: ${RESULT}"
else
    echo "❌ WAL 模式启用失败: ${RESULT}"
    exit 1
fi

# 显示当前配置
echo ""
echo "📊 当前数据库配置："
sqlite3 "$DB_FILE" "PRAGMA journal_mode"
sqlite3 "$DB_FILE" "PRAGMA synchronous"
sqlite3 "$DB_FILE" "PRAGMA wal_autocheckpoint"
echo ""

echo "✅ WAL 模式启用完成"
echo "说明："
echo "  - journal_mode=WAL: 写前日志模式"
echo "  - synchronous=NORMAL: 允许多个读取器"
echo "  - 数据库并发性能已优化"
