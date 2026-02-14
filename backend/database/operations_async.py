"""
Async Database CRUD Operations
异步数据库 CRUD 操作

High-level async database operations for planning sessions, checkpoints,
and UI conversations using SQLAlchemy async support.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlmodel import SQLModel

from .engine import get_async_session
from .models import (
    PlanningSession,
    Checkpoint,
    UISession,
    UIMessage
)

logger = logging.getLogger(__name__)


# ==========================================
# Helper Functions
# ==========================================

def make_json_serializable(obj: Any) -> Any:
    """
    Recursively convert non-JSON serializable types to serializable types
    递归转换不可JSON序列化的类型为可序列化类型
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, set):
        return list(obj)  # set → list
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_serializable(i) for i in obj]
    # Other non-serializable objects → convert to string
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)


def _planning_session_to_dict(db_session: PlanningSession) -> Dict[str, Any]:
    """Convert PlanningSession model to dictionary"""
    return {
        "session_id": db_session.session_id,
        "project_name": db_session.project_name,
        "status": db_session.status,
        "execution_error": db_session.execution_error,
        "village_data": db_session.village_data,
        "task_description": db_session.task_description,
        "constraints": db_session.constraints,
        "output_path": db_session.output_path,
        "created_at": db_session.created_at.isoformat() if db_session.created_at else None,
        "updated_at": db_session.updated_at.isoformat() if db_session.updated_at else None,
        "completed_at": db_session.completed_at.isoformat() if db_session.completed_at else None,
    }


def _checkpoint_to_dict(db_checkpoint: Checkpoint) -> Dict[str, Any]:
    """Convert Checkpoint model to dictionary"""
    return {
        "checkpoint_id": db_checkpoint.checkpoint_id,
        "session_id": db_checkpoint.session_id,
        "layer": db_checkpoint.layer,
        "description": db_checkpoint.description,
        "state_snapshot": db_checkpoint.state_snapshot,
        "checkpoint_metadata": db_checkpoint.checkpoint_metadata,
        "timestamp": db_checkpoint.timestamp.isoformat() if db_checkpoint.timestamp else None,
    }


def _ui_session_to_dict(db_session: UISession) -> Dict[str, Any]:
    """Convert UISession model to dictionary"""
    return {
        "conversation_id": db_session.conversation_id,
        "status": db_session.status,
        "project_name": db_session.project_name,
        "task_id": db_session.task_id,
        "created_at": db_session.created_at.isoformat() if db_session.created_at else None,
        "updated_at": db_session.updated_at.isoformat() if db_session.updated_at else None,
    }


def _ui_message_to_dict(db_message: UIMessage) -> Dict[str, Any]:
    """Convert UIMessage model to dictionary"""
    return {
        "id": db_message.id,
        "session_id": db_message.session_id,
        "role": db_message.role,
        "content": db_message.content,
        "message_type": db_message.message_type,
        "message_metadata": db_message.message_metadata,
        "timestamp": db_message.timestamp.isoformat() if db_message.timestamp else None,
    }


# ==========================================
# Planning Session Operations
# ==========================================

