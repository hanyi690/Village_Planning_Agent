"""
Database CRUD operations
数据库 CRUD 操作

High-level database operations for planning sessions, checkpoints,
and UI conversations.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, orm
from sqlmodel import Session, select as sqlmodel_select

from .models import (
    PlanningSession,
    Checkpoint,
    UISession,
    UIMessage
)
from .engine import get_session

logger = logging.getLogger(__name__)


# ==========================================
# Planning Session Operations
# ==========================================

def create_planning_session(state: Dict[str, Any]) -> str:
    """
    Create a new planning session
    创建新的规划会话

    Args:
        state: Initial state dictionary

    Returns:
        str: Session ID
    """
    try:
        with get_session() as session:
            # Extract fields from state
            session_id = state.get("session_id")
            project_name = state.get("project_name", "")

            # Create planning session record
            db_session = PlanningSession(
                session_id=session_id,
                project_name=project_name,
                status="running",
                village_data=state.get("village_data", ""),
                task_description=state.get("task_description", "制定村庄总体规划方案"),
                constraints=state.get("constraints", "无特殊约束"),

                # Flow control
                current_layer=state.get("current_layer", 1),
                previous_layer=state.get("previous_layer", 1),
                layer_1_completed=state.get("layer_1_completed", False),
                layer_2_completed=state.get("layer_2_completed", False),
                layer_3_completed=state.get("layer_3_completed", False),

                # Review settings
                need_human_review=state.get("need_human_review", False),
                step_mode=state.get("step_mode", False),

                # Output
                output_path=state.get("output_path"),

                # Store complete state snapshot
                state_snapshot=state,
                request_params=state.get("_request_params"),

                # Initialize event tracking
                events=[],
                execution_complete=False,
                execution_error=None,
            )

            session.add(db_session)
            session.commit()

            logger.info(f"Created planning session: {session_id}")
            return session_id

    except Exception as e:
        logger.error(f"Failed to create planning session: {e}", exc_info=True)
        raise


def get_planning_session(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get planning session by ID
    获取规划会话

    Args:
        session_id: Session ID

    Returns:
        Dict with session data, or None if not found
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                return None

            return _planning_session_to_dict(db_session)

    except Exception as e:
        logger.error(f"Failed to get planning session {session_id}: {e}", exc_info=True)
        return None


def update_planning_session(
    session_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    Update planning session
    更新规划会话

    Args:
        session_id: Session ID
        updates: Fields to update

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                logger.warning(f"Planning session not found: {session_id}")
                return False

            # Update fields
            for key, value in updates.items():
                if hasattr(db_session, key):
                    setattr(db_session, key, value)

            # Update timestamp
            db_session.updated_at = datetime.now()

            # Auto-set completed_at if status changed to completed
            if updates.get("status") == "completed" and not db_session.completed_at:
                db_session.completed_at = datetime.now()

            session.commit()

            logger.info(f"Updated planning session: {session_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to update planning session {session_id}: {e}", exc_info=True)
        return False


def update_session_state(session_id: str, state: Dict[str, Any]) -> bool:
    """
    Update session state snapshot
    更新会话状态快照

    Args:
        session_id: Session ID
        state: Complete state dictionary

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                logger.warning(f"Planning session not found: {session_id}")
                return False

            # Update state snapshot
            db_session.state_snapshot = state

            # Update individual fields for easy querying
            db_session.current_layer = state.get("current_layer", db_session.current_layer)
            db_session.layer_1_completed = state.get("layer_1_completed", db_session.layer_1_completed)
            db_session.layer_2_completed = state.get("layer_2_completed", db_session.layer_2_completed)
            db_session.layer_3_completed = state.get("layer_3_completed", db_session.layer_3_completed)
            db_session.status = state.get("status", db_session.status)

            # Update timestamp
            db_session.updated_at = datetime.now()

            session.commit()

            logger.info(f"Updated session state: {session_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to update session state {session_id}: {e}", exc_info=True)
        return False


