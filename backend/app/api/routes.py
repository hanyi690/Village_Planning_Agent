"""
Unified API Routes - All endpoints in one place

This module consolidates all API routes from:
- session_routes.py (核心会话 API - 7 个端点)
- data.py (数据访问)
- files.py (文件上传)
- knowledge.py (知识库)
- tiles.py (瓦片代理)

架构变更（2026-05-08）：
- 旧版：planning_router 包含分散的多个子路由
- 新版：session_router 统一 7 个核心端点 + 辅助端点
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.session_routes import router as session_router
from app.api.data import router as data_router
from app.api import files, knowledge, gis_upload, tiles, jintian_data

logger = logging.getLogger(__name__)

# Main router
router = APIRouter()

# Core session API (新架构)
router.include_router(session_router, tags=["Session"])

# Data access
router.include_router(data_router, tags=["Data"])

# File operations
router.include_router(files.router, prefix="/api/files", tags=["Files"])
router.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge"])
router.include_router(gis_upload.router, prefix="/api/gis", tags=["GIS"])
router.include_router(tiles.router, prefix="/api/tiles", tags=["Tiles"])
router.include_router(jintian_data.router, prefix="/api/jintian", tags=["Jintian Data"])

# GIS Test endpoints (development only)
try:
    from app.api import gis_test
    router.include_router(gis_test.router, prefix="/api/dev/gis", tags=["GIS Test"])
    logger.info("[Routes] GIS Test endpoints enabled")
except ImportError as e:
    logger.warning(f"[Routes] GIS Test module not available: {e}")


# ============================================
# Health Check
# ============================================

@router.get("/api/health", tags=["Health"])
async def unified_health_check():
    """Unified health check endpoint"""
    return {
        "status": "healthy",
        "service": "village-planning-backend",
        "version": "2.0.0",
        "modules": ["session", "data", "files", "knowledge"],
        "architecture": "SSE-single-channel"
    }


__all__ = ["router"]