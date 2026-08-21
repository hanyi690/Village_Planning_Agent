"""Bounded LLM-call budget shared by one grounding execution."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar


_T = TypeVar("_T")


def new_ground_llm_budget() -> Dict[str, Any]:
    """Create the independent, loop-local budget for one grounding run."""
    from app.core.settings import (
        GROUND_LLM_CALL_TIMEOUT_S,
        GROUND_LLM_MAX_CONCURRENT,
        GROUND_MAX_LLM_CALLS,
    )

    max_calls = max(0, int(GROUND_MAX_LLM_CALLS))
    call_timeout = max(0.001, float(GROUND_LLM_CALL_TIMEOUT_S))
    max_concurrent = max(1, int(GROUND_LLM_MAX_CONCURRENT))
    return {
        "remaining": max_calls,
        "reserved": 0,
        "completed": 0,
        "failed": 0,
        "provider_unavailable": False,
        "deadline": time.monotonic() + call_timeout * max(1, max_calls),
        "call_timeout": call_timeout,
        "max_concurrent": max_concurrent,
        "semaphore": asyncio.Semaphore(max_concurrent),
        "sync_semaphore": threading.BoundedSemaphore(max_concurrent),
        "reservation_lock": threading.Lock(),
    }


def get_ground_llm_budget(
    owner: Any = None,
    *,
    scope_key: str = "default",
) -> Dict[str, Any]:
    """Return one transient budget for one owner and request scope.

    The budget contains loop/thread synchronization primitives and therefore
    must never be persisted in an artifact or workflow state.  A context can
    be reused by multiple requests; changing ``scope_key`` replaces the old
    transient budget so an exhausted request cannot poison the next one.
    """
    if owner is None:
        budget = new_ground_llm_budget()
        budget["scope_key"] = str(scope_key or "default")
        return budget
    normalized_scope = str(scope_key or "default")
    current_scope = getattr(owner, "_ground_llm_budget_scope", "")
    current = getattr(owner, "_ground_llm_budget", None)
    if current is None or current_scope != normalized_scope:
        current = new_ground_llm_budget()
        current["scope_key"] = normalized_scope
        setattr(owner, "_ground_llm_budget", current)
        setattr(owner, "_ground_llm_budget_scope", normalized_scope)
    return current


def reserve_ground_llm_call(budget: Optional[Dict[str, Any]]) -> float | None:
    """Atomically reserve one call and return its remaining timeout."""
    if budget is None:
        from app.core.settings import GROUND_LLM_CALL_TIMEOUT_S

        return max(0.001, float(GROUND_LLM_CALL_TIMEOUT_S))

    lock = budget.get("reservation_lock")
    if lock is None:
        # Compatibility for callers that construct a small test budget by
        # hand.  Production budgets always carry the lock above.
        lock = threading.Lock()
        budget["reservation_lock"] = lock
    with lock:
        remaining = int(budget.get("remaining", 0) or 0)
        if bool(budget.get("provider_unavailable", False)):
            return None
        deadline = float(budget.get("deadline", 0.0) or 0.0)
        seconds = min(
            max(0.001, float(budget.get("call_timeout", 30.0) or 30.0)),
            max(0.0, deadline - time.monotonic()),
        )
        if remaining <= 0 or seconds <= 0:
            return None
        budget["remaining"] = remaining - 1
        budget["reserved"] = int(budget.get("reserved", 0) or 0) + 1
        return seconds


def mark_ground_llm_provider_unavailable(
    budget: Optional[Dict[str, Any]],
    exc: BaseException,
) -> bool:
    """Stop this grounding wave after a non-recoverable provider response.

    Grounding calls are best-effort.  A quota/rate-limit response cannot be
    repaired by sending the next mention, so continuing to reserve calls only
    creates a serial tail of identical failures.  The flag is scoped to the
    current grounding budget; later workflow stages may still use their own
    independent policy when a provider is available again.
    """
    if budget is None:
        return False
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    text = str(exc).lower()
    non_recoverable = status == 429 or any(
        marker in text
        for marker in (
            "rate_limit",
            "rate limit",
            "token plan",
            "用量上限",
            "quota",
            "insufficient_quota",
        )
    )
    if not non_recoverable:
        return False
    lock = budget.get("reservation_lock")
    if lock is None:
        lock = threading.Lock()
        budget["reservation_lock"] = lock
    with lock:
        budget["provider_unavailable"] = True
        budget["provider_error"] = str(exc)[:500]
    return True


def ground_llm_semaphore(budget: Optional[Dict[str, Any]]) -> asyncio.Semaphore:
    """Return the shared concurrency gate, or a serial compatibility gate."""
    semaphore = budget.get("semaphore") if budget else None
    return semaphore or asyncio.Semaphore(1)


def ground_llm_sync_semaphore(budget: Optional[Dict[str, Any]]) -> threading.BoundedSemaphore:
    """Return the concurrency gate for synchronous resolver call sites."""
    semaphore = budget.get("sync_semaphore") if budget else None
    return semaphore or threading.BoundedSemaphore(1)


async def run_ground_llm_call(
    budget: Optional[Dict[str, Any]],
    timeout: float,
    operation: Callable[[], Awaitable[_T]],
) -> _T:
    """Run one grounding call with queue wait included in its budget.

    The semaphore acquisition is deliberately inside ``wait_for``.  Otherwise
    a call can spend its entire per-call budget waiting behind earlier calls
    and still start a provider request after the deadline has expired.
    """
    async def _run() -> _T:
        async with ground_llm_semaphore(budget):
            return await operation()

    try:
        result = await asyncio.wait_for(_run(), timeout=max(0.001, float(timeout)))
        if budget is not None:
            budget["completed"] = int(budget.get("completed", 0) or 0) + 1
        return result
    except Exception as exc:
        if budget is not None:
            budget["failed"] = int(budget.get("failed", 0) or 0) + 1
        mark_ground_llm_provider_unavailable(budget, exc)
        raise


__all__ = [
    "ground_llm_semaphore",
    "ground_llm_sync_semaphore",
    "get_ground_llm_budget",
    "new_ground_llm_budget",
    "mark_ground_llm_provider_unavailable",
    "reserve_ground_llm_call",
    "run_ground_llm_call",
]
