"""P1: TaskSupervisor replace race + cancel-then-await."""

import asyncio

import pytest

from app.services.task_supervisor import TaskSupervisor


@pytest.mark.asyncio
async def test_replace_does_not_lose_new_task():
    sup = TaskSupervisor()
    started = asyncio.Event()
    old_task = asyncio.create_task(started.wait())
    sup._tasks["k"] = old_task

    async def new_coro():
        await asyncio.sleep(10)

    new_task = sup.create_task("k", new_coro())
    await asyncio.sleep(0.1)
    assert "k" in sup._tasks
    assert sup._tasks["k"] is new_task
    new_task.cancel()
    try:
        await new_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_cancel_all_awaits_all_tasks():
    sup = TaskSupervisor()
    finished = []

    async def slow():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            finished.append("cancelled")
            raise

    sup.create_task("a", slow())
    sup.create_task("b", slow())
    await asyncio.sleep(0)
    await sup.cancel_all()
    assert len(finished) == 2


@pytest.mark.asyncio
async def test_cancel_key_awaits_task():
    sup = TaskSupervisor()
    done = asyncio.Event()

    async def coro():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            done.set()
            raise

    t = sup.create_task("k", coro())
    await asyncio.sleep(0)
    await sup.cancel("k")
    assert done.is_set()
    assert t.done()
