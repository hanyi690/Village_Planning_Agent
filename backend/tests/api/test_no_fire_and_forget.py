"""Architecture guard: no bare fire-and-forget tasks in session routes.

All background graph-execution tasks must be routed through the composition
root's TaskSupervisor (for per-session deduplication and cancellation), not
spawned with bare ``asyncio.create_task``.
"""

from __future__ import annotations

import inspect

from app.api import session_routes


def test_no_bare_create_task_in_session_routes():
    source = inspect.getsource(session_routes)
    assert "asyncio.create_task" not in source