def delete_planning_session(session_id: str) -> bool:
    """
    Delete planning session
    删除规划会话

    Args:
        session_id: Session ID

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                logger.warning(f"Planning session not found: {session_id}")
                return False

            session.delete(db_session)
            session.commit()

            logger.info(f"Deleted planning session: {session_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to delete planning session {session_id}: {e}", exc_info=True)
        return False


def list_planning_sessions(
    project_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    List planning sessions
    列出规划会话

    Args:
        project_name: Filter by project name (optional)
        status: Filter by status (optional)
        limit: Maximum number of results

    Returns:
        List of session dictionaries
    """
    try:
        with get_session() as session:
            query = select(PlanningSession)

            # Apply filters
            if project_name:
                query = query.where(PlanningSession.project_name == project_name)
            if status:
                query = query.where(PlanningSession.status == status)

            # Order by created_at descending
            query = query.order_by(PlanningSession.created_at.desc()).limit(limit)

            results = session.execute(query).scalars().all()

            return [_planning_session_to_dict(r) for r in results]

    except Exception as e:
        logger.error(f"Failed to list planning sessions: {e}", exc_info=True)
        return []


def add_session_event(session_id: str, event: Dict[str, Any]) -> bool:
    """
    Add event to session event list
    添加事件到会话事件列表

    Args:
        session_id: Session ID
        event: Event dictionary

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                return False

            # Initialize events list if None
            if db_session.events is None:
                db_session.events = []

            # Add event
            db_session.events.append(event)

            # Flag the events attribute as modified (required for JSON columns)
            orm.attributes.flag_modified(db_session, 'events')

            session.commit()

            return True

    except Exception as e:
        logger.error(f"Failed to add event to session {session_id}: {e}", exc_info=True)
        return False


def get_session_events(session_id: str) -> List[Dict[str, Any]]:
    """
    Get session events
    获取会话事件列表

    Args:
        session_id: Session ID

    Returns:
        List of event dictionaries
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            ).scalar_one_or_none()

            if not db_session:
                return []

            return db_session.events or []

    except Exception as e:
        logger.error(f"Failed to get session events {session_id}: {e}", exc_info=True)
        return []


# ==========================================
# Checkpoint Operations
# ==========================================

def create_checkpoint(
    project_name: str,
    timestamp: str,
    checkpoint_id: str,
    state: Dict[str, Any],
    metadata: Dict[str, Any]
) -> bool:
    """
    Create a checkpoint
    创建检查点

    Args:
        project_name: Project name
        timestamp: Session timestamp (session_id)
        checkpoint_id: Checkpoint ID
        state: Complete state dictionary
        metadata: Checkpoint metadata

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            checkpoint = Checkpoint(
                checkpoint_id=checkpoint_id,
                session_id=timestamp,  # session_id is used as timestamp
                layer=metadata.get("layer", 0),
                description=metadata.get("description", ""),
                state_snapshot=state,
                checkpoint_metadata=metadata,
                timestamp=datetime.now()
            )

            session.add(checkpoint)
            session.commit()

            logger.info(f"Created checkpoint: {checkpoint_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to create checkpoint {checkpoint_id}: {e}", exc_info=True)
        return False


def get_checkpoint(checkpoint_id: str) -> Optional[Dict[str, Any]]:
    """
    Get checkpoint by ID
    获取检查点

    Args:
        checkpoint_id: Checkpoint ID

    Returns:
        Dict with checkpoint data, or None if not found
    """
    try:
        with get_session() as session:
            checkpoint = session.execute(
                select(Checkpoint).where(Checkpoint.checkpoint_id == checkpoint_id)
            ).scalar_one_or_none()

            if not checkpoint:
                return None

            return {
                "checkpoint_id": checkpoint.checkpoint_id,
                "session_id": checkpoint.session_id,
                "layer": checkpoint.layer,
                "description": checkpoint.description,
                "state": checkpoint.state_snapshot,
                "metadata": checkpoint.checkpoint_metadata,
                "timestamp": checkpoint.timestamp.isoformat(),
            }

    except Exception as e:
        logger.error(f"Failed to get checkpoint {checkpoint_id}: {e}", exc_info=True)
        return None


def list_checkpoints(
    session_id: Optional[str] = None,
    project_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    List checkpoints
    列出检查点

    Args:
        session_id: Filter by session ID (optional)
        project_name: Filter by project name (requires join)

    Returns:
        List of checkpoint dictionaries
    """
    try:
        with get_session() as session:
            query = select(Checkpoint)

            if session_id:
                query = query.where(Checkpoint.session_id == session_id)

            # Order by layer
            query = query.order_by(Checkpoint.layer.asc())

            results = session.execute(query).scalars().all()

            checkpoints = []
            for cp in results:
                checkpoints.append({
                    "checkpoint_id": cp.checkpoint_id,
                    "session_id": cp.session_id,
                    "layer": cp.layer,
                    "description": cp.description,
                    "timestamp": cp.timestamp.isoformat(),
                    "metadata": cp.checkpoint_metadata,
                })

            return checkpoints

    except Exception as e:
        logger.error(f"Failed to list checkpoints: {e}", exc_info=True)
        return []


