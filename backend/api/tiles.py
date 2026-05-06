"""
Tiles API - Tile Proxy Endpoints

代理瓦片请求到天地图等地图服务，提供本地缓存。

端点:
- GET /api/tiles/{provider}/{layer}/{z}/{y}/{x} - 获取瓦片

支持的提供者:
- tianditu: 天地图瓦片服务
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import Response

from src.utils.paths import get_project_root

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================
# Configuration
# ============================================

TILE_CACHE_DIR = get_project_root() / "tile_cache"

# Module-level shared HTTP client (connection pool reuse)
_http_client: Optional[httpx.AsyncClient] = None

# Module-level shared TileService instance
_tile_service: Optional["TileService"] = None


# ============================================
# Helper Functions
# ============================================

def _get_http_client() -> httpx.AsyncClient:
    """Get or create shared HTTP client with connection pool."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=httpx.Timeout(10.0)
        )
    return _http_client


def _get_tile_service() -> "TileService":
    """Get or create shared TileService instance."""
    global _tile_service
    if _tile_service is None:
        from src.tools.geocoding.tianditu.tiles import TileService
        _tile_service = TileService()
    return _tile_service


def _get_tile_cache_path(provider: str, layer: str, z: int, x: int, y: int) -> Path:
    """Get tile cache path"""
    return TILE_CACHE_DIR / provider / layer / str(z) / str(y) / f"{x}.png"


async def _fetch_tile_from_tianditu(layer: str, projection: str, z: int, x: int, y: int) -> Optional[bytes]:
    """Fetch tile from Tianditu using shared client and service."""
    tile_service = _get_tile_service()

    # Distinguish annotation layers (cva/cia/cta) from base layers (vec/img/ter)
    if layer in ("cva", "cia", "cta"):
        url = tile_service.get_annotation_url(layer, projection, x, y, z, server=0)
    else:
        url = tile_service.get_tile_url(layer, projection, x, y, z, server=0)

    client = _get_http_client()
    resp = await client.get(url)
    if resp.status_code == 200:
        return resp.content
    return None


# ============================================
# Tile API Endpoints
# ============================================

@router.get("/{provider}/{layer}/{z}/{y}/{x}")
async def get_tile(provider: str, layer: str, z: int, y: int, x: int):
    """Proxy tile requests

    - provider: tianditu
    - layer: vec_c, img_c, cva_c etc (layer_projection format)
    - z: zoom level (1-18)
    - y: row number
    - x: column number
    """
    try:
        # Only support tianditu provider
        if provider != "tianditu":
            return Response(status_code=400, content="Only tianditu provider supported")

        # Check cache
        cache_path = _get_tile_cache_path(provider, layer, z, x, y)
        if cache_path.exists():
            return Response(
                content=cache_path.read_bytes(),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"}
            )

        # Parse layer format: vec_c = layer=vec, projection=c
        parts = layer.split("_")
        tile_layer = parts[0] if len(parts) > 0 else "vec"
        projection = parts[1] if len(parts) > 1 else "c"

        # Fetch from Tianditu
        tile_data = await _fetch_tile_from_tianditu(tile_layer, projection, z, x, y)

        if tile_data:
            # Save to cache
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(tile_data)

            return Response(
                content=tile_data,
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=86400"}
            )

        return Response(status_code=404, content="Tile not found")

    except Exception as e:
        logger.error(f"[Tile API] Error: {e}")
        return Response(status_code=500, content=str(e))


__all__ = ["router"]