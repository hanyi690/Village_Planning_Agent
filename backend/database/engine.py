"""
Database engine and session management
数据库引擎和会话管理

Provides SQLite connection and session factory.
"""

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.orm import sessionmaker
import atexit

logger = logging.getLogger(__name__)

# Global database directory
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "village_planning.db"

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
        logger.info(f"Database engine created: {DB_PATH}")

    _engine_ref_count += 1
    return engine


def dispose_engine():
    """
    Close database engine when reference count reaches zero
    引用计数为零时关闭数据库引擎
    """
    global engine, _engine_ref_count

    _engine_ref_count -= 1

    if _engine_ref_count <= 0 and engine is not None:
        engine.dispose()
        engine = None
        logger.info("Database engine disposed")


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
    """
    try:
        engine = get_engine()

        # Import all models to ensure they are registered with SQLModel
        from .models import PlanningSession, Checkpoint, UISession, UIMessage

        # Create all tables
        SQLModel.metadata.create_all(engine)

        logger.info("Database tables initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
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
    "get_session",
    "init_db",
    "get_engine",
    "dispose_engine",
    "get_db_path",
]
