"""天地图 API 模块"""
from .provider import TiandituProvider
from .tiles import TileService
from .wfs import WfsService, WFS_LAYERS
from .types import TiandituResult
from .constants import (
    BASE_URL,
    SEARCH_URL,
    GEOCODER_URL,
    ADMIN_API,
    ROUTE_URL,
    WFS_URL,
    TILE_LAYERS,
    ANNOTATION_LAYERS,
    PROJECTIONS,
    TILE_SERVICES,
    TILE_CONFIG,
)


__all__ = [
    "TiandituProvider",
    "TiandituResult",
    "TileService",
    "WfsService",
    "WFS_LAYERS",
    "BASE_URL",
    "SEARCH_URL",
    "GEOCODER_URL",
    "ADMIN_API",
    "ROUTE_URL",
    "WFS_URL",
    "TILE_LAYERS",
    "ANNOTATION_LAYERS",
    "PROJECTIONS",
    "TILE_SERVICES",
    "TILE_CONFIG",
]