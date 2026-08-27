"""Backend pytest bootstrap when tests run from the backend directory."""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest


BACKEND_ROOT = Path(__file__).resolve().parent
_PYTEST_TEMP_PREFIX = "run-"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# pytest's rootdir is selected from backend/pytest.ini even when the command
# is launched from the repository root.  Fixture discovery must therefore not
# depend on the caller's current directory.
def pytest_collection_modifyitems(items):
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
        elif "/tests/acceptance/" in path:
            item.add_marker(pytest.mark.acceptance)
        elif "/tests/characterization/" in path:
            item.add_marker(pytest.mark.characterization)
        elif "/tests/contracts/" in path:
            item.add_marker(pytest.mark.contracts)
        elif "/tests/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/tests/core/" in path:
            item.add_marker(pytest.mark.unit)


def pytest_configure(config):
    """Use an isolated workspace-owned base directory for every test session."""
    if config.option.basetemp:
        return
    configured_root = os.getenv("PYTEST_DEBUG_TEMPROOT")
    base_root = (
        Path(configured_root)
        if configured_root
        else Path(tempfile.gettempdir()) / "village-planning-agent-pytest"
    )
    base_root.mkdir(parents=True, exist_ok=True)
    run_dir = base_root / f"{_PYTEST_TEMP_PREFIX}{uuid4().hex}"
    config.option.basetemp = str(run_dir)
    config._village_owned_basetemp = run_dir


def pytest_sessionfinish(session, exitstatus):
    """Release process-owned async resources, then remove successful temp data."""

    async def _shutdown_runtime_resources() -> None:
        from app.database.engine import shutdown_database
        from app.infrastructure.llm.instructor_client import close_cached_clients
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )

        await PlanningRuntimeService.shutdown()
        await shutdown_database()
        await close_cached_clients()

    try:
        asyncio.run(_shutdown_runtime_resources())
    except Exception as exc:
        # A failed cleanup must stay visible, but pytest still needs to finish
        # its own reporting and exact-PID recovery remains available to the
        # caller.  Individual cleanup functions are idempotent and already
        # contain their own bounded close paths.
        print(f"pytest session resource cleanup failed: {type(exc).__name__}: {exc}")
    run_dir = getattr(session.config, "_village_owned_basetemp", None)
    if exitstatus == 0 and isinstance(run_dir, Path) and run_dir.name.startswith(_PYTEST_TEMP_PREFIX):
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _close_session_kg_process_pool():
    """Ensure isolated KG workers do not outlive the pytest session."""
    yield
    from app.infrastructure.kg.session_kg import shutdown_session_kg_process_pool

    shutdown_session_kg_process_pool()
