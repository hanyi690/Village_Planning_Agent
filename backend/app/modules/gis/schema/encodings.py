"""DLBM/GHYTBM/GHFLBM encoding systems and lookup functions.

Three orthogonal encoding systems:
  1. DLBM/GHYTBM — 三调工作分类 (current/planned land use codes)
  2. YDYHFLDM — 用地用海分类代码 (自然资发〔2023〕234号)
  3. V/N/E — 住建部村庄规划用地分类 (frontend statistics)

Two orthogonal classification systems within zone types:
  1. Function zones (7 types) — DLBM_TO_ZONE_TYPE
  2. Planning zones (6 zones) — DLBM_TO_PLANNING_ZONE
     Mapping 7→6 is many-to-one. These two systems MUST NOT be mixed.
  3. Primary zones (3 zones) — DLBM_TO_PRIMARY_ZONE
     三区三线: 生态空间/农业空间/建设空间 (全域覆盖不重叠)
"""

from typing import Dict, List

# ── DLBM → DLMC → Zone type mappings ─────────────────────────

DLBM_TO_DLMC: Dict[str, str] = {
    "0100": "耕地", "0110": "水田", "0120": "旱地",
    "0200": "园地", "0300": "林地", "0400": "草地",
    "0500": "商服用地", "0600": "工矿用地",
    "0610": "工业用地", "0620": "采矿用地",
    "0700": "住宅用地", "0800": "公共管理与公共服务用地",
    "0900": "特殊用地", "1000": "交通运输用地",
    "1100": "耕地", "1200": "其他土地", "1400": "草地",
    "2100": "商服用地", "2121": "宅基地",
    "2123": "基础设施用地", "2124": "经营性建设用地",
    "3100": "水域",
}

# All DLBM mappings derived from the unified classification schema.
# Add/modify DLBM classifications in schema.py, not here.
from .classification import SCHEMA as _SCHEMA

DLBM_TO_ZONE_TYPE: Dict[str, str] = _SCHEMA.to_dlbm_zone_type()
ZONE_TYPE_TO_DLBMS: Dict[str, List[str]] = _SCHEMA.to_zone_type_dlbms()


def get_zone_type_for_dlbm(dlbm: str) -> str:
    """Get zone type for a DLBM code."""
    return DLBM_TO_ZONE_TYPE.get(dlbm, "农业用地")


def get_dlbms_for_zone_type(zone_type: str) -> List[str]:
    """Get all DLBM codes that map to a zone type."""
    return ZONE_TYPE_TO_DLBMS.get(zone_type, [])


def get_zone_type_for_planned_dlbm(dlbm: str) -> str:
    """Get zone type for a planned DLBM code (delegates to get_zone_type_for_dlbm)."""
    return get_zone_type_for_dlbm(dlbm)


# ── GHYTMC planning use names ─────────────────────────────────

GHYTMC_TO_ZONE_TYPE: Dict[str, str] = {
    "耕地": "农业用地", "水田": "农业用地", "旱地": "农业用地", "水浇地": "农业用地",
    "园地": "农业用地", "果园": "农业用地", "茶园": "农业用地",
    "设施农用地": "农业用地", "水利设施用地": "农业用地", "其他农用地": "农业用地",
    "商品林": "生态绿地", "生态林": "生态绿地",
    "乔木林地": "生态绿地", "其他林地": "生态绿地", "灌木林地": "生态绿地",
    "景观与绿化用地": "公共服务用地",
    "宅基地": "居住用地",
    "经营性建设用地": "产业用地",
    "公共服务设施用地": "公共服务用地",
    "基础设施用地": "交通用地",
    "村内交通用地": "交通用地", "对外交通用地": "交通用地",
    "农村道路": "交通用地",
    "水域": "水域", "河流水面": "水域", "坑塘水面": "水域",
    "商业服务业用地": "商业用地",
}

GHYTMC_TO_DLMC: Dict[str, str] = {
    "耕地": "耕地", "水田": "水田", "旱地": "旱地",
    "园地": "园地", "果园": "果园",
    "商品林": "商品林", "生态林": "生态林",
    "乔木林地": "乔木林地",
    "宅基地": "宅基地",
    "经营性建设用地": "经营性建设用地",
    "公共服务设施用地": "公共服务设施用地",
    "村内交通用地": "村内交通用地", "对外交通用地": "对外交通用地",
    "基础设施用地": "基础设施用地",
    "景观与绿化用地": "景观与绿化用地",
    "设施农用地": "设施农用地", "水利设施用地": "水利设施用地",
    "其他农用地": "其他农用地", "水域": "水域",
}


