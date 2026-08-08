"""
FastAPI Backend Application - 村庄规划智能体后端服务

Architecture:
- routes.py: Unified API router (aggregates all endpoints)
- services/: Business logic (planning_service, sse_manager, checkpoint_service)
- database/: Async database operations
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.settings import (
    BACKEND_STARTUP_TIMEOUT_SECONDS, LOG_LEVEL, LOG_DIR, LOG_FILE_MAX_BYTES,
    LOG_FILE_BACKUP_COUNT, LOG_RETENTION_DAYS, PROJECT_ROOT, IS_PRODUCTION,
)
from app.utils.logger import SessionFilter, ensure_log_dir

# Ensure log directory exists before configuring handlers
ensure_log_dir()

# Keep runtime logs in a fresh workspace-owned directory. Historical log files
# may be owned by another Windows sandbox identity and cannot be reopened.
LOG_DIR = PROJECT_ROOT / "output" / "runtime-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging with dictConfig to avoid duplicate handlers
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "session_filter": {
            "()": SessionFilter,
        }
    },
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        },
        "session_aware": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - [%(session_id)s] %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "session_aware",
            "filters": ["session_filter"],
            "stream": sys.stdout
        },
        # 全量日志：按日轮转，保留 LOG_RETENTION_DAYS 天
        "file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(LOG_DIR / "planning.log"),
            "when": "midnight",
            "interval": 1,
            "backupCount": max(LOG_RETENTION_DAYS, 7),
            "formatter": "session_aware",
            "filters": ["session_filter"],
            "encoding": "utf-8"
        },
        # 错误日志：单独文件，只记录 ERROR 及以上
        "error_file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "filename": str(LOG_DIR / "planning.error.log"),
            "when": "midnight",
            "interval": 1,
            "backupCount": max(LOG_RETENTION_DAYS, 7),
            "formatter": "session_aware",
            "filters": ["session_filter"],
            "encoding": "utf-8",
            "level": logging.ERROR
        }
    },
    "root": {
        "level": getattr(logging, LOG_LEVEL, logging.INFO),
        "handlers": ["console", "file", "error_file"]
    },
    "loggers": {
        "uvicorn": {"level": "INFO", "handlers": ["console", "file", "error_file"], "propagate": False},
        "uvicorn.error": {"level": "INFO", "handlers": ["console", "file", "error_file"], "propagate": False},
        "uvicorn.access": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"}
    }
}

logging.config.dictConfig(LOGGING_CONFIG)

logger = logging.getLogger(__name__)

# Environment configuration
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:8000"
).split(",")


# ============================================
# Application Lifecycle
# ============================================

def _cleanup_old_logs():
    """Delete log files older than LOG_RETENTION_DAYS."""
    import glob
    import time

    cutoff = time.time() - LOG_RETENTION_DAYS * 86400
    patterns = ["planning.log*", "planning.error.log*"]
    deleted = 0

    for pattern in patterns:
        for path in glob.glob(str(LOG_DIR / pattern)):
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    deleted += 1
            except OSError:
                pass

    if deleted:
        logger.info("🧹 Log cleanup: removed %d old log files (retention=%d days)", deleted, LOG_RETENTION_DAYS)


async def _sse_cleanup_loop():
    """Periodic SSE session cleanup — removes expired session data every 10 minutes."""
    while True:
        await asyncio.sleep(600)
        try:
            from app.services.sse import sse_manager
            sse_manager.cleanup_expired_sessions()
        except Exception as e:
            logger.error(f"SSE cleanup failed: {e}")


async def _log_cleanup_loop():
    """Periodic log cleanup — runs once per day."""
    while True:
        await asyncio.sleep(86400)  # 24 hours
        try:
            _cleanup_old_logs()
        except Exception as e:
            logger.error(f"Log cleanup failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    logger.info(f"🚀 村庄规划智能体后端启动中...")
    logger.info(f"📁 Project root: {PROJECT_ROOT}")
    logger.info(f"📁 Working directory: {os.getcwd()}")

    app.state.readiness = {"database": "starting", "checkpointer": "starting", "langgraph": "starting"}
    try:
        async with asyncio.timeout(BACKEND_STARTUP_TIMEOUT_SECONDS):
            from app.database import init_async_db
            if not await init_async_db():
                raise RuntimeError("database initialization returned false")
            from app.services.composition import CompositionRoot
            CompositionRoot.initialize()
            from app.services.runtime import PlanningRuntimeService
            await PlanningRuntimeService.initialize()
    except Exception:
        logger.exception("Core backend startup failed")
        app.state.readiness = {"database": "failed", "checkpointer": "failed", "langgraph": "failed"}
        raise
    app.state.readiness = {"database": "ready", "checkpointer": "ready", "langgraph": "ready"}

    # Save event loop for cross-thread SSE publishing
    from app.services.sse import sse_manager
    sse_manager.save_event_loop(asyncio.get_running_loop())
    logger.info("🧹 SSE event loop saved")

    logger.info("✅ 后端服务启动完成")

    # Startup log cleanup
    _cleanup_old_logs()

    # Periodic SSE session cleanup (every 10 minutes)
    sse_cleanup_task = asyncio.create_task(_sse_cleanup_loop())
    # Periodic log cleanup (every 24 hours)
    log_cleanup_task = asyncio.create_task(_log_cleanup_loop())

    yield

    # Cancel periodic cleanups
    for task in [sse_cleanup_task, log_cleanup_task]:
        task.cancel()
    for task in [sse_cleanup_task, log_cleanup_task]:
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Clean up resources
    logger.info("🧹 Cleaning up resources...")
    try:
        from app.services.runtime import PlanningRuntimeService
        await PlanningRuntimeService.shutdown()
    except Exception as e:
        logger.error(f"❌ Failed to cancel runtime tasks: {e}", exc_info=True)
    try:
        from app.database import dispose_async_engine
        async with asyncio.timeout(5):
            await dispose_async_engine()
        logger.info("✅ Database engine disposed")
    except Exception as e:
        logger.error(f"❌ Failed to dispose database engine: {e}", exc_info=True)
    try:
        from app.database import shutdown_database
        await shutdown_database()
        logger.info("✅ Database connections fully shutdown")
    except Exception as e:
        logger.error(f"❌ Failed to shutdown database: {e}", exc_info=True)

    logger.info("👋 后端服务关闭")


# ============================================
# FastAPI Application
# ============================================

app = FastAPI(
    title="村庄规划智能体 API",
    description="基于LangGraph的村庄规划智能系统后端服务",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS configuration
# Note: allow_credentials=True requires explicit origins (not ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Disposition"],
)

# Session ID injection middleware — extracts session_id from URL path
# so all downstream log records carry it automatically
from app.utils.logger import set_session_id as _set_session_id
from starlette.requests import Request
from starlette.responses import Response


@app.middleware("http")
async def session_id_middleware(request: Request, call_next):
    path = request.url.path
    # Match /api/sessions/{session_id}/...
    import re
    m = re.search(r"/api/sessions/([^/]+)", path)
    sid = m.group(1) if m else ""
    from app.utils.logger import set_session_id, reset_session_id
    token = set_session_id(sid)
    try:
        response: Response = await call_next(request)
    finally:
        reset_session_id(token)
    return response

# Include unified router (aggregates all API routes)
from app.api.routes import router
app.include_router(router)


# ============================================
# Health Check & Root Endpoints
# ============================================

@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint"""
    return {
        "status": "alive",
        "service": "village-planning-backend",
        "version": "1.0.0"
    }


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root endpoint"""
    return {
        "message": "村庄规划智能体 API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# ============================================
# Error Handlers
# ============================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    """Global exception handler"""
    request_id = str(uuid.uuid4())
    logger.error(f"Unhandled exception [{request_id}]: {exc}", exc_info=True)

    if IS_PRODUCTION:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
                "request_id": request_id
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": str(exc),
                "type": type(exc).__name__,
                "request_id": request_id
            }
        )


# ============================================
# Run Server (for development)
# ============================================

if __name__ == "__main__":
    import uvicorn
    BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=BACKEND_PORT,
        reload=True,
        log_level="info"
    )
