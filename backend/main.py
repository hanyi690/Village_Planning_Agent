"""
FastAPI Backend Application - 村庄规划智能体后端服务
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add parent directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.api import sessions, files
from backend.api.data import router as data_router
from backend.api.planning import router as planning_router
from backend.api.validate_config import validate_config
from src.utils.paths import ensure_working_directory, get_project_root, get_results_dir

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ============================================
# Application Lifecycle
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    ensure_working_directory()
    project_root = get_project_root()

    logger.info(f"🚀 村庄规划智能体后端启动中...")
    logger.info(f"📁 Project root: {project_root}")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    logger.info(f"📁 Results directory: {get_results_dir()}")

    config_check = validate_config()
    if not config_check["valid"]:
        logger.error(f"❌ 配置验证失败: {config_check['errors']}")
    for warning in config_check["warnings"]:
        logger.warning(f"⚠️  {warning}")

    logger.info("🗄️  Initializing database...")
    from backend.database import init_db
    if init_db():
        logger.info("✅ Database initialized successfully")
    else:
        logger.error("❌ Database initialization failed")

    # 启动会话清理后台任务
    from backend.api.planning import start_session_cleanup, stop_session_cleanup
    await start_session_cleanup()
    logger.info("🧹 Session cleanup task started")

    logger.info("✅ 后端服务启动完成")
    yield

    # 关闭时停止清理任务
    await stop_session_cleanup()
    logger.info("🧹 Session cleanup task stopped")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(planning_router, tags=["Planning - Planning Execution"])
app.include_router(data_router, tags=["Data - Data Access"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions - UI Session Management"])
app.include_router(files.router, prefix="/api/files", tags=["Files - File Upload"])


# ============================================
# Health Check & Root Endpoints
# ============================================

@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """健康检查端点"""
    return {
        "status": "healthy",
        "service": "village-planning-backend",
        "version": "1.0.0"
    }


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """根路径"""
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
    """全局异常处理"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": str(exc)
        }
    )


# ============================================
# Run Server (for development)
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