async def create_planning_session_async(state: Dict[str, Any]) -> str:
    """
    Create planning session (async)
    
    Args:
        state: Session state dictionary
        
    Returns:
        str: Session ID
    """
    clean_state = make_json_serializable(state)
    
    async with get_async_session() as session:
        db_session = PlanningSession(
            session_id=clean_state["session_id"],
            project_name=clean_state.get("project_name", ""),
            status="running",
            village_data=clean_state.get("village_data") or "",
            task_description=clean_state.get("task_description", "制定村庄总体规划方案"),
            constraints=clean_state.get("constraints", "无特殊约束"),
            output_path=clean_state.get("output_path"),
            completed_at=clean_state.get("completed_at"),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(db_session)
        await session.commit()
        await session.refresh(db_session)
        logger.info(f"[Async DB] Created planning session: {db_session.session_id}")
        return db_session.session_id


async def get_planning_session_async(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get planning session by ID (async)
    
    Args:
        session_id: Session ID
        
    Returns:
        Dict with session data, or None if not found
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                return None
            
            return _planning_session_to_dict(db_session)
    except Exception as e:
        logger.error(f"[Async DB] Failed to get planning session {session_id}: {e}", exc_info=True)
        return None


async def update_planning_session_async(
    session_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    Update planning session (async)
    
    Args:
        session_id: Session ID
        updates: Fields to update
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] Session {session_id} not found")
                return False
            
            for key, value in updates.items():
                if hasattr(db_session, key):
                    setattr(db_session, key, value)
            
            db_session.updated_at = datetime.now()
            await session.commit()
            logger.info(f"[Async DB] Updated planning session: {session_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to update planning session {session_id}: {e}", exc_info=True)
        return False


async def delete_planning_session_async(session_id: str) -> bool:
    """
    Delete planning session (async)
    
    Args:
        session_id: Session ID
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] Session {session_id} not found")
                return False
            
            await session.delete(db_session)
            await session.commit()
            logger.info(f"[Async DB] Deleted planning session: {session_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete planning session {session_id}: {e}", exc_info=True)
        return False


async def list_planning_sessions_async(
    project_name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    List planning sessions (async)
    
    Args:
        project_name: Filter by project name
        status: Filter by status
        limit: Maximum number of results
        
    Returns:
        List of session dictionaries
    """
    try:
        async with get_async_session() as session:
            query = select(PlanningSession)
            
            if project_name:
                query = query.where(PlanningSession.project_name == project_name)
            
            if status:
                query = query.where(PlanningSession.status == status)
            
            query = query.order_by(PlanningSession.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            sessions = result.scalars().all()
            
            return [_planning_session_to_dict(s) for s in sessions]
    except Exception as e:
        logger.error(f"[Async DB] Failed to list planning sessions: {e}", exc_info=True)
        return []


async def update_session_state_async(session_id: str, state: Dict[str, Any]) -> bool:
    """
    Update session state (async)
    
    Args:
        session_id: Session ID
        state: State dictionary
        
    Returns:
        bool: True if successful
    """
    clean_state = make_json_serializable(state)
    
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] Session {session_id} not found")
                return False
            
            for key, value in clean_state.items():
                if hasattr(db_session, key) and key not in [
                    "current_layer", "layer_1_completed", "layer_2_completed",
                    "layer_3_completed", "pause_after_step", "waiting_for_review"
                ]:
                    setattr(db_session, key, value)
            
            db_session.updated_at = datetime.now()
            await session.commit()
            logger.info(f"[Async DB] Updated session state: {session_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to update session state {session_id}: {e}", exc_info=True)
        return False


async def add_session_event_async(session_id: str, event: Dict[str, Any]) -> bool:
    """
    Add event to session (async)
    
    Note: Events are now managed by AsyncSqliteSaver in checkpoints table.
    This function is kept for compatibility but does nothing.
    
    Args:
        session_id: Session ID
        event: Event dictionary
        
    Returns:
        bool: True (always returns True for compatibility)
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(PlanningSession).where(PlanningSession.session_id == session_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                return False
            
            await session.commit()
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to add event to session {session_id}: {e}", exc_info=True)
        return False


async def get_session_events_async(session_id: str) -> List[Dict[str, Any]]:
    """
    Get session events (async)
    
    Note: Events are now managed by AsyncSqliteSaver in checkpoints table.
    This function returns empty list for compatibility.
    
    Args:
        session_id: Session ID
        
    Returns:
        List of event dictionaries (empty for now)
    """
    return []


# ==========================================
# Checkpoint Operations
# ==========================================

async def create_checkpoint_async(
    checkpoint_id: str,
    session_id: str,
    layer: int,
    description: str = "",
    state_snapshot: Dict[str, Any] = None,
    checkpoint_metadata: Dict[str, Any] = None
) -> bool:
    """
    Create checkpoint (async)
    
    Args:
        checkpoint_id: Checkpoint ID
        session_id: Session ID
        layer: Layer number
        description: Checkpoint description
        state_snapshot: State snapshot dictionary
        checkpoint_metadata: Checkpoint metadata
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_checkpoint = Checkpoint(
                checkpoint_id=checkpoint_id,
                session_id=session_id,
                layer=layer,
                description=description,
                state_snapshot=state_snapshot or {},
                checkpoint_metadata=checkpoint_metadata,
                timestamp=datetime.now(),
            )
            session.add(db_checkpoint)
            await session.commit()
            logger.info(f"[Async DB] Created checkpoint: {checkpoint_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to create checkpoint {checkpoint_id}: {e}", exc_info=True)
        return False


async def get_checkpoint_async(checkpoint_id: str) -> Optional[Dict[str, Any]]:
    """
    Get checkpoint by ID (async)
    
    Args:
        checkpoint_id: Checkpoint ID
        
    Returns:
        Dict with checkpoint data, or None if not found
    """
    try:
        async with get_async_session() as session:
            db_checkpoint = await session.execute(
                select(Checkpoint).where(Checkpoint.checkpoint_id == checkpoint_id)
            )
            db_checkpoint = db_checkpoint.scalar_one_or_none()
            
            if not db_checkpoint:
                return None
            
            return _checkpoint_to_dict(db_checkpoint)
    except Exception as e:
        logger.error(f"[Async DB] Failed to get checkpoint {checkpoint_id}: {e}", exc_info=True)
        return None


async def list_checkpoints_async(
    session_id: Optional[str] = None,
    layer: Optional[int] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    List checkpoints (async)
    
    Args:
        session_id: Filter by session ID
        layer: Filter by layer
        limit: Maximum number of results
        
    Returns:
        List of checkpoint dictionaries
    """
    try:
        async with get_async_session() as session:
            query = select(Checkpoint)
            
            if session_id:
                query = query.where(Checkpoint.session_id == session_id)
            
            if layer is not None:
                query = query.where(Checkpoint.layer == layer)
            
            query = query.order_by(Checkpoint.timestamp.desc()).limit(limit)
            
            result = await session.execute(query)
            checkpoints = result.scalars().all()
            
            return [_checkpoint_to_dict(c) for c in checkpoints]
    except Exception as e:
        logger.error(f"[Async DB] Failed to list checkpoints: {e}", exc_info=True)
        return []


async def delete_checkpoint_async(checkpoint_id: str) -> bool:
    """
    Delete checkpoint (async)
    
    Args:
        checkpoint_id: Checkpoint ID
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_checkpoint = await session.execute(
                select(Checkpoint).where(Checkpoint.checkpoint_id == checkpoint_id)
            )
            db_checkpoint = db_checkpoint.scalar_one_or_none()
            
            if not db_checkpoint:
                logger.error(f"[Async DB] Checkpoint {checkpoint_id} not found")
                return False
            
            await session.delete(db_checkpoint)
            await session.commit()
            logger.info(f"[Async DB] Deleted checkpoint: {checkpoint_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete checkpoint {checkpoint_id}: {e}", exc_info=True)
        return False


# ==========================================
# UI Session Operations
# ==========================================

async def create_ui_session_async(
    conversation_id: str,
    session_type: str = "conversation",
    project_name: Optional[str] = None,
    task_id: Optional[str] = None
) -> str:
    """
    Create UI session (async)
    
    Args:
        conversation_id: Conversation ID
        session_type: Session type
        project_name: Project name
        task_id: Task ID
        
    Returns:
        str: Conversation ID
    """
    async with get_async_session() as session:
        db_session = UISession(
            conversation_id=conversation_id,
            status="idle",
            project_name=project_name,
            task_id=task_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(db_session)
        await session.commit()
        await session.refresh(db_session)
        logger.info(f"[Async DB] Created UI session: {conversation_id}")
        return db_session.conversation_id


async def get_ui_session_async(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Get UI session by ID (async)
    
    Args:
        conversation_id: Conversation ID
        
    Returns:
        Dict with session data, or None if not found
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                return None
            
            return _ui_session_to_dict(db_session)
    except Exception as e:
        logger.error(f"[Async DB] Failed to get UI session {conversation_id}: {e}", exc_info=True)
        return None


async def update_ui_session_async(
    conversation_id: str,
    updates: Dict[str, Any]
) -> bool:
    """
    Update UI session (async)
    
    Args:
        conversation_id: Conversation ID
        updates: Fields to update
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] UI session {conversation_id} not found")
                return False
            
            for key, value in updates.items():
                if hasattr(db_session, key):
                    setattr(db_session, key, value)
            
            db_session.updated_at = datetime.now()
            await session.commit()
            logger.info(f"[Async DB] Updated UI session: {conversation_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to update UI session {conversation_id}: {e}", exc_info=True)
        return False


async def delete_ui_session_async(conversation_id: str) -> bool:
    """
    Delete UI session (async)
    
    Args:
        conversation_id: Conversation ID
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            db_session = await session.execute(
                select(UISession).where(UISession.conversation_id == conversation_id)
            )
            db_session = db_session.scalar_one_or_none()
            
            if not db_session:
                logger.error(f"[Async DB] UI session {conversation_id} not found")
                return False
            
            await session.delete(db_session)
            await session.commit()
            logger.info(f"[Async DB] Deleted UI session: {conversation_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete UI session {conversation_id}: {e}", exc_info=True)
        return False


async def list_ui_sessions_async(
    status: Optional[str] = None,
    task_id: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    List UI sessions (async)
    
    Args:
        status: Filter by status
        task_id: Filter by task ID
        limit: Maximum number of results
        
    Returns:
        List of session dictionaries
    """
    try:
        async with get_async_session() as session:
            query = select(UISession)
            
            if status:
                query = query.where(UISession.status == status)
            
            if task_id:
                query = query.where(UISession.task_id == task_id)
            
            query = query.order_by(UISession.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            sessions = result.scalars().all()
            
            return [_ui_session_to_dict(s) for s in sessions]
    except Exception as e:
        logger.error(f"[Async DB] Failed to list UI sessions: {e}", exc_info=True)
        return []


# ==========================================
# UI Message Operations
# ==========================================

async def create_ui_message_async(
    session_id: str,
    role: str,
    content: str,
    message_type: str = "text",
    metadata: Optional[Dict[str, Any]] = None
) -> int:
    """
    Create UI message (async)
    
    Args:
        session_id: Session ID
        role: Message role (user/assistant/system)
        content: Message content
        message_type: Message type
        metadata: Message metadata
        
    Returns:
        int: Message ID
    """
    async with get_async_session() as session:
        db_message = UIMessage(
            session_id=session_id,
            role=role,
            content=content,
            message_type=message_type,
            message_metadata=metadata,
            timestamp=datetime.now(),
        )
        session.add(db_message)
        await session.commit()
        await session.refresh(db_message)
        logger.info(f"[Async DB] Created UI message: {db_message.id}")
        return db_message.id


async def get_ui_messages_async(
    session_id: str,
    role: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Get UI messages for a session (async)
    
    Args:
        session_id: Session ID
        role: Filter by role
        limit: Maximum number of results
        
    Returns:
        List of message dictionaries
    """
    try:
        async with get_async_session() as session:
            query = select(UIMessage).where(UIMessage.session_id == session_id)
            
            if role:
                query = query.where(UIMessage.role == role)
            
            query = query.order_by(UIMessage.timestamp.asc()).limit(limit)
            
            result = await session.execute(query)
            messages = result.scalars().all()
            
            return [_ui_message_to_dict(m) for m in messages]
    except Exception as e:
        logger.error(f"[Async DB] Failed to get UI messages for session {session_id}: {e}", exc_info=True)
        return []


async def delete_ui_messages_async(session_id: str, role: Optional[str] = None) -> bool:
    """
    Delete UI messages for a session (async)
    
    Args:
        session_id: Session ID
        role: Filter by role (optional)
        
    Returns:
        bool: True if successful
    """
    try:
        async with get_async_session() as session:
            query = select(UIMessage).where(UIMessage.session_id == session_id)
            
            if role:
                query = query.where(UIMessage.role == role)
            
            result = await session.execute(query)
            messages = result.scalars().all()
            
            for message in messages:
                await session.delete(message)
            
            await session.commit()
            logger.info(f"[Async DB] Deleted {len(messages)} UI messages for session {session_id}")
            return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to delete UI messages for session {session_id}: {e}", exc_info=True)
        return False