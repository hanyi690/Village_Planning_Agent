from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def build_summary_task_key(
    session_id: str,
    layer: int,
    dimension: str,
    version: int,
    report_id: str = "",
) -> str:
    identity = f"{session_id}:summary:{layer}:{dimension}:{version}"
    return f"{identity}:{report_id}" if report_id else identity


class TaskSupervisor:
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}

    def create_task(self, key: str, coro: Any) -> asyncio.Task:
        old = self._tasks.get(key)
        if old is not None and not old.done():
            old.cancel()

        task = asyncio.create_task(coro)
        self._tasks[key] = task

        def _done_callback(t: asyncio.Task) -> None:
            current = self._tasks.get(key)
            if current is t:
                self._tasks.pop(key, None)
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.error("[TaskSupervisor] task %s failed: %s", key, exc)

        task.add_done_callback(_done_callback)
        return task

    async def _cancel_many(self, keys: list[str]) -> None:
        to_wait: list[tuple[str, asyncio.Task]] = []
        for key in keys:
            task = self._tasks.pop(key, None)
            if task is None or task.done():
                continue
            task.cancel()
            to_wait.append((key, task))

        if not to_wait:
            return

        results = await asyncio.gather(
            *(task for _, task in to_wait),
            return_exceptions=True,
        )
        for (key, _), result in zip(to_wait, results):
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.error("[TaskSupervisor] task %s raised during cancel: %s", key, result)

    async def cancel(self, key: str) -> None:
        await self._cancel_many([key])

    async def cancel_session(self, session_id: str) -> None:
        owned_prefix = f"{session_id}:"
        owned_keys = [
            key for key in list(self._tasks.keys())
            if key == session_id or key.startswith(owned_prefix)
        ]
        await self._cancel_many(owned_keys)

    async def cancel_all(self) -> None:
        await self._cancel_many(list(self._tasks.keys()))
        self._tasks.clear()

    @property
    def active_count(self) -> int:
        return len(self._tasks)

__all__ = ["TaskSupervisor", "build_summary_task_key"]