def get_zone_type_for_ghytmc(ghytmc: str) -> str:
    """Get zone type from GHYTMC planning use category name."""
    return GHYTMC_TO_ZONE_TYPE.get(str(ghytmc).strip(), "农业用地")


# ── DLBM → Primary zone mapping (三区三线 一级分区, from schema) ──
DLBM_TO_PRIMARY_ZONE: Dict[str, str] = _SCHEMA.to_dlbm_primary_zone()


def get_primary_zone(dlbm: str) -> str:
    """Map DLBM code to primary zone (三区: 生态空间/农业空间/建设空间)."""
    return DLBM_TO_PRIMARY_ZONE.get(str(dlbm).strip(), "农业空间")


# ── DLBM → Planning zone mapping (三区三线 二级6类分区, from schema) ──
DLBM_TO_PLANNING_ZONE: Dict[str, str] = _SCHEMA.to_dlbm_planning_zone()


def dlbm_to_planning_zone(dlbm: str) -> str:
    """Map DLBM code to planning zone."""
    return DLBM_TO_PLANNING_ZONE.get(str(dlbm).strip(), "一般农业区")


# ── Planning zone ↔ Primary zone mapping ──────────────────────

PRIMARY_ZONE_NAMES: List[str] = ["生态空间", "农业空间", "建设空间"]

PLANNING_ZONE_NAMES: List[str] = [
    "生态保护区", "生态控制区", "农田保护区",
    "一般农业区", "村庄建设区", "林业发展区",
]

PLANNING_ZONE_TO_PRIMARY_ZONE: Dict[str, str] = {
    "生态保护区": "生态空间",
    "生态控制区": "生态空间",
    "农田保护区": "农业空间",
    "一般农业区": "农业空间",
    "村庄建设区": "建设空间",
    "林业发展区": "农业空间",
}


def get_primary_zone_for_planning_zone(planning_zone: str) -> str:
    """Get the primary zone that a planning zone belongs to."""
    return PLANNING_ZONE_TO_PRIMARY_ZONE.get(planning_zone, "农业空间")


# ── GHFLBM / GHYTBM planning classification codes ─────────────

GHFLBM_MEANING: Dict[str, str] = {
    "1110": "耕地(规划)", "1120": "园地(规划)",
    "1130": "林地(规划)", "1200": "草地(规划)",
    "1310": "商品林(规划)", "1330": "生态林(规划)",
    "1520": "设施农用地(规划)", "1530": "其他农用地(规划)",
    "2120": "农村建设用地(规划)", "2270": "水利设施用地(规划)",
    "3110": "水域(规划)",
}

GHFLBM_TO_ZONE_TYPE: Dict[str, str] = {
    "1110": "农业用地", "1120": "农业用地",
    "1130": "生态绿地", "1200": "生态绿地",
    "1310": "生态绿地", "1330": "生态绿地",
    "1520": "农业用地", "1530": "农业用地",
    "2120": "居住用地", "2270": "农业用地",
    "3110": "水域",
}

GHFLBM_TO_GHYTBMS: Dict[str, List[str]] = {
    "1110": ["1100"], "1120": ["1200"],
    "1130": ["1340", "1350"], "1200": ["1400"],
    "1310": ["1340"], "1330": ["1350"],
    "1520": ["1510"], "1530": ["1500"],
    "2120": ["2121", "2122", "2123", "2124", "2125", "2126"],
    "2270": ["2270"], "3110": ["3100"],
}


def get_zone_type_for_ghflbm(ghflbm: str) -> str:
    """Get zone type from GHFLBM planning classification code."""
    return GHFLBM_TO_ZONE_TYPE.get(str(ghflbm).strip(), "农业用地")


