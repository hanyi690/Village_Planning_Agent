"""Root transport router for the versioned frontend API."""

from __future__ import annotations

import logging
import random

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.api.v1 import router as v1_router
from app.core.settings import TIANDITU_API_KEY

logger = logging.getLogger(__name__)

# Main router
router = APIRouter()

# Stable frontend-facing API.
router.include_router(v1_router)


# ============================================
# Health Check
# ============================================

@router.get("/api/health", tags=["Health"])
async def unified_health_check(request: Request):
    """Readiness check for core resources initialized by lifespan."""
    readiness = getattr(request.app.state, "readiness", None)
    if not readiness or not all(value == "ready" for value in readiness.values()):
        return JSONResponse(status_code=503, content={"status": "not_ready", "components": readiness or {}})
    return {
        "status": "ready",
        "service": "village-planning-backend",
        "components": readiness,
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
