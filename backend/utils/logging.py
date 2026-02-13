"""
Logging utilities for backend
Provides decorators and helpers for consistent logging with performance tracking
"""

import asyncio
import functools
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


def log_execution(module: str, action: str | None = None):
    """
    Decorator: Record function execution time and log with session tracking

    Usage:
        @log_execution("Planning", "start_planning")
        async def start_planning(session_id: str, ...):
            ...

    Args:
        module: Module name for logging
        action: Action name (defaults to function name)
    """
    def decorator(func: Callable) -> Callable:
        func_name = action or func.__name__

        # Check if function is async
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # Try to extract session_id from arguments
                session_id = _extract_session_id(args, kwargs)
                sid_str = f" [{session_id}]" if session_id else ""

                logger.info(f"[{module}]{sid_str} {func_name} - 开始执行")

                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    elapsed = (time.time() - start_time) * 1000
                    logger.info(f"[{module}]{sid_str} {func_name} - 执行完成 ({elapsed:.2f}ms)")
                    return result
                except Exception as e:
                    elapsed = (time.time() - start_time) * 1000
                    logger.error(f"[{module}]{sid_str} {func_name} - 执行失败 ({elapsed:.2f}ms): {e}", exc_info=True)
                    raise

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                session_id = _extract_session_id(args, kwargs)
                sid_str = f" [{session_id}]" if session_id else ""

                logger.info(f"[{module}]{sid_str} {func_name} - 开始执行")

                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    elapsed = (time.time() - start_time) * 1000
                    logger.info(f"[{module}]{sid_str} {func_name} - 执行完成 ({elapsed:.2f}ms)")
                    return result
                except Exception as e:
                    elapsed = (time.time() - start_time) * 1000
                    logger.error(f"[{module}]{sid_str} {func_name} - 执行失败 ({elapsed:.2f}ms): {e}", exc_info=True)
                    raise

            return sync_wrapper

    return decorator


def _extract_session_id(args: tuple, kwargs: dict) -> str | None:
    """
    Try to extract session_id from function arguments

    Args:
        args: Positional arguments
        kwargs: Keyword arguments

    Returns:
        session_id if found, None otherwise
    """
    # Check in kwargs first
    if "session_id" in kwargs:
        return kwargs["session_id"]

    # Check in args (commonly first or second argument)
    for arg in args[:3]:  # Check first 3 args
        if isinstance(arg, str) and len(arg) > 10:  # session_id is usually a string like "20250208_143015"
            # Check if it looks like a session_id (format: YYYYMMDD_HHMMSS)
            if "_" in arg and len(arg) <= 20:
                return arg

    # Check if first arg has session_id attribute
    if len(args) > 0 and hasattr(args[0], "session_id"):
        return args[0].session_id

    return None
