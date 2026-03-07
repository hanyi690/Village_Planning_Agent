"""
Database engine and session management
数据库引擎和会话管理

Provides SQLite connection and session factory for async operations.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

logger = logging.getLogger(__name__)

# Global database directory
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "village_planning.db"


# ==========================================
# Async Engine
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
        
        # 启用 WAL 模式以提高并发写入安全性
        from sqlalchemy import event
        
        @event.listens_for(async_engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.close()
        
        logger.info("[Async DB] WAL mode enabled")
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
        # Note: Checkpoint is excluded because it's now managed by LangGraph's AsyncSqliteSaver
        from .models import PlanningSession, UISession, UIMessage

        # Create all tables (except checkpoints, which is managed by LangGraph)
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
    # Async functions
    "get_async_session",
    "init_async_db",
    "get_async_engine",
    "dispose_async_engine",
    # Utilities
    "get_db_path",
]