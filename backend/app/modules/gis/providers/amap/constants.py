"""高德地图 API 常量定义"""
from typing import Dict

# API Base URL
BASE_URL = "https://restapi.amap.com/v3"

# API Endpoints
POI_TEXT_URL = f"{BASE_URL}/place/text"
POI_AROUND_URL = f"{BASE_URL}/place/around"
DRIVING_URL = f"{BASE_URL}/direction/driving"
WALKING_URL = f"{BASE_URL}/direction/walking"
TRAFFIC_RECT_URL = f"{BASE_URL}/traffic/status/rectangle"
TRAFFIC_CIRCLE_URL = f"{BASE_URL}/traffic/status/circle"
TRAFFIC_ROAD_URL = f"{BASE_URL}/traffic/status/road"
GEOCODE_URL = f"{BASE_URL}/geocode/geo"
REGEOCODE_URL = f"{BASE_URL}/geocode/regeo"
DISTRICT_URL = f"{BASE_URL}/config/district"

# POI 类型码 - 公共服务设施
POI_TYPES_PUBLIC_SERVICE: Dict[str, str] = {
    # 医疗服务
    "医院": "090100",
    "综合医院": "090101",
    "专科医院": "090102",
    "诊所": "090200",
    "药店": "090300",
    # 教育服务
    "学校": "141000",
    "幼儿园": "141100",
    "小学": "141200",
    "中学": "141300",
    "高等院校": "141400",
    # 商业服务
    "超市": "060100",
    "便利店": "060200",
    "商场": "060400",
    "农贸市场": "060500",
    # 金融服务
    "银行": "160100",
    "ATM": "160200",
    # 交通设施
    "公交站": "150700",
    "地铁站": "150500",
    "停车场": "150900",
    "加油站": "010100",
    # 政务服务
    "政府机构": "130100",
    "派出所": "130200",
    "社区服务中心": "130500",
    # 餐饮服务
    "餐厅": "050100",
    "快餐": "050200",
    # 休闲娱乐
    "公园": "110100",
    "广场": "110200",
    "体育场馆": "080100",
    "电影院": "060600",
}

# 公共服务设施服务半径标准（米）
SERVICE_RADIUS_STANDARDS_AMAP: Dict[str, int] = {
    "幼儿园": 300,
    "小学": 500,
    "中学": 1000,
    "医院": 1000,
    "诊所": 500,
    "超市": 500,
    "便利店": 300,
    "公交站": 300,
    "地铁站": 800,
    "银行": 500,
    "公园": 500,
}

# 交通态势等级
TRAFFIC_STATUS_LEVELS: Dict[int, str] = {
    1: "畅通",
    2: "缓行",
    3: "拥堵",
    4: "严重拥堵",
    5: "无数据",
}

# 搜索扩展字段
POI_EXTENSIONS = "all"

# 默认搜索参数
DEFAULT_POI_PAGE_SIZE = 20
DEFAULT_POI_OFFSET = 1

# 路径规划策略
DRIVING_STRATEGY: Dict[str, int] = {
    "最快": 0,      # 速度优先（时间）
    "最短": 1,      # 距离优先（距离）
    "避开高速": 2,  # 不走高速
    "避开拥堵": 3,  # 避开拥堵
    "多策略": 4,    # 多路径规划（返回多条路径）
}


__all__ = [
    "BASE_URL",
    "POI_TEXT_URL",
    "POI_AROUND_URL",
    "DRIVING_URL",
    "WALKING_URL",
    "TRAFFIC_RECT_URL",
    "TRAFFIC_CIRCLE_URL",
    "TRAFFIC_ROAD_URL",
    "GEOCODE_URL",
    "REGEOCODE_URL",
    "DISTRICT_URL",
    "POI_TYPES_PUBLIC_SERVICE",
    "SERVICE_RADIUS_STANDARDS_AMAP",
    "TRAFFIC_STATUS_LEVELS",
    "POI_EXTENSIONS",
    "DEFAULT_POI_PAGE_SIZE",
    "DEFAULT_POI_OFFSET",
    "DRIVING_STRATEGY",
]