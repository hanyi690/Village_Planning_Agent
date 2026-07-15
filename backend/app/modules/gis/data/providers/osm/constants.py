"""OSM 常量定义"""

# Overpass API 端点（免费，无需 Key）
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"

# 网络类型定义
NETWORK_TYPES = {
    "all": "所有道路（含步行、自行车道）",
    "drive": "机动车道路",
    "bike": "自行车道",
    "walk": "步行道路",
}

# OSM highway 类型分类
HIGHWAY_CLASSES = {
    # 主要道路
    "motorway": "高速公路",
    "motorway_link": "高速连接线",
    "trunk": "主干道",
    "trunk_link": "主干道连接线",
    "primary": "一级公路（国道级）",
    "primary_link": "一级公路连接线",
    "secondary": "二级公路（省道级）",
    "secondary_link": "二级公路连接线",
    "tertiary": "三级公路（县道级）",
    "tertiary_link": "三级公路连接线",

    # 村级相关道路（重点补充）
    "residential": "居民区道路（村内道路）",
    "unclassified": "未分类道路（村道）",
    "track": "农/林道路（田野道路）",
    "service": "服务道路",
    "living_street": "生活街道",

    # 特殊道路
    "pedestrian": "步行街",
    "path": "小路",
    "footway": "人行道",
    "cycleway": "自行车道",
    "bridleway": "马道",
    "steps": "台阶",
}

# 村级道路相关类型（天地图 WFS 缺失，需要 OSM 补充）
VILLAGE_RELEVANT_HIGHWAYS = [
    "residential",   # 村内道路
    "unclassified",  # 村道
    "track",         # 田野道路
    "tertiary",      # 三级公路（可能有部分乡道）
    "service",       # 服务道路
    "living_street", # 生活街道
]