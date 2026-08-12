"""
Async Rate Limiter for LLM and Embedding API calls.

Wraps LangChain's InMemoryRateLimiter for RPM control plus asyncio.Semaphore
for concurrent request limiting. Follows the official two-level control pattern:
1. RPM check (token bucket) — prevents rate-limit errors
2. Semaphore acquire — limits concurrent in-flight requests

Key design: RPM check BEFORE semaphore (prevents head-of-line blocking).

Usage:
    limiter = AsyncRateLimiter(requests_per_second=500, max_concurrent=20)
    await limiter.acquire()
    try:
        result = await llm.ainvoke(prompt)
    finally:
        limiter.release()
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    """Two-level rate limiter: InMemoryRateLimiter (RPM) + asyncio.Semaphore (concurrency).

    Strict acquire() order: RPM check first, then semaphore.
    """

    def __init__(
        self,
        requests_per_second: float = 500.0,
        max_concurrent: int = 20,
        warmup_seconds: float = 0.0,
    ):
        try:
            from langchain_core.rate_limiters import InMemoryRateLimiter
        except ImportError:
            raise ImportError(
                "langchain-core>=0.2.24 required for InMemoryRateLimiter. "
                "Install with: pip install langchain-core>=0.2.24"
            )

        self._rpm_limiter = InMemoryRateLimiter(
            requests_per_second=requests_per_second,
            check_every_n_seconds=0.1,
            max_bucket_size=requests_per_second,
        )
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._warmup_seconds = warmup_seconds
        self._start_time: Optional[float] = None
        self._acquire_count = 0

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def _warmup_limit(self) -> int:
        if self._warmup_seconds <= 0 or self._start_time is None:
            return self._max_concurrent

        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._warmup_seconds:
            return self._max_concurrent

        progress = elapsed / self._warmup_seconds
        limit = max(1, int(self._max_concurrent * progress))
        return min(limit, self._max_concurrent)

    async def acquire(self) -> None:
        if self._start_time is None:
            self._start_time = time.monotonic()

        warmup_limit = self._warmup_limit()
        if warmup_limit < self._max_concurrent:
            await asyncio.sleep(0.05)

        # Step 1: RPM check (must come first; InMemoryRateLimiter.acquire is sync)
        self._rpm_limiter.acquire()

        # Step 2: concurrency semaphore (async)
        await self._semaphore.acquire()
        self._acquire_count += 1

    def release(self) -> None:
        self._semaphore.release()

    def update_rate_limit(self, requests_per_second: float) -> None:
        self._rpm_limiter.max_bucket_size = requests_per_second
        logger.debug(f"[AsyncRateLimiter] Rate limit updated to {requests_per_second} rps")


# Global rate limiter instances (lazy init)
_llm_rate_limiter: Optional[AsyncRateLimiter] = None
_embedding_rate_limiter: Optional[AsyncRateLimiter] = None
_lock = asyncio.Lock()


async def get_llm_rate_limiter(
    requests_per_second: float = 500.0,
    max_concurrent: int = 50,
    warmup_seconds: float = 5.0,
) -> AsyncRateLimiter:
    global _llm_rate_limiter
    if _llm_rate_limiter is None:
        async with _lock:
            if _llm_rate_limiter is None:
                _llm_rate_limiter = AsyncRateLimiter(
                    requests_per_second=requests_per_second,
                    max_concurrent=max_concurrent,
                    warmup_seconds=warmup_seconds,
                )
                logger.info(
                    f"[RateLimiter] LLM rate limiter created: rps={requests_per_second}, "
                    f"max_concurrent={max_concurrent}, warmup={warmup_seconds}s"
                )
    return _llm_rate_limiter


async def get_embedding_rate_limiter(
    requests_per_second: float = 25.0,
    max_concurrent: int = 10,
) -> AsyncRateLimiter:
    global _embedding_rate_limiter
    if _embedding_rate_limiter is None:
        async with _lock:
            if _embedding_rate_limiter is None:
                _embedding_rate_limiter = AsyncRateLimiter(
                    requests_per_second=requests_per_second,
                    max_concurrent=max_concurrent,
                    warmup_seconds=1.0,
                )
                logger.info(
                    f"[RateLimiter] Embedding rate limiter created: rps={requests_per_second}, "
                    f"max_concurrent={max_concurrent}"
                )
    return _embedding_rate_limiter


__all__ = ["AsyncRateLimiter", "get_llm_rate_limiter", "get_embedding_rate_limiter"]
