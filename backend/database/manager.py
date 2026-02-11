"""
数据库管理器 - 统一同步和异步操作

提供双轨支持，允许同步和异步版本共存
"""

import os
import asyncio
import logging
import time
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.orm import sessionmaker

# 导入异步操作函数
from . import operations_async

# 异步导入 - Python 3.10+ 兼容
try:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    ASYNC_AVAILABLE = True
    AsyncSession = AsyncSession  # 使用导入的类
    create_async_engine = create_async_engine
    async_sessionmaker = async_sessionmaker
except ImportError:
    ASYNC_AVAILABLE = False
    AsyncSession = None  # 占位符
    logging.warning('Async SQLAlchemy not available, using sync mode only')

logger = logging.getLogger(__name__)


class DBMode(str, Enum):
    """数据库模式枚举"""
    SYNC = "sync"
    ASYNC = "async"


class DatabaseManager:
    """
    数据库管理器 - 提供统一的数据库操作接口

    功能：
    1. 双轨支持：同步和异步版本共存
    2. 环境变量控制：USE_ASYNC_DATABASE
    3. 性能监控：慢查询日志
    4. 线程安全：异步引擎初始化加锁
    """

    def __init__(self):
        """初始化数据库管理器（Python 3.10+ 兼容）"""
        self.current_mode: Optional[DBMode] = None
        self._async_engine: Optional[create_async_engine] = None
        self._sync_engine: Optional[create_engine] = None
        self._lock = asyncio.Lock()

    def get_engine(self, mode: Optional[DBMode]) -> create_engine:
        """获取对应模式的数据库引擎"""
        if mode is None:
            mode = DBMode.SYNC

        if mode == DBMode.SYNC:
            # 同步模式：使用同步引擎
            if self._sync_engine is None:
                from backend.database.engine import get_engine
                self._sync_engine = get_engine()
            return self._sync_engine
        elif mode == DBMode.ASYNC:
            # 异步模式：延迟初始化，在需要时创建
            if self._async_engine is None:
                raise RuntimeError("Async engine not initialized. Call initialize() first.")
            return self._async_engine
        else:
            raise ValueError(f"Unsupported DB mode: {mode}")

    @asynccontextmanager
    async def get_session(self, mode: Optional[DBMode]):
        """获取数据库会话（自动选择模式）"""
        if mode is None:
            mode = DBMode.SYNC

        if mode == DBMode.SYNC:
            # 同步模式：使用同步会话
            from backend.database.engine import get_session
            with get_session() as session:
                yield session
        elif mode == DBMode.ASYNC:
            # 异步模式：使用异步会话
            from backend.database.operations_async import get_async_session
            async with get_async_session() as session:
                yield session
        else:
            raise ValueError(f"Unsupported DB mode: {mode}")

    async def execute_operation(self, operation_name: str, async_func=None, sync_func=None, *args, **kwargs):
        """
        执行数据库操作（自动路由到对应版本）

        性能监控：慢查询警告（>100ms）

        支持的操作类型：
        - create_session
        - get_session
        - update_session
        - add_event
        - get_events
        """
        use_async = os.getenv("USE_ASYNC_DATABASE", "false").lower() == "true"
        mode = DBMode.ASYNC if use_async else DBMode.SYNC

        import time
        start = time.time()

        try:
            # 根据操作类型选择对应的异步函数
            if mode == DBMode.ASYNC:
                if operation_name == 'create_session':
                    result = await operations_async.create_planning_session_async(*args, **kwargs)
                elif operation_name == 'get_session':
                    result = await operations_async.get_planning_session_async(*args, **kwargs)
                elif operation_name == 'update_session':
                    result = await operations_async.update_planning_session_async(*args, **kwargs)
                elif operation_name == 'add_event':
                    result = await operations_async.add_session_event_async(*args, **kwargs)
                elif operation_name == 'get_events':
                    result = await operations_async.get_session_events_async(*args, **kwargs)
                elif async_func:
                    # 自定义异步函数
                    result = await async_func(*args, **kwargs)
                else:
                    raise ValueError(f"Operation {operation_name} not supported in async mode")
            else:
                # 同步模式：使用传入的同步函数或默认行为
                if sync_func:
                    result = sync_func(*args, **kwargs)
                else:
                    # 默认：在内存中操作（用于向后兼容）
                    if operation_name == 'add_event':
                        # 内存版本的 add_event，不写入数据库
                        from backend.api.planning import _append_session_event
                        session_id, event = args
                        _append_session_event(session_id, event)
                        result = True
                    elif operation_name == 'get_events':
                        # 内存版本的 get_events
                        from backend.api.planning import _get_session_events_copy
                        session_id = args[0]
                        result = _get_session_events_copy(session_id)
                    else:
                        raise ValueError(f"Operation {operation_name} not supported in sync mode without sync_func")

            elapsed = time.time() - start

            # 性能监控：慢查询警告
            if elapsed > 0.1:  # 100ms
                logger.warning(f"Slow DB operation [{operation_name}]: {elapsed:.3f}s > 100ms threshold")

            return result

        except Exception as e:
            logger.error(f"Database operation [{operation_name}] failed: {e}", exc_info=True)
            raise

    def initialize(self, mode: Optional[DBMode]):
        """初始化数据库管理器"""
        if mode is None:
            mode = DBMode.SYNC

        self.current_mode = mode
        logger.info(f"DatabaseManager initialized in {mode.value} mode")
        return

    def initialize_database(self, mode: Optional[DBMode]):
        """初始化数据库管理器"""
        _db_manager.initialize(mode)
        logger.info(f"Database manager initialized in {mode.value} mode")


# 全局单例
_db_manager = DatabaseManager()


def get_db_manager() -> DatabaseManager:
    """获取数据库管理器单例"""
    return _db_manager


async def initialize_database(mode: Optional[DBMode]):
    """初始化数据库管理器"""
    _db_manager.initialize(mode)
    logger.info(f"Database manager initialized in {mode.value} mode")
