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

logger = logging.getLogger(__name__)


# Global database directory
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "village_planning.db"

# Database URL
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Engine
engine = None

# Session factory
SessionLocal = None


def get_engine():
    """
    Get or create database engine
    获取或创建数据库引擎
    """
    global engine

    if engine is None:
        # Ensure data directory exists
        DB_DIR.mkdir(parents=True, exist_ok=True)

        # Create engine with SQLite configuration
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},  # Required for SQLite
            echo=False  # Set to True for SQL query logging
        )

        logger.info(f"Database engine created: {DB_PATH}")

    return engine


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
    "get_db_path",
]
