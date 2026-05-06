"""天地图和高德地图地理编码服务"""
# 天地图模块
from .tianditu import (
    TiandituProvider,
    TiandituResult,
    TileService,
    WfsService,
    WFS_LAYERS,
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

# 高德地图模块
from .amap import (
    AmapProvider,
    TrafficService,
    AmapResult,
    POI_TYPES_PUBLIC_SERVICE,
    SERVICE_RADIUS_STANDARDS_AMAP,
    TRAFFIC_STATUS_LEVELS,
)

# POI 统一接口（高德优先）
from .poi_provider import POIProvider

# OpenStreetMap 模块（补充村级道路数据）
from .osm import (
    OSMProvider,
    OSMResult,
    OSMRoadFeature,
    OVERPASS_ENDPOINT,
    NETWORK_TYPES,
    HIGHWAY_CLASSES,
    VILLAGE_RELEVANT_HIGHWAYS,
)


__all__ = [
    # 天地图
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
    # 高德地图
    "AmapProvider",
    "TrafficService",
    "AmapResult",
    "POI_TYPES_PUBLIC_SERVICE",
    "SERVICE_RADIUS_STANDARDS_AMAP",
    "TRAFFIC_STATUS_LEVELS",
    # POI 统一接口
    "POIProvider",
    # OpenStreetMap
    "OSMProvider",
    "OSMResult",
    "OSMRoadFeature",
    "OVERPASS_ENDPOINT",
    "NETWORK_TYPES",
    "HIGHWAY_CLASSES",
    "VILLAGE_RELEVANT_HIGHWAYS",
]