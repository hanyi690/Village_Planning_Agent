"""天地图 API 常量定义"""
from typing import Dict

# API endpoints
BASE_URL = "https://api.tianditu.gov.cn"
SEARCH_URL = f"{BASE_URL}/v2/search"
GEOCODER_URL = f"{BASE_URL}/geocoder"
ADMIN_API = f"{BASE_URL}/v2/administrative"
ROUTE_URL = f"{BASE_URL}/drive"

# WFS endpoints
WFS_URL = "http://gisserver.tianditu.gov.cn/TDTService/wfs"

# 瓦片图层类型定义
TILE_LAYERS: Dict[str, str] = {
    "vec": "矢量底图",
    "img": "影像底图",
    "ter": "地形晕渲"
}

# 注记图层类型定义
ANNOTATION_LAYERS: Dict[str, str] = {
    "cva": "矢量注记",
    "cia": "影像注记",
    "cta": "地形注记"
}

# 投影类型定义
PROJECTIONS: Dict[str, str] = {
    "c": "经纬度投影 (EPSG:4326)",
    "w": "球面墨卡托投影 (EPSG:3857)"
}

# WFS 图层类型
WFS_LAYERS: Dict[str, str] = {
    "LRRL": "铁路",
    "LRDL": "公路",
    "HYDA": "水系面",
    "HYDL": "水系线",
    "HYDP": "水系点",
    "RESA": "居民地面",
    "RESP": "居民地点"
}

# 新增瓦片服务
TILE_SERVICES: Dict[str, str] = {
    "ibo_c": "全球境界(经纬度)",
    "ibo_w": "全球境界(墨卡托)",
    "3d地名": "GetTiles",
    "3d地形": "swdx"
}

# 瓦片服务配置
TILE_CONFIG = {
    "zoom_range": {"min": 1, "max": 18},
    "server_range": {"min": 0, "max": 7}
}


__all__ = [
    "BASE_URL",
    "SEARCH_URL",
    "GEOCODER_URL",
    "ADMIN_API",
    "ROUTE_URL",
    "WFS_URL",
    "TILE_LAYERS",
    "ANNOTATION_LAYERS",
    "PROJECTIONS",
    "WFS_LAYERS",
    "TILE_SERVICES",
    "TILE_CONFIG"
]