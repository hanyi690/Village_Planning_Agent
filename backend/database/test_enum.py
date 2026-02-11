"""测试 Enum 导入"""

from enum import Enum

try:
    class DBMode(str, Enum):
        SYNC = "sync"
        ASYNC = "async"
    print("✅ Enum 导入成功")
except ImportError as e:
    print(f"❌ Enum 导入失败: {e}")
