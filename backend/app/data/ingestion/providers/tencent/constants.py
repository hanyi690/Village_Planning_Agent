"""腾讯地图 API 常量定义"""
from typing import Dict

BASE_URL = "https://apis.map.qq.com"

# API Endpoints - 注意: 路径是 /ws/place/v1/search (无空格)
SEARCH_URL = "https://apis.map.qq.com/ws/place/v1/search"
SUGGESTION_URL = "https://apis.map.qq.com/ws/place/v1/suggestion"
GEOCODER_URL = "https://apis.map.qq.com/ws/geocoder/v1"

# 坐标系
COORD_TYPE_GCJ02 = "gcj02"   # 腾讯默认 (火星坐标系)
COORD_TYPE_WGS84 = "wgs84"   # 国际标准

# 默认每页大小 (腾讯上限 20)
DEFAULT_PAGE_SIZE = 20

# POI 类型 (腾讯分类关键词, 用于 filter 参数)
# 参考: https://lbs.qq.com/webservice_v1/guide-appendix.html
FILTER_CATEGORIES: Dict[str, str] = {
    "school": "中学,小学",
    "hospital": "医院",
    "bus_station": "公交车站",
    "village_committee": "村委会",
    "town": "乡镇",
    "scenic": "风景名胜",
    "food": "美食",
    "shopping": "购物",
    "life_service": "生活服务",
}


__all__ = [
    "BASE_URL",
    "SEARCH_URL",
    "SUGGESTION_URL",
    "GEOCODER_URL",
    "COORD_TYPE_GCJ02",
    "COORD_TYPE_WGS84",
    "DEFAULT_PAGE_SIZE",
    "FILTER_CATEGORIES",
]