def delete_checkpoint(checkpoint_id: str) -> bool:
    """
    Delete checkpoint
    删除检查点

    Args:
        checkpoint_id: Checkpoint ID

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            checkpoint = session.execute(
                select(Checkpoint).where(Checkpoint.checkpoint_id == checkpoint_id)
            ).scalar_one_or_none()

            if not checkpoint:
                return False

            session.delete(checkpoint)
            session.commit()

            logger.info(f"Deleted checkpoint: {checkpoint_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to delete checkpoint {checkpoint_id}: {e}", exc_info=True)
        return False


# ==========================================
# UI Session Operations
# ==========================================

def create_ui_session(
    conversation_id: str,
    session_type: str = "conversation"
) -> str:
    """
    Create a new UI session
    创建新的 UI 会话

    Args:
        conversation_id: Conversation ID
        session_type: Session type (conversation/form/cli/api)

    Returns:
        str: Conversation ID
    """
    try:
        with get_session() as session:
            db_session = UISession(
                conversation_id=conversation_id,
                status="idle",
            )

            session.add(db_session)
            session.commit()

            logger.info(f"Created UI session: {conversation_id}")
            return conversation_id

    except Exception as e:
        logger.error(f"Failed to create UI session: {e}", exc_info=True)
        raise


def get_ui_session(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Get UI session by ID
    获取 UI 会话

    Args:
        conversation_id: Conversation ID

    Returns:
        Dict with session data, or None if not found
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            ).scalar_one_or_none()

            if not db_session:
                return None

            return _ui_session_to_dict(db_session)

    except Exception as e:
        logger.error(f"Failed to get UI session {conversation_id}: {e}", exc_info=True)
        return None


def update_ui_session(
    conversation_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    Update UI session
    更新 UI 会话

    Args:
        conversation_id: Conversation ID
        updates: Fields to update

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            ).scalar_one_or_none()

            if not db_session:
                return False

            # Update fields
            for key, value in updates.items():
                if hasattr(db_session, key):
                    setattr(db_session, key, value)

            # Update timestamp
            db_session.updated_at = datetime.now()

            session.commit()

            logger.info(f"Updated UI session: {conversation_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to update UI session {conversation_id}: {e}", exc_info=True)
        return False


def delete_ui_session(conversation_id: str) -> bool:
    """
    Delete UI session
    删除 UI 会话

    Args:
        conversation_id: Conversation ID

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            db_session = session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            ).scalar_one_or_none()

            if not db_session:
                return False

            session.delete(db_session)
            session.commit()

            logger.info(f"Deleted UI session: {conversation_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to delete UI session {conversation_id}: {e}", exc_info=True)
        return False


