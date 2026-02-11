"""
Async Database Operations
异步数据库操作

Provides async versions of database operations for non-blocking I/O.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import SQLModel, select, Session
from sqlmodel.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession as SQLAsyncSession

# 导入数据库路径配置
from backend.database.engine import DB_PATH

logger = logging.getLogger(__name__)

# Async database URL - 使用与同步数据库相同的路径配置
async_database_url = f"sqlite+aiosqlite:///{DB_PATH}"

# Async engine
async_engine = None
AsyncSessionLocal = None


async def get_async_engine():
    """
    Get or create async database engine
    获取或创建异步数据库引擎
    """
    global async_engine, AsyncSessionLocal

    if async_engine is None:
        async_engine = create_async_engine(
            async_database_url,
            connect_args={"check_same_thread": False},
        )

        AsyncSessionLocal = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        logger.info("Async database engine created")

    return async_engine


async def dispose_async_engine():
    """
    Close async database engine
    关闭异步数据库引擎
    """
    global async_engine, AsyncSessionLocal

    if async_engine is not None:
        await async_engine.dispose()
        async_engine = None
        AsyncSessionLocal = None
        logger.info("Async database engine disposed")


@asynccontextmanager
async def get_async_session() -> SQLAsyncSession:
    """
    Get async database session
    获取异步数据库会话
    """
    async with get_async_engine() as engine:
        async with AsyncSessionLocal() as session:
            yield session


# ============================================
# Async CRUD Operations
# ============================================

async def create_planning_session_async(state: Dict[str, Any]) -> str:
    """
    Async version of create_planning_session
    创建规划会话（异步版本）
    """
    async with get_async_session() as session:
        db_session = PlanningSession(
            session_id=state["session_id"],
            project_name=state.get("project_name", ""),
            status="running",
            current_layer=state.get("current_layer", 1),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            request=state.get("request", {}),
            initial_state=state.get("initial_state", {}),
            layer_1_completed=False,
            layer_2_completed=False,
            layer_3_completed=False,
            pause_after_step=state.get("pause_after_step", False),
            waiting_for_review=False,
            last_checkpoint_id=state.get("last_checkpoint_id"),
            execution_complete=False,
            execution_error=None,
            progress=0,
        )

        session.add(db_session)
        await session.commit()
        await session.refresh(db_session)

        logger.info(f"Created planning session: {db_session.session_id}")
        return db_session.session_id


async def get_planning_session_async(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Async version of get_planning_session
    获取规划会话（异步版本）
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(PlanningSession)
            .where(PlanningSession.session_id == session_id)
        )

        db_session = result.scalar_one_or_none()
        return db_session.__dict__ if db_session else None


async def update_planning_session_async(
    session_id: str,
    **updates: Dict[str, Any]
) -> bool:
    """
    Async version of update_planning_session
    更新规划会话（异步版本）
    """
    try:
        async with get_async_session() as session:
            # Get session
            result = await session.execute(
                select(PlanningSession)
                .where(PlanningSession.session_id == session_id)
            )
            db_session = result.scalar_one_or_none()

            if not db_session:
                logger.error(f"Session not found: {session_id}")
                return False

            # Update fields
            for key, value in updates.items():
                if hasattr(db_session, key):
                    setattr(db_session, key, value)

            db_session.updated_at = datetime.now()
            await session.commit()

        logger.info(f"Updated session {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to update session {session_id}: {e}", exc_info=True)
        return False


async def add_session_event_async(
    session_id: str,
    event: Dict[str, Any]
) -> bool:
    """
    Async version of add_session_event
    添加会话事件（异步版本）
    """
    try:
        async with get_async_session() as session:
            # Import here to avoid circular import
            from backend.database.models import SessionEvent

            # Check if session exists
            result = await session.execute(
                select(SessionEvent)
                .where(SessionEvent.session_id == session_id)
                .order_by(SessionEvent.timestamp.desc())
            )

            db_event = result.scalar_one_or_none()

            if db_event:
                # Parse existing events
                events = []
                if db_event.events:
                    try:
                        events = json.loads(db_event.events)
                    except Exception:
                        events = []

                # Append new event
                events.append(event)

                # Update
                db_event.events = json.dumps(events)
                db_event.updated_at = datetime.now()

                await session.commit()

        logger.info(f"Added event to session {session_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to add event to session {session_id}: {e}", exc_info=True)
        return False


async def get_session_events_async(session_id: str) -> List[Dict[str, Any]]:
    """
    Async version of get_session_events
    获取会话事件列表（异步版本）
    """
    async with get_async_session() as session:
        # Import here to avoid circular import
        from backend.database.models import SessionEvent

        result = await session.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session_id)
        )

        db_event = result.scalar_one_or_none()

        if db_event and db_event.events:
            try:
                events = json.loads(db_event.events)
                return events
            except Exception:
                return []

        return []
