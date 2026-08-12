"""
Async retry utility with exponential backoff and jitter.

Aligns with LangGraph AsyncCallerParams defaults: maxRetries=4.
Handles: RateLimitError (429), APIConnectionError, InternalServerError (500).
"""

import asyncio
import logging
import random
from typing import Any, Callable, TypeVar, Awaitable

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_EXCEPTIONS = (
    "RateLimitError",
    "APIConnectionError",
    "ConnectionError",
    "InternalServerError",
)

MAX_RETRIES = 4


def _is_retryable(exception: Exception) -> bool:
    for name in RETRYABLE_EXCEPTIONS:
        if name in type(exception).__name__:
            return True

    status_code = getattr(exception, "status_code", None)
    if status_code in (429, 500, 502, 503, 504):
        return True

    http_status = getattr(exception, "http_status", None)
    if http_status in (429, 500, 502, 503, 504):
        return True

    return False


async def async_retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    max_retries: int = MAX_RETRIES,
    min_wait: float = 1.0,
    max_wait: float = 60.0,
) -> T:
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as e:
            last_exception = e
            if not _is_retryable(e):
                raise

            if attempt < max_retries:
                wait = min(max_wait, min_wait * (2 ** attempt))
                jitter = random.uniform(0, wait * 0.5)
                total_wait = wait + jitter

                logger.warning(
                    f"[Retry] Attempt {attempt + 1}/{max_retries} failed "
                    f"({type(e).__name__}), retrying in {total_wait:.1f}s"
                )
                await asyncio.sleep(total_wait)

    raise last_exception


__all__ = ["async_retry_with_backoff", "MAX_RETRIES"]
