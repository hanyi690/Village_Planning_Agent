"""
异步数据库操作的便捷包装器

提供简化的异步调用接口，统一入口，
自动使用异步模式并内置错误处理和性能监控。
"""

import logging
from typing import Any, Dict, List, Optional

from .manager import get_db_manager, DBMode

logger = logging.getLogger(__name__)


# ============================================
# 便捷异步函数
# ============================================

async def create_session_async(state: Dict[str, Any]) -> str:
    """
    创建规划会话（异步）

    Args:
        state: 初始状态字典

    Returns:
        session_id: 创建的会话ID
    """
    db_manager = get_db_manager()
    return await db_manager.execute_operation(
        'create_session',
        None,  # 同步版本不使用
        None,  # 同步版本不使用
        state
    )


async def get_session_async(session_id: str) -> Optional[Dict[str, Any]]:
    """
    获取规划会话（异步）

    Args:
        session_id: 会话ID

    Returns:
        会话数据字典，不存在时返回 None
    """
    db_manager = get_db_manager()
    return await db_manager.execute_operation(
        'get_session',
        None,  # 同步版本不使用
        None,  # 同步版本不使用
        session_id
    )


async def update_session_async(
    session_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    更新规划会话（异步）

    Args:
        session_id: 会话ID
        updates: 要更新的字段字典

    Returns:
        True: 成功, False: 失败
    """
    db_manager = get_db_manager()
    return await db_manager.execute_operation(
        'update_session',
        None,  # 同步版本不使用
        None,  # 同步版本不使用
        session_id,
        updates
    )


async def add_event_async(session_id: str, event: Dict) -> bool:
    """
    添加会话事件（异步）

    这是最高频的操作之一，使用异步可显著提升性能。

    Args:
        session_id: 会话ID
        event: 事件字典

    Returns:
        True: 成功, False: 失败
    """
    db_manager = get_db_manager()
    return await db_manager.execute_operation(
        'add_event',
        None,  # 同步版本不使用
        None,  # 同步版本不使用
        session_id,
        event
    )


async def get_events_async(session_id: str) -> List[Dict[str, Any]]:
    """
    获取会话事件列表（异步）

    Args:
        session_id: 会话ID

    Returns:
        事件列表，会话不存在时返回空列表
    """
    db_manager = get_db_manager()
    return await db_manager.execute_operation(
        'get_events',
        None,  # 同步版本不使用
        None,  # 同步版本不使用
        session_id
    )


# ============================================
# 导出所有函数
# ============================================

__all__ = [
    "create_session_async",
    "get_session_async",
    "update_session_async",
    "add_event_async",
    "get_events_async",
]
