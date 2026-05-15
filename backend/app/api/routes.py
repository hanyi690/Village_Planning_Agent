"""
Unified API Routes - All endpoints in one place

This module consolidates all API routes from:
- session_routes.py (核心会话 API - 7 个端点)

架构变更（2026-05-08）：
- 旧版：planning_router 包含分散的多个子路由
- 新版：session_router 统一 7 个核心端点 + 辅助端点

移除端点（2026-05-09）：
- data, jintian_data: 旧版遗留，数据通过规划流程内部获取
- files, gis_upload: 整合到 POST /api/sessions multipart/form-data
- knowledge: 运维操作，移至命令行脚本
- tiles: 前端直接向地图服务商请求
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.session_routes import router as session_router

logger = logging.getLogger(__name__)

# Main router
router = APIRouter()

# Core session API (新架构)
router.include_router(session_router, tags=["Session"])


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
        "modules": ["session"],
        "architecture": "SSE-single-channel"
    }


__all__ = ["router"]