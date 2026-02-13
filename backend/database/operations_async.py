"""
Async Database Operations
异步数据库操作

Provides async versions of database operations for non-blocking I/O.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# 导入数据库路径配置
from backend.database.engine import DB_PATH
from backend.database.models import PlanningSession

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
        logger.info(f"Initializing Async Engine with URL: {async_database_url}")
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
async def get_async_session() -> AsyncSession:
    """
    Get async database session
    获取异步数据库会话
    """
    global AsyncSessionLocal

    # 1. 确保 Engine 和 SessionMaker 已初始化
    if AsyncSessionLocal is None:
        await get_async_engine()

    # 2. 使用 SessionMaker 创建会话
    # 注意：这里直接使用 AsyncSessionLocal() 作为上下文管理器
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Session rollback due to exception: {e}")
            await session.rollback()
            raise
        finally:
            # async_sessionmaker 自动处理 close，但显式关闭是个好习惯
            await session.close()

# ============================================
# Async CRUD Operations
# ============================================

async def create_planning_session_async(state: Dict[str, Any]) -> str:
    """
    Async version of create_planning_session
    创建规划会话（异步版本）
    """
    async with get_async_session() as session:
        from .serialization import make_json_serializable
        clean_state = make_json_serializable(state)   # ⭐ 深度清洗

        db_session = PlanningSession(
            session_id=clean_state["session_id"],
            project_name=clean_state.get("project_name", ""),
            status="running",
            current_layer=clean_state.get("current_layer", 1),
            village_data=clean_state.get("village_data"),
            task_description=clean_state.get("task_description"),
            constraints=clean_state.get("constraints"),
            previous_layer=clean_state.get("previous_layer"),
            layer_1_completed=clean_state.get("layer_1_completed", False),
            layer_2_completed=clean_state.get("layer_2_completed", False),
            layer_3_completed=clean_state.get("layer_3_completed", False),
            need_human_review=clean_state.get("need_human_review", False),
            human_feedback=clean_state.get("human_feedback"),
            need_revision=clean_state.get("need_revision", False),
            step_mode=clean_state.get("step_mode", False),
            pause_after_step=clean_state.get("pause_after_step", False),
            output_path=clean_state.get("output_path"),
            state_snapshot=clean_state.get("state_snapshot"),      # ✅ JSON字段
            request_params=clean_state.get("request_params"),      # ✅ JSON字段
            events=clean_state.get("events", []),                 # ✅ JSON字段
            execution_complete=clean_state.get("execution_complete", False),
            execution_error=clean_state.get("execution_error"),
            created_at=datetime.now(),
            updated_at=datetime.now(),
            completed_at=clean_state.get("completed_at"),
            progress=clean_state.get("progress", 0),
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
    updates: Dict[str, Any]
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
    添加事件到 JSON 字段
    """
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(PlanningSession)
                .where(PlanningSession.session_id == session_id)
            )
            db_session = result.scalar_one_or_none()

            if not db_session:
                return False

            # 处理 JSON 字段的追加逻辑
            # 注意：在某些 SQL 数据库中，需要重新赋值整个列表才能触发更新
            current_events = list(db_session.events) if db_session.events else []
            current_events.append(event)
            
            # 显式重新赋值
            db_session.events = current_events
            db_session.updated_at = datetime.now()

            await session.commit()
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
        result = await session.execute(
            select(PlanningSession)
            .where(PlanningSession.session_id == session_id)
        )

        db_session = result.scalar_one_or_none()

        if db_session and db_session.events:
            return db_session.events

        return []
