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

    async def cancel(self, key: str) -> None:
        task = self._tasks.pop(key, None)
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[TaskSupervisor] task %s raised during cancel: %s", key, exc)

    async def cancel_all(self) -> None:
        keys = list(self._tasks.keys())
        tasks = [self._tasks.pop(key, None) for key in keys]
        to_wait = [t for t in tasks if t is not None and not t.done()]
        for t in to_wait:
            t.cancel()
        if to_wait:
            await asyncio.gather(*to_wait, return_exceptions=True)
        self._tasks.clear()

    @property
    def active_count(self) -> int:
        return len(self._tasks)


__all__ = ["TaskSupervisor"]
