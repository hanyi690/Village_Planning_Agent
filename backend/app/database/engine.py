"""
Database engine and session management
数据库引擎和会话管理

Provides SQLite connection and session factory for async operations.
"""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.core.settings import DATABASE_DIR

logger = logging.getLogger(__name__)

# Database path from settings
DB_PATH = DATABASE_DIR / "village_planning.db"
CHECKPOINT_DB_PATH = DATABASE_DIR / "checkpoints.db"


# ==========================================
# Async Engine
# ==========================================

# Async engine
async_engine: AsyncEngine | None = None
_engine_creation_lock = threading.Lock()

# Async session factory
AsyncSessionLocal: async_sessionmaker[AsyncSession] | None = None


async def get_async_engine() -> AsyncEngine:
    """
    Get or create the process-local async database engine.
    获取或创建进程级异步数据库引擎。
    
    Returns:
        AsyncEngine: The async database engine
    """
    global async_engine

    if async_engine is not None:
        return async_engine

    with _engine_creation_lock:
        if async_engine is not None:
            return async_engine

        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        async_engine = engine
        logger.info("[Async DB] WAL mode enabled")
        logger.info("[Async DB] Async database engine created: %s", DB_PATH)

    return async_engine


async def dispose_async_engine() -> None:
    """
    Dispose the application-owned engine and its session factory.
    释放应用级引擎及其会话工厂。
    """
    global async_engine, AsyncSessionLocal

    engine = async_engine
    async_engine = None
    AsyncSessionLocal = None

    if engine is not None:
        await engine.dispose()
        logger.info("[Async DB] Async database engine disposed")


async def shutdown_database() -> None:
    """Force-close ALL async connections so the process can exit.

    Fixes the hang: aiosqlite >= 0.22 worker threads are non-daemon and
    block on queue.get() unless the connection is closed.  Two sources are
    covered that ``dispose_async_engine`` cannot reach:
      1. the LangGraph checkpointer's bare aiosqlite connection (created
         directly in get_global_checkpointer, never through the engine);
      2. the engine itself when the reference count is unbalanced after a
         crash path (skips dispose silently).
    Safe to call multiple times; never raises.
    """
    try:
        await asyncio.wait_for(_shutdown_database_inner(), timeout=5)
    except asyncio.TimeoutError:
        logger.warning("[Async DB] shutdown exceeded 5s — leaving to process exit")
    except Exception as e:
        logger.warning("[Async DB] shutdown failed: %s", e)
    logger.info("[Async DB] All database connections shutdown")


async def _shutdown_database_inner() -> None:
    global _checkpointer, _checkpointer_initialized
    with _checkpointers_guard:
        checkpointers = list(_checkpointers_by_loop.values())
        if _checkpointer is not None and _checkpointer not in checkpointers:
            checkpointers.append(_checkpointer)
        _checkpointers_by_loop.clear()
        _checkpointer = None
        _checkpointer_initialized = False
    for saver in checkpointers:
        conn = getattr(saver, "conn", None)
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                try:
                    conn.stop()
                except Exception:
                    pass
    global async_engine, AsyncSessionLocal
    if async_engine is not None:
        try:
            await async_engine.dispose()
        except Exception:
            pass
        async_engine = None
    AsyncSessionLocal = None


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
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
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
        from .models import (
            PlanningSession,
            UISession,
            DimensionReport,
            UploadedFile,
            PlanningBundle,
            StepReportModel,
            RunEvent,
        )

        # Create all tables (except checkpoints, which is managed by LangGraph)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        # Run schema migrations for existing tables
        await _run_migrations(engine)

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


