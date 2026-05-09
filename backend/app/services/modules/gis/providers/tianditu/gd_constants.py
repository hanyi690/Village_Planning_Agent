"""广东省天地图专题服务配置

定义广东省天地图专题服务的服务ID、坐标系、协议类型等信息。
用于村庄规划约束验证，自动获取现状数据（三区三线、生态保护红线、
基本农田、地质灾害隐患点等）。

服务地址可通过环境变量 GD_TIANDITU_BASE_URL 配置。
"""
import os
from typing import Dict

# 广东省天地图专题服务基础URL（可通过环境变量配置）
# 每个服务有独立的路径: /server/{service_id}/wmts, /server/{service_id}/wms
GD_TIANDITU_BASE_URL = os.getenv(
    "GD_TIANDITU_BASE_URL",
    "https://guangdong.tianditu.gov.cn"
)

# 注意: 移除了静态端点 GD_WMTS_URL/GD_WMS_URL/GD_WFS_URL
# 服务URL现在需要动态构建: {base_url}/server/{service_id}/{protocol}

# 服务ID到图层类型的映射
GD_SERVICE_LAYER_MAP: Dict[str, str] = {
    # Layer 2 约束数据层
    "SQSXWPSJ": "three_zones_three_lines",
    "GDSTBHHX": "ecological_protection",
    "gdsyjjbntbhtb_mercator": "farmland_protection",
    "DZZHD": "geological_hazard_points",
    "dzzhyhd_mercator": "geological_hazard_points_mercator",

    # Layer 1 分析数据层
    "SWDTZ_50W": "hydrogeology",

    # Layer 0 底图服务
    "dom2023": "satellite_imagery",
}

# 图层类型到服务ID的反向映射
GD_LAYER_SERVICE_MAP: Dict[str, str] = {
    "three_zones_three_lines": "SQSXWPSJ",
    "ecological_protection": "GDSTBHHX",
    "farmland_protection": "gdsyjjbntbhtb_mercator",
    "geological_hazard_points": "DZZHD",
    "geological_hazard_points_mercator": "dzzhyhd_mercator",
    "hydrogeology": "SWDTZ_50W",
    "satellite_imagery": "dom2023",
}

# 服务详细信息配置
GD_SPECIALIZED_SERVICES: Dict[str, Dict] = {
    # 三区三线专题图
    "SQSXWPSJ": {
        "name": "三区三线专题图",
        "description": "永久基本农田、生态保护红线、城镇开发边界",
        "crs": "CGCS2000",
        "epsg": "EPSG:4490",  # CGCS2000地理坐标，兼容WGS84
        "protocols": ["WMS", "WMTS"],
        "layer_type": "three_zones_three_lines",
        "layer_group": "constraint",
        "wms_layer": "SQSX",  # WMS实际图层名
    },

    # 生态保护红线
    "GDSTBHHX": {
        "name": "生态保护红线",
        "description": "广东省生态保护红线区域",
        "crs": "CGCS2000",
        "epsg": "EPSG:4490",  # CGCS2000地理坐标
        "protocols": ["WMS", "WMTS"],
        "layer_type": "ecological_protection",
        "layer_group": "constraint",
        "wms_layer": "GDSTBHHX",
    },

    # 基本农田保护图斑（墨卡托投影）
    "gdsyjjbntbhtb_mercator": {
        "name": "基本农田保护图斑",
        "description": "永久基本农田保护图斑数据",
        "crs": "Web墨卡托",
        "epsg": "EPSG:3857",
        "protocols": ["WMS", "WMTS"],
        "layer_type": "farmland_protection",
        "layer_group": "constraint",
        "wms_layer": "基本农田保护图斑_mercator",
    },

    # 地质灾害隐患点（CGCS2000）
    "DZZHD": {
        "name": "地质灾害隐患点",
        "description": "广东省地质灾害隐患点分布",
        "crs": "CGCS2000",
        "epsg": "EPSG:4490",  # CGCS2000地理坐标
        "protocols": ["WMS", "WMTS"],
        "layer_type": "geological_hazard_points",
        "layer_group": "analysis",
        "wms_layer": "DZZHD",
    },

    # 地质灾害隐患点（墨卡托）
    "dzzhyhd_mercator": {
        "name": "地质灾害隐患点(墨卡托)",
        "description": "广东省地质灾害隐患点分布",
        "crs": "Web墨卡托",
        "epsg": "EPSG:3857",
        "protocols": ["WMS", "WMTS"],
        "layer_type": "geological_hazard_points_mercator",
        "layer_group": "analysis",
        "wms_layer": "dzzhyhd_mercator",
    },

    # 50万水文地质图
    "SWDTZ_50W": {
        "name": "50万水文地质图",
        "description": "广东省水文地质图（1:50万）",
        "crs": "CGCS2000",
        "epsg": "EPSG:4490",
        "protocols": ["WFS", "WMS", "WMTS"],
        "layer_type": "hydrogeology",
        "layer_group": "analysis",
        "wms_layer": "SWDTZ_50W",
    },

    # 2023年影像电子地图
    "dom2023": {
        "name": "2023年影像电子地图",
        "description": "广东省2023年卫星影像底图",
        "crs": "CGCS2000",
        "epsg": "EPSG:4490",
        "protocols": ["WMS", "WMTS"],
        "layer_type": "satellite_imagery",
        "layer_group": "base",
        "wms_layer": "dom2023",
    },
}

# 坐标系转换配置
# EPSG:4490 (CGCS2000地理坐标) 与 WGS84 在精度要求不高时可视为兼容
# Web墨卡托(EPSG:3857)需要转换到WGS84(EPSG:4326)
CRS_TRANSFORM_MAP: Dict[str, str] = {
    "EPSG:4490": "EPSG:4326",  # CGCS2000地理 -> WGS84 (兼容)
    "EPSG:3857": "EPSG:4326",  # Web墨卡托 -> WGS84
    "EPSG:4326": "EPSG:4326",  # WGS84无需转换
}

# Layer 2 约束类型（用于约束验证）
GD_LAYER_2_TYPES = [
    "three_zones_three_lines",
    "ecological_protection",
    "farmland_protection",
    "geological_hazard_points",
]

# 服务请求参数模板
GD_WMTS_PARAMS = {
    "SERVICE": "WMTS",
    "VERSION": "1.0.0",
    "REQUEST": "GetTile",
    "FORMAT": "image/png",
    "STYLE": "default",
}

GD_WMS_PARAMS = {
    "SERVICE": "WMS",
    "VERSION": "1.1.1",
    "REQUEST": "GetMap",
    "FORMAT": "image/png",
    "STYLE": "default",
}

__all__ = [
    "GD_TIANDITU_BASE_URL",
    "GD_SERVICE_LAYER_MAP",
    "GD_LAYER_SERVICE_MAP",
    "GD_SPECIALIZED_SERVICES",
    "CRS_TRANSFORM_MAP",
    "GD_LAYER_2_TYPES",
    "GD_WMTS_PARAMS",
    "GD_WMS_PARAMS",
]