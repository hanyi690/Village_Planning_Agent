"""
FastAPI Backend Application - 村庄规划智能体后端服务

Architecture:
- routes.py: Unified API router (aggregates all endpoints)
- services/: Business logic (planning_service, sse_manager, checkpoint_service)
- database/: Async database operations
"""

from __future__ import annotations

# CRITICAL: Set HuggingFace mirror before any imports
import os
os.environ['HF_ENDPOINT'] = os.getenv('HF_ENDPOINT', 'https://hf-mirror.com')

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

# from app.api.validate_config import validate_config  # 移除：模块不存在
# from app.utils.paths import ...  # 移除：使用 settings.PROJECT_ROOT
from app.core.settings import LOG_LEVEL

# Configure logging with dictConfig to avoid duplicate handlers
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": sys.stdout
        }
    },
    "root": {
        "level": getattr(logging, LOG_LEVEL, logging.INFO),
        "handlers": ["console"]
    },
    "loggers": {
        "uvicorn": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "uvicorn.error": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "uvicorn.access": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"}
    }
}

logging.config.dictConfig(LOGGING_CONFIG)

logger = logging.getLogger(__name__)

# Environment configuration
IS_PRODUCTION = os.getenv("ENVIRONMENT") == "production"
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000"
).split(",")


# ============================================
# Application Lifecycle
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    from app.core.settings import PROJECT_ROOT, setup_huggingface_env

    # Setup HuggingFace environment
    setup_huggingface_env()

    logger.info(f"🚀 村庄规划智能体后端启动中...")
    logger.info(f"📁 Project root: {PROJECT_ROOT}")
    logger.info(f"📁 Working directory: {os.getcwd()}")

    # Initialize async database
    logger.info("🗄️  Initializing database...")
    try:
        from app.database import init_async_db
        if await init_async_db():
            logger.info("✅ Database initialized successfully")
        else:
            logger.error("❌ Database initialization failed")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}", exc_info=True)

    # Initialize PlanningRuntimeService (LangGraph runtime singleton)
    logger.info("🔧 Initializing PlanningRuntimeService...")
    try:
        from app.services.runtime import PlanningRuntimeService
        await PlanningRuntimeService.initialize()
        logger.info("✅ PlanningRuntimeService initialized successfully")
    except Exception as e:
        logger.error(f"❌ PlanningRuntimeService initialization failed: {e}", exc_info=True)

    # Save event loop for cross-thread SSE publishing
    from app.services.sse import sse_manager
    sse_manager.save_event_loop(asyncio.get_running_loop())
    logger.info("🧹 SSE event loop saved")

    logger.info("✅ 后端服务启动完成")
    yield

    # Clean up resources
    logger.info("🧹 Cleaning up resources...")
    try:
        from app.database import dispose_async_engine
        await dispose_async_engine()
        logger.info("✅ Database engine disposed")
    except Exception as e:
        logger.error(f"❌ Failed to dispose database engine: {e}", exc_info=True)

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if IS_PRODUCTION else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

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
        "status": "healthy",
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