async def _run_migrations(engine) -> None:
    """Run schema migrations for existing tables (idempotent)."""
    from sqlalchemy import text

    table_migrations = {
        "planning_sessions": [
            ("village_name", "ALTER TABLE planning_sessions ADD COLUMN village_name TEXT DEFAULT ''"),
            ("province", "ALTER TABLE planning_sessions ADD COLUMN province TEXT DEFAULT ''"),
            ("city", "ALTER TABLE planning_sessions ADD COLUMN city TEXT DEFAULT ''"),
            ("county", "ALTER TABLE planning_sessions ADD COLUMN county TEXT DEFAULT ''"),
            ("township", "ALTER TABLE planning_sessions ADD COLUMN township TEXT DEFAULT ''"),
            ("planning_period", "ALTER TABLE planning_sessions ADD COLUMN planning_period TEXT DEFAULT '2022-2035年'"),
        ],
        "dimension_reports": [
            # P8: INSTRUCTION 结构化段独立列（剥离存储，不参与展示）
            ("instruction", "ALTER TABLE dimension_reports ADD COLUMN instruction TEXT"),
        ],
        "planning_bundles": [
            # P0-c: CAS blob descriptor reference for the bundle blob
            ("bundle_ref", "ALTER TABLE planning_bundles ADD COLUMN bundle_ref TEXT"),
        ],
    }

    async with engine.begin() as conn:
        for table, migrations in table_migrations.items():
            try:
                result = await conn.run_sync(
                    lambda sync_conn, t=table: sync_conn.execute(
                        text(f"PRAGMA table_info({t})")
                    )
                )
                existing = {row[1] for row in result.fetchall()}
            except Exception as e:
                logger.warning(f"[Migration] PRAGMA failed for {table}: {e}")
                continue

            for col_name, sql in migrations:
                if col_name not in existing:
                    try:
                        await conn.execute(text(sql))
                        logger.info(f"[Migration] Added column: {col_name}")
                    except Exception as e:
                        logger.warning(f"[Migration] Column {col_name} may already exist: {e}")


# ==========================================
# Global Checkpointer (LangGraph)
# ==========================================

_checkpointer = None
_checkpointer_lock = None
_checkpointer_initialized = False
_checkpointers_by_loop = {}
_checkpointers_guard = threading.RLock()


async def get_global_checkpointer():
    """
    Get global AsyncSqliteSaver instance (singleton pattern)

    Uses singleton pattern to avoid duplicate connection creation and setup() calls.
    This function initializes the checkpointer on first call and returns the same instance afterwards.

    Returns:
        AsyncSqliteSaver instance

    Raises:
        Exception: If initialization fails
    """
    import asyncio
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    global _checkpointer, _checkpointer_lock, _checkpointer_initialized

    loop = asyncio.get_running_loop()
    loop_key = id(loop)
    with _checkpointers_guard:
        existing = _checkpointers_by_loop.get(loop_key)
    if existing is not None:
        _checkpointer = existing
        _checkpointer_initialized = True
        return existing

    if _checkpointer_lock is None or getattr(_checkpointer_lock, "_loop", loop) is not loop:
        _checkpointer_lock = asyncio.Lock()

    # Slow path: need initialization (with lock)
    async with _checkpointer_lock:
        with _checkpointers_guard:
            existing = _checkpointers_by_loop.get(loop_key)
        if existing is not None:
            _checkpointer = existing
            _checkpointer_initialized = True
            return existing

        try:
            logger.info("[Checkpointer] Initializing global AsyncSqliteSaver instance...")

            # Create connection
            CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(CHECKPOINT_DB_PATH, check_same_thread=False)

            # Enable WAL mode for better concurrent write safety
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            logger.info("[Checkpointer] WAL mode enabled")

            saver = AsyncSqliteSaver(conn)

            # Initialize table structure (only on first call)
            await saver.setup()

            with _checkpointers_guard:
                _checkpointers_by_loop[loop_key] = saver
            _checkpointer = saver
            _checkpointer_initialized = True
            logger.info("[Checkpointer] AsyncSqliteSaver initialized for event loop %s", loop_key)

            return saver

        except Exception as e:
            logger.error(f"[Checkpointer] Initialization failed: {e}", exc_info=True)
            raise


__all__ = [
    # Async functions
    "get_async_session",
    "init_async_db",
    "get_async_engine",
    "dispose_async_engine",
    "shutdown_database",
    # Utilities
    "get_db_path",
    # Checkpointer
    "get_global_checkpointer",
]
