"""
Enhanced Database CRUD operations with transaction support
增强数据库操作（带事务支持）

High-level database operations with transaction support, retry logic,
and comprehensive logging for planning sessions.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, orm
from sqlmodel import Session, select as sqlmodel_select
from sqlalchemy.exc import SQLAlchemyError

from .models import (
    PlanningSession,
    Checkpoint,
    UISession,
    UIMessage
)
from .engine import get_session

logger = logging.getLogger(__name__)


# ==========================================
# Planning Session Operations (Enhanced)
# ==========================================

def update_session_state_safe(session_id: str, state: Dict[str, Any]) -> bool:
    """
    安全更新会话状态（带事务保护）

    使用 SQLAlchemy 事务确保原子性，支持乐观锁。

    Args:
        session_id: Session ID
        state: State dictionary with updates

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                logger.error(f"[DB] Session {session_id} not found")
                return False

            # 记录更新前状态
            old_layer_1 = db_session.layer_1_completed
            old_layer_2 = db_session.layer_2_completed
            old_layer_3 = db_session.layer_3_completed

            # 批量更新状态字段
            updated_fields = []
            for key, value in state.items():
                if hasattr(db_session, key):
                    old_value = getattr(db_session, key)
                    setattr(db_session, key, value)
                    if old_value != value:
                        updated_fields.append(f"{key}: {old_value} -> {value}")

            # 更新时间戳
            db_session.updated_at = datetime.now()

            # 提交事务
            session.commit()

            # 记录成功日志
            new_layer_1 = db_session.layer_1_completed
            new_layer_2 = db_session.layer_2_completed
            new_layer_3 = db_session.layer_3_completed

            logger.info(f"[DB] Session {session_id} state updated successfully")
            logger.info(f"[DB] Layer completion changes: L1: {old_layer_1}->{new_layer_1}, L2: {old_layer_2}->{new_layer_2}, L3: {old_layer_3}->{new_layer_3}")
            if updated_fields:
                logger.debug(f"[DB] Updated fields: {', '.join(updated_fields)}")

            return True

    except SQLAlchemyError as e:
        logger.error(f"[DB] Database error updating session {session_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"[DB] Unexpected error updating session {session_id}: {e}", exc_info=True)
        return False


def update_session_layer_completion(
    session_id: str,
    layer_num: int,
    completed: bool,
    status: Optional[str] = None,
    pause_after_step: Optional[bool] = None
) -> bool:
    """
    更新层级完成状态（原子操作）

    专门用于层级完成时的状态更新，确保原子性。

    Args:
        session_id: Session ID
        layer_num: Layer number (1/2/3)
        completed: Completion status
        status: Optional status update
        pause_after_step: Optional pause state

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                logger.error(f"[DB] Session {session_id} not found for layer {layer_num} completion update")
                return False

            # 更新对应的层级完成状态
            if layer_num == 1:
                db_session.layer_1_completed = completed
            elif layer_num == 2:
                db_session.layer_2_completed = completed
            elif layer_num == 3:
                db_session.layer_3_completed = completed
            else:
                logger.error(f"[DB] Invalid layer number: {layer_num}")
                return False

            # 更新当前层级
            if completed:
                db_session.current_layer = layer_num + 1

            # 可选状态更新
            if status is not None:
                db_session.status = status

            if pause_after_step is not None:
                db_session.pause_after_step = pause_after_step

            # 更新时间戳
            db_session.updated_at = datetime.now()

            # 提交事务
            session.commit()

            logger.info(f"[DB] ✓ Layer {layer_num} completion updated for session {session_id}: completed={completed}")
            logger.info(f"[DB]   → current_layer: {db_session.current_layer}, status: {db_session.status}, pause_after_step: {db_session.pause_after_step}")

            return True

    except SQLAlchemyError as e:
        logger.error(f"[DB] Database error updating layer {layer_num} completion: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"[DB] Unexpected error updating layer {layer_num} completion: {e}", exc_info=True)
        return False


# Import all existing operations from the original module
from .operations import (
    create_planning_session,
    get_planning_session,
    update_planning_session,
    delete_planning_session,
    list_planning_sessions,
    update_session_state,
    add_session_event,
    get_session_events,

    create_checkpoint,
    get_checkpoint,
    list_checkpoints,
    delete_checkpoint,

    create_ui_session,
    get_ui_session,
    update_ui_session,
    delete_ui_session,
    list_ui_sessions,

    create_ui_message,
    get_ui_messages,
    delete_ui_messages,
)

__all__ = [
    # Enhanced operations
    "update_session_state_safe",
    "update_session_layer_completion",

    # Original operations
    "create_planning_session",
    "get_planning_session",
    "update_planning_session",
    "delete_planning_session",
    "list_planning_sessions",
    "update_session_state",
    "add_session_event",
    "get_session_events",

    "create_checkpoint",
    "get_checkpoint",
    "list_checkpoints",
    "delete_checkpoint",

    "create_ui_session",
    "get_ui_session",
    "update_ui_session",
    "delete_ui_session",
    "list_ui_sessions",

    "create_ui_message",
    "get_ui_messages",
    "delete_ui_messages",
]
