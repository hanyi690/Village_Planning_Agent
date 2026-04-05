"""
Planning API Startup - 初始化和清理

应用启动事件和后台清理任务。
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from backend.constants import (
    MAX_SESSION_EVENTS,
    EVENT_CLEANUP_INTERVAL_SECONDS,
    SESSION_TTL_HOURS,
)
from backend.services.sse_manager import sse_manager

logger = logging.getLogger(__name__)

# Cleanup task management
_cleanup_task: Optional[asyncio.Task] = None
_cleanup_running = False

# Global event loop reference
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None


async def on_startup():
    """应用启动时调用"""
    global _main_event_loop
    _main_event_loop = asyncio.get_running_loop()
    sse_manager.save_event_loop(_main_event_loop)
    logger.info("[Planning API] 主事件循环已保存，跨线程事件发布已启用")

    # Start cleanup task
    await start_session_cleanup()


async def on_shutdown():
    """应用关闭时调用"""
    await stop_session_cleanup()


async def start_session_cleanup() -> None:
    """启动会话清理后台任务"""
    global _cleanup_task, _cleanup_running

    if _cleanup_running:
        logger.warning("[Session Cleanup] 清理任务已在运行中")
        return

    _cleanup_running = True
    _cleanup_task = asyncio.create_task(_session_cleanup_loop())
    logger.info(f"[Session Cleanup] 清理任务已启动 (TTL: {SESSION_TTL_HOURS}h, 间隔: {EVENT_CLEANUP_INTERVAL_SECONDS}s)")


async def stop_session_cleanup() -> None:
    """停止会话清理后台任务"""
    global _cleanup_task, _cleanup_running

    if not _cleanup_running or _cleanup_task is None:
        return

    _cleanup_running = False

    try:
        _cleanup_task.cancel()
        await _cleanup_task
    except asyncio.CancelledError:
        pass

    _cleanup_task = None
    logger.info("[Session Cleanup] 清理任务已停止")


async def _session_cleanup_loop() -> None:
    """会话清理循环"""
    while True:
        try:
            await asyncio.sleep(EVENT_CLEANUP_INTERVAL_SECONDS)

            cutoff_time = datetime.now() - timedelta(hours=SESSION_TTL_HOURS)
            cleaned = sse_manager.cleanup_expired_sessions(cutoff_time)

            total = sum(cleaned.values())
            if total > 0:
                logger.info(f"[Session Cleanup] 清理完成: {cleaned}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[Session Cleanup] 清理失败: {e}", exc_info=True)


__all__ = [
    "on_startup",
    "on_shutdown",
    "start_session_cleanup",
    "stop_session_cleanup",
]