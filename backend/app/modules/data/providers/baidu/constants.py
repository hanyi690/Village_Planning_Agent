"""百度地图 API 常量定义"""
from typing import Dict

BASE_URL = "https://api.map.baidu.com"

# API Endpoints
SEARCH_V2_URL = f"{BASE_URL}/place/v2/search"
REGION_V3_URL = f"{BASE_URL}/place/v3/region"
SUGGESTION_URL = f"{BASE_URL}/place/v2/suggestion"
EVENTSEARCH_URL = f"{BASE_URL}/place/v2/eventsearch"
DETAIL_URL = f"{BASE_URL}/place/v2/detail"
GEOCODING_URL = f"{BASE_URL}/geocoding/v3/"

# coord_type: 1=wgs84, 2=gcj02, 3=bd09ll (默认), 4=bd09mc
COORD_TYPE_WGS84 = 1
COORD_TYPE_GCJ02 = 2
COORD_TYPE_BD09LL = 3

# 默认每页数量 (百度最大 20)
DEFAULT_PAGE_SIZE = 20

# 输出格式
OUTPUT_JSON = "json"

# 百度 POI 分类 tag (用于精确筛选)
# 参考 https://lbsyun.baidu.com/faq/api?title=webapi/guide/webservice-placeapiV3/interfaceDocumentV3
TAGS_FACILITY: Dict[str, str] = {
    "教育培训": "education",
    "中小学": "school",
    "幼儿园": "kindergarten",
    "医院": "hospital",
    "诊所": "clinic",
    "药店": "pharmacy",
    "政府机构": "government",
    "村委会": "village_committee",
    "公交站": "bus_station",
    "停车场": "parking",
}

# 百度自然村/聚落相关 tag (实测后填入)
# 百度没有官方"村庄"标签，可能用以下通用标签
TAGS_GEOGRAPHY: Dict[str, str] = {
    "地名": "geography",
    "村庄": "village",
    "自然村": "natural_village",
    "行政区划": "admin_area",
    "道路": "road",
    "河流": "river",
    "水库": "reservoir",
}


__all__ = [
    "BASE_URL",
    "SEARCH_V2_URL",
    "REGION_V3_URL",
    "SUGGESTION_URL",
    "EVENTSEARCH_URL",
    "DETAIL_URL",
    "GEOCODING_URL",
    "COORD_TYPE_WGS84",
    "COORD_TYPE_GCJ02",
    "COORD_TYPE_BD09LL",
    "DEFAULT_PAGE_SIZE",
    "OUTPUT_JSON",
    "TAGS_FACILITY",
    "TAGS_GEOGRAPHY",
]