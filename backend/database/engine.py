"""
Database engine and session management
数据库引擎和会话管理

Provides SQLite connection and session factory for both sync and async operations.
"""

import logging
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import atexit

logger = logging.getLogger(__name__)

# Global database directory
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "village_planning.db"

# ==========================================
# Sync Engine (保留用于向后兼容)
# ==========================================

# Database URL
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Engine
engine = None
_engine_ref_count = 0

# Session factory
SessionLocal = None


def get_engine():
    """
    Get or create database engine (with reference counting)
    获取或创建数据库引擎（带引用计数）
    
    Deprecated: 建议使用异步版本 get_async_engine()
    """
    global engine, _engine_ref_count

    if engine is None:
        # Ensure data directory exists
        DB_DIR.mkdir(parents=True, exist_ok=True)

        # Create engine with SQLite configuration
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )

        # Register cleanup function with atexit
        atexit.register(dispose_engine)
        logger.info(f"[Sync DB] Database engine created: {DB_PATH}")

    _engine_ref_count += 1
    return engine


def dispose_engine():
    """
    Close database engine when reference count reaches zero
    引用计数为零时关闭数据库引擎
    
    Deprecated: 建议使用异步版本 dispose_async_engine()
    """
    global engine, _engine_ref_count

    _engine_ref_count -= 1

    if _engine_ref_count <= 0 and engine is not None:
        engine.dispose()
        engine = None
        logger.info("[Sync DB] Database engine disposed")


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Get database session (dependency injection)
    获取数据库会话（依赖注入）

    Yields:
        Session: SQLModel session

    Example:
        with get_session() as session:
            session.add(session_obj)
            session.commit()
    
    Deprecated: 建议使用异步版本 get_async_session()
    """
    global SessionLocal

    if SessionLocal is None:
        engine = get_engine()
        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine
        )

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> bool:
    """
    Initialize database tables
    初始化数据库表

    Creates all tables if they don't exist.

    Returns:
        bool: True if successful
    
    Deprecated: 建议使用异步版本 init_async_db()
    """
    try:
        engine = get_engine()

        # Import all models to ensure they are registered with SQLModel
        from .models import PlanningSession, Checkpoint, UISession, UIMessage

        # Create all tables
        SQLModel.metadata.create_all(engine)

        logger.info("[Sync DB] Database tables initialized successfully")
        return True
    except Exception as e:
        logger.error(f"[Sync DB] Failed to initialize database: {e}", exc_info=True)
        return False


# ==========================================
# Async Engine (主要实现)
# ==========================================

# Async database URL
ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# Async engine
async_engine = None
_async_engine_ref_count = 0

# Async session factory
AsyncSessionLocal = None


async def get_async_engine() -> create_async_engine:
    """
    Get or create async database engine (with reference counting)
    获取或创建异步数据库引擎（带引用计数）
    
    Returns:
        AsyncEngine: The async database engine
    """
    global async_engine, _async_engine_ref_count
    
    if async_engine is None:
        # Ensure data directory exists
        DB_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create async engine with SQLite configuration
        async_engine = create_async_engine(
            ASYNC_DATABASE_URL,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        logger.info(f"[Async DB] Async database engine created: {DB_PATH}")
    
    _async_engine_ref_count += 1
    return async_engine


async def dispose_async_engine() -> None:
    """
    Close async database engine when reference count reaches zero
    引用计数为零时关闭异步数据库引擎
    """
    global async_engine, _async_engine_ref_count
    
    _async_engine_ref_count -= 1
    
    if _async_engine_ref_count <= 0 and async_engine is not None:
        await async_engine.dispose()
        async_engine = None
        logger.info("[Async DB] Async database engine disposed")


@asynccontextmanager
async def get_async_session() -> AsyncSession:
    """
    Get async database session (dependency injection)
    获取异步数据库会话（依赖注入）

    Yields:
        AsyncSession: SQLAlchemy async session

    Example:
        async with get_async_session() as session:
            session.add(session_obj)
            await session.commit()
    """
    global AsyncSessionLocal
    
    if AsyncSessionLocal is None:
        engine = await get_async_engine()
        AsyncSessionLocal = async_sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine
        )
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_async_db() -> bool:
    """
    Initialize database tables with async engine
    使用异步引擎初始化数据库表

    Creates all tables if they don't exist.

    Returns:
        bool: True if successful
    """
    try:
        engine = await get_async_engine()

        # Import all models to ensure they are registered with SQLModel
        from .models import PlanningSession, Checkpoint, UISession, UIMessage

        # Create all tables
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        logger.info("[Async DB] Database tables initialized successfully")
        return True
    except Exception as e:
        logger.error(f"[Async DB] Failed to initialize database: {e}", exc_info=True)
        return False


def get_db_path() -> Path:
    """
    Get database file path
    获取数据库文件路径

    Returns:
        Path: Database file path
    """
    return DB_PATH


__all__ = [
    # Sync functions (deprecated, kept for backward compatibility)
    "get_session",
    "init_db",
    "get_engine",
    "dispose_engine",
    # Async functions (recommended)
    "get_async_session",
    "init_async_db",
    "get_async_engine",
    "dispose_async_engine",
    # Utilities
    "get_db_path",
]
