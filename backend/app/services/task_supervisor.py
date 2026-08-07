from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TaskSupervisor:
    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}

    def create_task(self, key: str, coro: Any) -> asyncio.Task:
        old = self._tasks.get(key)
        if old and not old.done():
            old.cancel()
        task = asyncio.create_task(coro)
        self._tasks[key] = task

        def _done_callback(t: asyncio.Task) -> None:
            self._tasks.pop(key, None)
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.error("[TaskSupervisor] task %s failed: %s", key, exc)

        task.add_done_callback(_done_callback)
        return task

    def cancel(self, key: str) -> None:
        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

    async def cancel_all(self) -> None:
        keys = list(self._tasks.keys())
        for key in keys:
            self.cancel(key)
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    @property
    def active_count(self) -> int:
        return len(self._tasks)


__all__ = ["TaskSupervisor"]
