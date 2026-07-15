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
from .gd_constants import (
    GD_TIANDITU_BASE_URL,
    GD_SPECIALIZED_SERVICES,
    GD_LAYER_SERVICE_MAP,
    GD_SERVICE_LAYER_MAP,
    GD_LAYER_2_TYPES,
)
from .gd_service import GDSpecializedService, GD_TIANDITU_TOKEN


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
    # 广东省天地图专题服务
    "GDSpecializedService",
    "GD_TIANDITU_TOKEN",
    "GD_TIANDITU_BASE_URL",
    "GD_SPECIALIZED_SERVICES",
    "GD_LAYER_SERVICE_MAP",
    "GD_SERVICE_LAYER_MAP",
    "GD_LAYER_2_TYPES",
]