"""
FastAPI Backend Application - 村庄规划智能体后端服务

Architecture:
- routes.py: Unified API router (aggregates all endpoints)
- services/: Legacy application orchestration being migrated to application/workflow
- database/: Async database operations
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.settings import (
    BACKEND_STARTUP_TIMEOUT_SECONDS, LOG_LEVEL, LOG_DIR, LOG_FILE_MAX_BYTES,
    LOG_FILE_BACKUP_COUNT, LOG_RETENTION_DAYS, PROJECT_ROOT, IS_PRODUCTION,
)
from app.infrastructure.logging import SessionFilter


def _select_log_dir() -> Path:
    """Choose a writable log directory before logging handlers are created."""
    configured = os.getenv("BACKEND_LOG_DIR", "").strip()
    candidates = [
        Path(configured) if configured else PROJECT_ROOT / "output" / "runtime-logs",
        Path(os.getenv("TEMP", ".")) / "village-planning-runtime-logs",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-probe"
            probe.touch()
            probe.unlink()
            return candidate
        except (OSError, PermissionError):
            continue
    raise RuntimeError("No writable runtime log directory is available")


LOG_DIR = _select_log_dir()

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
    "http://localhost:3000,http://localhost:3001,http://localhost:3002,"
    "http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002,"
    "http://localhost:8000,http://127.0.0.1:8000"
).split(",")



from app.bootstrap.lifespan import lifespan


# ============================================
# FastAPI Application
# ============================================

app = FastAPI(
    title="村庄规划智能体 API",
    description="基于LangGraph的村庄规划智能系统后端服务",
    version="1.1.0",
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
    allow_headers=["Content-Type", "Authorization", "Last-Event-ID"],
    expose_headers=["Content-Disposition"],
)

# Session ID injection middleware — extracts session_id from URL path
# so all downstream log records carry it automatically
from app.infrastructure.logging import set_session_id as _set_session_id
from starlette.requests import Request
from starlette.responses import Response


@app.middleware("http")
async def session_id_middleware(request: Request, call_next):
    path = request.url.path
    # Match the versioned session resource.
    import re
    m = re.search(r"/api/v1/sessions/([^/]+)", path)
    sid = m.group(1) if m else ""
    from app.infrastructure.logging import set_session_id, reset_session_id
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

def _v1_error(request_id: str, code: str, message: str, *, retryable: bool = False, details=None):
    return {
        "schema_version": "1.0",
        "code": code,
        "message": message,
        "request_id": request_id,
        "retryable": retryable,
        "details": details or {},
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if not request.url.path.startswith('/api/v1/'):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    request_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content=_v1_error(
            request_id,
            "NOT_FOUND" if exc.status_code == 404 else "REQUEST_REJECTED",
            str(exc.detail),
            retryable=exc.status_code >= 500,
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if not request.url.path.startswith('/api/v1/'):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    request_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=422,
        content=_v1_error(
            request_id,
            "VALIDATION_FAILED",
            "request validation failed",
            details={"errors": exc.errors()},
        ),
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception) -> JSONResponse:
    """Global exception handler"""
    request_id = str(uuid.uuid4())
    logger.error(f"Unhandled exception [{request_id}]: {exc}", exc_info=True)

    if request.url.path.startswith('/api/v1/'):
        return JSONResponse(
            status_code=500,
            content=_v1_error(
                request_id,
                "INTERNAL_ERROR",
                "An unexpected error occurred" if IS_PRODUCTION else str(exc),
                retryable=True,
            ),
        )
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
