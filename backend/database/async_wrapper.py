"""
异步数据库操作的便捷包装器

提供简化的异步调用接口，统一入口，
自动使用异步模式并内置错误处理和性能监控。
"""

import logging
from typing import Any, Dict, List, Optional

from .manager import get_db_manager, DBMode
from . import operations as sync_ops

logger = logging.getLogger(__name__)


# ============================================
# 便捷异步函数
# ============================================

async def create_session_async(state: Dict[str, Any]) -> str:
    """
    创建规划会话（异步，带同步回退）

    Args:
        state: 初始状态字典

    Returns:
        session_id: 创建的会话ID
    """
    db_manager = get_db_manager()

    try:
        return await db_manager.execute_operation(
            'create_session',
            None,
            sync_ops.create_planning_session,  # sync fallback
            state
        )
    except Exception as e:
        logger.warning(f"Async create_session failed, trying sync: {e}")
        return sync_ops.create_planning_session(state)


async def get_session_async(session_id: str) -> Optional[Dict[str, Any]]:
    """
    获取规划会话（异步，带同步回退）

    Args:
        session_id: 会话ID

    Returns:
        会话数据字典，不存在时返回 None
    """
    db_manager = get_db_manager()

    try:
        return await db_manager.execute_operation(
            'get_session',
            None,
            sync_ops.get_planning_session,  # sync fallback
            session_id
        )
    except Exception as e:
        logger.warning(f"Async get_session failed, trying sync: {e}")
        return sync_ops.get_planning_session(session_id)


async def update_session_async(
    session_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    更新规划会话（异步，带同步回退）

    Args:
        session_id: 会话ID
        updates: 要更新的字段字典

    Returns:
        True: 成功, False: 失败
    """
    db_manager = get_db_manager()

    try:
        return await db_manager.execute_operation(
            'update_session',
            None,
            sync_ops.update_planning_session,  # sync fallback
            session_id,
            updates
        )
    except Exception as e:
        logger.warning(f"Async update_session failed, trying sync: {e}")
        return sync_ops.update_planning_session(session_id, updates)


async def add_event_async(session_id: str, event: Dict) -> bool:
    """
    添加会话事件（异步，带同步回退）

    这是最高频的操作之一，使用异步可显著提升性能。

    Args:
        session_id: 会话ID
        event: 事件字典

    Returns:
        True: 成功, False: 失败
    """
    db_manager = get_db_manager()

    try:
        return await db_manager.execute_operation(
            'add_event',
            None,
            sync_ops.add_session_event,  # sync fallback
            session_id,
            event
        )
    except Exception as e:
        logger.warning(f"Async add_event failed, trying sync: {e}")
        return sync_ops.add_session_event(session_id, event)


async def get_events_async(session_id: str) -> List[Dict[str, Any]]:
    """
    获取会话事件列表（异步，带同步回退）

    Args:
        session_id: 会话ID

    Returns:
        事件列表，会话不存在时返回空列表
    """
    db_manager = get_db_manager()

    try:
        return await db_manager.execute_operation(
            'get_events',
            None,
            sync_ops.get_session_events,  # sync fallback
            session_id
        )
    except Exception as e:
        logger.warning(f"Async get_events failed, trying sync: {e}")
        return sync_ops.get_session_events(session_id)


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
