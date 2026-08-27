"""FastAPI lifespan wiring for the village planning backend.

Extracted from ``app.main`` so the application object stays thin and the
lifecycle can be reused by scripts and acceptance runs.
"""

from __future__ import annotations

import asyncio
import glob as _glob
import logging
import os

from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def _cleanup_old_logs(log_dir: Path, retention_days: int) -> None:
    """Delete log files older than the retention window."""
    import time

    cutoff = time.time() - retention_days * 86400
    patterns = ["planning.log*", "planning.error.log*"]
    deleted = 0

    for pattern in patterns:
        for path in _glob.glob(str(log_dir / pattern)):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    deleted += 1
            except OSError:
                pass

    if deleted:
        logger.info(
            "Log cleanup: removed %d old log files (retention=%d days)",
            deleted,
            retention_days,
        )


async def _log_cleanup_loop(log_dir: Path, retention_days: int) -> None:
    """Periodic log cleanup - runs once per day."""
    while True:
        await asyncio.sleep(86400)
        try:
            _cleanup_old_logs(log_dir, retention_days)
        except Exception as exc:  # noqa: BLE001 - cleanup must never crash the loop
            logger.error("Log cleanup failed: %s", exc)


@asynccontextmanager
async def lifespan(app):
    """Application lifecycle management (blueprint M9/M10 bootstrap)."""
    from app.core.settings import (
        BACKEND_STARTUP_TIMEOUT_SECONDS,
        PROJECT_ROOT,
        LOG_RETENTION_DAYS,
    )
    from app.bootstrap.composition import CompositionRoot

    log_dir = Path(os.getenv("BACKEND_LOG_DIR", "").strip() or PROJECT_ROOT / "output" / "runtime-logs")

    logger.info("Village planning backend starting")
    app.state.readiness = {"database": "starting", "checkpointer": "starting", "langgraph": "starting"}
    try:
        async with asyncio.timeout(BACKEND_STARTUP_TIMEOUT_SECONDS):
            from app.database import init_async_db
            if not await init_async_db():
                raise RuntimeError("database initialization returned false")
            CompositionRoot.initialize()
            from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
            await PlanningRuntimeService.initialize()
    except Exception:
        logger.exception("Core backend startup failed")
        app.state.readiness = {"database": "failed", "checkpointer": "failed", "langgraph": "failed"}
        raise
    app.state.readiness = {"database": "ready", "checkpointer": "ready", "langgraph": "ready"}

    from app.infrastructure.search.provider_registry import configure_external_provider
    configure_external_provider(app)

    from app.infrastructure.events import event_hub
    event_hub.save_event_loop(asyncio.get_running_loop())
    logger.info("SSE event loop saved")
    logger.info("Backend service startup complete")

    # A process restart drops asyncio background tasks, but LangGraph keeps
    # pending cursors in checkpoints.db.  Scan and schedule only recoverable
    # cursors after the core runtime is ready; HUMAN interrupts stay parked.
    recovery_task = asyncio.create_task(
        PlanningRuntimeService.recover_inflight_sessions()
    )

    log_cleanup_task = asyncio.create_task(
        _log_cleanup_loop(log_dir, LOG_RETENTION_DAYS)
    )

    yield

    log_cleanup_task.cancel()
    try:
        await log_cleanup_task
    except asyncio.CancelledError:
        pass

    recovery_task.cancel()
    try:
        await recovery_task
    except asyncio.CancelledError:
        pass

    logger.info("Cleaning up resources...")
    try:
        from app.infrastructure.search.provider_registry import close_external_provider
        await close_external_provider(app)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to close external evidence provider: %s", exc, exc_info=True)
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
        await PlanningRuntimeService.shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to cancel runtime tasks: %s", exc, exc_info=True)
    try:
        from app.infrastructure.llm.instructor_client import close_cached_clients
        await close_cached_clients()
        logger.info("Structured LLM clients closed")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to close structured LLM clients: %s", exc, exc_info=True)
    try:
        from app.database import dispose_async_engine
        async with asyncio.timeout(5):
            await dispose_async_engine()
        logger.info("Database engine disposed")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to dispose database engine: %s", exc, exc_info=True)
    try:
        from app.database import shutdown_database
        await shutdown_database()
        logger.info("Database connections fully shutdown")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to shutdown database: %s", exc, exc_info=True)
    try:
        from app.infrastructure.kg.session_kg import shutdown_session_kg_process_pool
        await asyncio.to_thread(shutdown_session_kg_process_pool)
        logger.info("Session KG worker pool shutdown")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to shutdown Session KG worker pool: %s", exc, exc_info=True)

    logger.info("Backend service closed")


__all__ = ["lifespan"]
