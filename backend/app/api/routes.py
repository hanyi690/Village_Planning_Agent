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
import random

import httpx
from fastapi import APIRouter
from fastapi.responses import Response

from app.api.session_routes import router as session_router
from app.api.gis_test_routes import router as gis_test_router
from app.api.human_review_routes import router as human_review_router
from app.api.artifact_routes import router as artifact_router
from app.api.render_routes import router as render_router
from app.core.settings import TIANDITU_API_KEY

logger = logging.getLogger(__name__)

# Main router
router = APIRouter()

# Core session API (新架构)
router.include_router(session_router, tags=["Session"])

# GIS dev test API (开发环境专用)
router.include_router(gis_test_router, tags=["GIS Dev"])

# Post-L3 HITL (人工审查 interrupt + resume)
router.include_router(human_review_router, tags=["Human Review"])

# Artifact query API (只读)
router.include_router(artifact_router, tags=["Artifacts"])

# Render layer API (PlannedState -> GeoJSON)
router.include_router(render_router, tags=["Render"])


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


# ============================================
# Tianditu Tile Proxy
# ============================================

_VALID_TILE_LAYERS = {"vec", "img", "ter", "cva", "cia", "cta"}


@router.get(
    "/api/tiles/tianditu/{layer_proj}/{z}/{y}/{x}",
    tags=["Tiles"],
    summary="Proxy Tianditu map tiles",
)
async def proxy_tianditu_tile(layer_proj: str, z: int, y: int, x: int):
    """代理天地图瓦片请求，避免前端跨域和 API Key 暴露。

    URL 格式: /api/tiles/tianditu/{layer}_{projection}/{z}/{y}/{x}
    例如: /api/tiles/tianditu/vec_w/14/5312/13532.png
    """
    # Parse layer_proj (e.g. "vec_w", "cva_w")
    parts = layer_proj.rsplit("_", 1)
    if len(parts) != 2 or parts[0] not in _VALID_TILE_LAYERS:
        return Response(status_code=400, content=f"Invalid layer: {layer_proj}")

    layer, projection = parts
    server = random.randint(0, 7)
    tk = TIANDITU_API_KEY

    if not tk:
        return Response(status_code=503, content="Tianditu API key not configured")

    url = (
        f"http://t{server}.tianditu.gov.cn/{layer}_{projection}/wmts"
        f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={layer}&STYLE=default&TILEMATRIXSET={projection}"
        f"&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
        f"&tk={tk}"
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "VillagePlanningAgent/1.0"})
            if resp.status_code == 200:
                return Response(
                    content=resp.content,
                    media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"},
                )
            return Response(status_code=resp.status_code, content=resp.content)
    except httpx.RequestError as exc:
        logger.warning(f"Tile proxy error: {exc}")
        return Response(status_code=502, content="Tile fetch failed")


__all__ = ["router"]