GHYTBM_TO_GHYTMC: Dict[str, str] = {
    "1100": "耕地", "1200": "园地",
    "1340": "商品林", "1350": "生态林",
    "1400": "草地", "1500": "其他农用地", "1510": "设施农用地",
    "2121": "宅基地", "2122": "公共服务设施用地",
    "2123": "基础设施用地", "2124": "经营性建设用地",
    "2125": "景观与绿化用地", "2126": "村内交通用地",
    "2200": "对外交通用地", "2270": "水利设施用地",
    "3100": "水域", "3200": "自然保留地",
}

GHYTBM_TO_YDYHFLDM: Dict[str, str] = {
    "1100": "0100", "1200": "0200",
    "1340": "0301", "1350": "0301",
    "1400": "0400", "1500": "1500", "1510": "0602",
    "2121": "0702", "2122": "0800", "2123": "1300",
    "2124": "0900", "2125": "1401", "2126": "0601",
    "2200": "1200", "2270": "1311",
    "3100": "1700", "3200": "2300",
}

YDYHFLDM_TO_NAME: Dict[str, str] = {
    "0100": "耕地", "0101": "水田", "0102": "水浇地", "0103": "旱地",
    "0200": "园地", "0201": "果园", "0204": "油料园地", "0205": "其他园地",
    "0300": "林地", "0301": "乔木林地", "0302": "竹林地",
    "0303": "灌木林地", "0304": "其他林地",
    "0400": "草地", "0401": "天然牧草地", "0402": "人工牧草地", "0403": "其他草地",
    "0500": "湿地", "0501": "森林沼泽", "0502": "灌木沼泽",
    "0503": "沼泽草地", "0506": "内陆滩涂",
    "0600": "农业设施建设用地", "0601": "农村道路", "0602": "设施农用地",
    "0700": "居住用地", "0702": "农村宅基地", "0703": "农村宅基地",
    "0704": "农村社区服务设施用地",
    "0800": "公共管理与公共服务用地",
    "0801": "机关团体用地", "0802": "科研用地", "0803": "文化用地",
    "0804": "教育用地", "0805": "体育用地", "0806": "医疗卫生用地",
    "0807": "社会福利用地",
    "0900": "商业服务业用地", "0901": "商业用地",
    "0902": "商务金融用地", "0903": "娱乐用地",
    "1000": "工矿用地", "1001": "工业用地", "1002": "采矿用地",
    "1100": "仓储用地", "1101": "物流仓储用地",
    "1200": "交通运输用地", "1201": "铁路用地", "1202": "公路用地",
    "1207": "城镇村道路用地", "1208": "交通场站用地",
    "1300": "公用设施用地",
    "1301": "供水用地", "1302": "排水用地", "1303": "供电用地",
    "1306": "通信用地", "1309": "环卫用地", "1310": "消防用地",
    "1311": "水工设施用地",
    "1400": "绿地与开敞空间用地", "1401": "公园绿地", "1402": "防护绿地",
    "1403": "广场用地",
    "1500": "特殊用地", "1600": "留白用地",
    "1700": "陆地水域", "1701": "河流水面", "1702": "湖泊水面",
    "1703": "水库水面", "1704": "坑塘水面", "1705": "沟渠",
    "2300": "其他土地", "2301": "空闲地", "2302": "田坎",
    "2303": "田间道", "2304": "盐碱地", "2305": "沙地",
    "2306": "裸土地", "2307": "裸岩石砾地",
}

GHYTBM_TO_ZONE_TYPE: Dict[str, str] = {
    "1100": "农业用地", "1200": "农业用地",
    "1340": "生态绿地", "1350": "生态绿地",
    "1400": "生态绿地", "1500": "农业用地", "1510": "农业用地",
    "2121": "居住用地", "2122": "公共服务用地",
    "2123": "交通用地", "2124": "产业用地",
    "2125": "公共服务用地", "2126": "交通用地",
    "2200": "交通用地", "2270": "农业用地",
    "3100": "水域", "3200": "农业用地",
}


def get_zone_type_for_ghytbm(ghytbm: str) -> str:
    """Get zone type from GHYTBM planning use code."""
    return GHYTBM_TO_ZONE_TYPE.get(str(ghytbm).strip(), "农业用地")


def get_ghytmc_for_ghytbm(ghytbm: str) -> str:
    """Get GHYTMC (name) from GHYTBM (code)."""
    return GHYTBM_TO_GHYTMC.get(str(ghytbm).strip(), "")
