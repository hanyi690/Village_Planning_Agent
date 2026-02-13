import json
from datetime import datetime
from typing import Any, Dict, List, Set

def make_json_serializable(obj: Any) -> Any:
    """递归转换不可JSON序列化的类型为可序列化类型"""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)          # ⭐ set → list
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_serializable(i) for i in obj]
    # 其他无法序列化的对象（如自定义类）→ 转字符串
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)