def list_ui_sessions(
    status: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    List UI sessions
    列出 UI 会话

    Args:
        status: Filter by status (optional)
        limit: Maximum number of results

    Returns:
        List of session dictionaries
    """
    try:
        with get_session() as session:
            query = select(UISession)

            if status:
                query = query.where(UISession.status == status)

            # Order by created_at descending
            query = query.order_by(UISession.created_at.desc()).limit(limit)

            results = session.execute(query).scalars().all()

            return [_ui_session_to_dict(r) for r in results]

    except Exception as e:
        logger.error(f"Failed to list UI sessions: {e}", exc_info=True)
        return []


# ==========================================
# UI Message Operations
# ==========================================

def create_ui_message(
    session_id: str,
    role: str,
    content: str,
    message_type: str = "text",
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Create a UI message
    创建 UI 消息

    Args:
        session_id: Session ID
        role: Message role (user/assistant/system)
        content: Message content
        message_type: Message type (text/file/progress/etc)
        metadata: Optional metadata

    Returns:
        int: Message ID
    """
    try:
        with get_session() as session:
            message = UIMessage(
                session_id=session_id,
                role=role,
                content=content,
                message_type=message_type,
                message_metadata=metadata,
                timestamp=datetime.now()
            )

            session.add(message)
            session.commit()
            session.refresh(message)

            logger.info(f"Created UI message: {message.id}")
            return message.id

    except Exception as e:
        logger.error(f"Failed to create UI message: {e}", exc_info=True)
        raise


def get_ui_messages(session_id: str) -> List[Dict[str, Any]]:
    """
    Get UI messages for a session
    获取 UI 会话消息

    Args:
        session_id: Session ID

    Returns:
        List of message dictionaries
    """
    try:
        with get_session() as session:
            messages = session.execute(
                select(UIMessage)
                .where(UIMessage.session_id == session_id)
                .order_by(UIMessage.timestamp.asc())
            ).scalars().all()

            return [_ui_message_to_dict(m) for m in messages]

    except Exception as e:
        logger.error(f"Failed to get UI messages for {session_id}: {e}", exc_info=True)
        return []


def delete_ui_messages(session_id: str) -> bool:
    """
    Delete all messages for a session
    删除会话的所有消息

    Args:
        session_id: Session ID

    Returns:
        bool: True if successful
    """
    try:
        with get_session() as session:
            messages = session.execute(
                select(UIMessage).where(UIMessage.session_id == session_id)
            ).scalars().all()

            for message in messages:
                session.delete(message)

            session.commit()

            logger.info(f"Deleted UI messages for session: {session_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to delete UI messages for {session_id}: {e}", exc_info=True)
        return False


# ==========================================
# Helper Functions
# ==========================================

def _planning_session_to_dict(db_session: PlanningSession) -> Dict[str, Any]:
    """Convert PlanningSession model to dictionary"""
    return {
        "session_id": db_session.session_id,
        "project_name": db_session.project_name,
        "status": db_session.status,
        "village_data": db_session.village_data,
        "task_description": db_session.task_description,
        "constraints": db_session.constraints,

        "current_layer": db_session.current_layer,
        "previous_layer": db_session.previous_layer,
        "layer_1_completed": db_session.layer_1_completed,
        "layer_2_completed": db_session.layer_2_completed,
        "layer_3_completed": db_session.layer_3_completed,

        "need_human_review": db_session.need_human_review,
        "human_feedback": db_session.human_feedback,
        "need_revision": db_session.need_revision,

        "step_mode": db_session.step_mode,
        "pause_after_step": db_session.pause_after_step,
        "waiting_for_review": db_session.pause_after_step,  # ✅ 派生值

        "output_path": db_session.output_path,
        "state_snapshot": db_session.state_snapshot,
        "request_params": db_session.request_params,

        "events": db_session.events or [],
        "execution_complete": db_session.execution_complete,
        "execution_error": db_session.execution_error,

        "created_at": db_session.created_at.isoformat(),
        "updated_at": db_session.updated_at.isoformat(),
        "completed_at": db_session.completed_at.isoformat() if db_session.completed_at else None,
    }


def _ui_session_to_dict(db_session: UISession) -> Dict[str, Any]:
    """Convert UISession model to dictionary"""
    return {
        "conversation_id": db_session.conversation_id,
        "status": db_session.status,
        "project_name": db_session.project_name,
        "task_id": db_session.task_id,
        "created_at": db_session.created_at.isoformat(),
        "updated_at": db_session.updated_at.isoformat(),
    }


def _ui_message_to_dict(message: UIMessage) -> Dict[str, Any]:
    """Convert UIMessage model to dictionary"""
    return {
        "id": message.id,
        "session_id": message.session_id,
        "role": message.role,
        "content": message.content,
        "message_type": message.message_type,
        "metadata": message.message_metadata,
        "timestamp": message.timestamp.isoformat(),
    }


__all__ = [
    # Planning session operations
    "create_planning_session",
    "get_planning_session",
    "update_planning_session",
    "delete_planning_session",
    "list_planning_sessions",
    "update_session_state",
    "add_session_event",
    "get_session_events",

    # Checkpoint operations
    "create_checkpoint",
    "get_checkpoint",
    "list_checkpoints",
    "delete_checkpoint",

    # UI session operations
    "create_ui_session",
    "get_ui_session",
    "update_ui_session",
    "delete_ui_session",
    "list_ui_sessions",

    # UI message operations
    "create_ui_message",
    "get_ui_messages",
    "delete_ui_messages",
]
