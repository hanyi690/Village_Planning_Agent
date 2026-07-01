"""
DLBM/DLMC/PLANNING_COLORS mapping and zone color definitions.

Synchronized with frontend: frontend/src/features/planning/constants/gis.ts
"""

from typing import Dict, List, Set, Tuple


# ============================================
# Zone type colors (synced with frontend PLANNING_COLORS.function_zone)
# GB/T 21010 + 市级国土空间规划制图规范配色
# ============================================

ZONE_TYPE_COLORS: Dict[str, Dict[str, str]] = {
    # 农业空间 - 黄色系 (耕地 RGB(245,248,220))
    "农业用地": {"fill": "#F5F8DC", "stroke": "#8B7355"},
    # 生态空间 - 绿色冷色系 (林地 RGB(104,177,103))
    "生态绿地": {"fill": "#68B167", "stroke": "#2E8B57"},
    # 城镇空间 - 红色暖色系 (宅基地 RGB(255,211,128))
    "居住用地": {"fill": "#FFD380", "stroke": "#B8860B"},
    # 商业用地 (RGB(255,0,0))
    "商业用地": {"fill": "#FF0000", "stroke": "#CC0000"},
    # 产业用地 (工业 RGB(187,150,116))
    "产业用地": {"fill": "#BB9674", "stroke": "#8B6914"},
    # 公共服务用地 - 蓝色系
    "公共服务用地": {"fill": "#4A90D9", "stroke": "#1E3A5F"},
    # 交通用地 (RGB(0,0,255))
    "交通用地": {"fill": "#0000FF", "stroke": "#0066CC"},
    # 水域
    "水域": {"fill": "#87CEEB", "stroke": "#4169E1"},
}

# Default color for unmapped zone types
DEFAULT_ZONE_COLOR: Dict[str, str] = {"fill": "#CCCCCC", "stroke": "#666666"}


# ============================================
# Facility status colors (synced with frontend PLANNING_COLORS.facility_point)
# ============================================

FACILITY_STATUS_COLORS: Dict[str, Dict[str, str]] = {
    "现状保留": {"fill": "green", "stroke": "#006400"},
    "规划新建": {"fill": "blue", "stroke": "#00008B"},
    "规划改扩建": {"fill": "orange", "stroke": "#CC8400"},
    "规划迁建": {"fill": "purple", "stroke": "#800080"},
}


# ============================================
# DLBM ↔ DLMC ↔ PLANNING_COLORS mapping
# ============================================

# DLBM (地类编码, GB/T 21010) → DLMC (地类名称) → PLANNING_COLORS key
# Multiple DLBM codes may map to the same zone type

DLBM_TO_DLMC: Dict[str, str] = {
    "0100": "耕地",
    "0110": "水田",
    "0120": "旱地",
    "0200": "园地",
    "0300": "林地",
    "0400": "草地",
    "0500": "商服用地",
    "0600": "工矿用地",
    "0610": "工业用地",
    "0620": "采矿用地",
    "0700": "住宅用地",
    "0800": "公共管理与公共服务用地",
    "0900": "特殊用地",
    "1000": "交通运输用地",
    "1100": "耕地",
    "1200": "其他土地",
    "1400": "草地",
    "2100": "商服用地",
    "2121": "宅基地",
    "3100": "水域",
}

# DLBM → PLANNING_COLORS zone type key
# Maps national land use codes (GB/T 21010-2017 + 三调工作分类) to rendering categories
# Organized by 一级类 with professional classification
DLBM_TO_ZONE_TYPE: Dict[str, str] = {
    # ── 01 耕地 → 农业用地 ──
    "0100": "农业用地",  # 耕地(大类)
    "0101": "农业用地",  # 水田
    "0102": "农业用地",  # 水浇地
    "0103": "农业用地",  # 旱地
    "0110": "农业用地",  # 水田(三调)
    "0120": "农业用地",  # 水浇地(三调)
    "0130": "农业用地",  # 旱地(三调)
    # ── 02 园地 → 农业用地 ──
    "0200": "农业用地",  # 园地(大类)
    "0201": "农业用地",  # 果园
    "0202": "农业用地",  # 茶园
    "0203": "农业用地",  # 橡胶园
    "0204": "农业用地",  # 其他园地
    "0210": "农业用地",  # 果园(三调)
    "0220": "农业用地",  # 茶园(三调)
    "1100": "农业用地",  # 果园(三调, 村庄规划专用编码)
    # ── 03 林地 → 生态绿地 ──
    "0300": "生态绿地",  # 林地(大类)
    "0301": "生态绿地",  # 乔木林地
    "0302": "生态绿地",  # 竹林地
    "0303": "生态绿地",  # 红树林地
    "0304": "生态绿地",  # 森林沼泽
    "0305": "生态绿地",  # 灌木林地
    "0306": "生态绿地",  # 灌丛沼泽
    "0307": "生态绿地",  # 其他林地
    "0310": "生态绿地",  # 乔木林地(三调)
    "0330": "生态绿地",  # 其他林地(三调)
    "1340": "生态绿地",  # 商品林(三调村庄规划专用)
    "1350": "生态绿地",  # 生态林(三调村庄规划专用)
    # ── 04 草地 → 生态绿地 ──
    "0400": "生态绿地",  # 草地(大类)
    "0401": "生态绿地",  # 天然牧草地
    "0402": "生态绿地",  # 沼泽草地
    "0403": "生态绿地",  # 人工牧草地
    "0404": "生态绿地",  # 其他草地
    "1400": "生态绿地",  # 草地(三调)
    # ── 05 商服用地 → 商业用地 ──
    "0500": "商业用地",
    # ── 06 工矿用地 → 产业用地 ──
    "0600": "产业用地",  # 工矿用地(大类)
    "0601": "产业用地",  # 工业用地
    "0602": "产业用地",  # 采矿用地
    "0603": "产业用地",  # 盐田
    "0610": "产业用地",  # 工业用地(三调)
    "0620": "产业用地",  # 采矿用地(三调)
    # ── 07 住宅用地 → 居住用地 ──
    "0700": "居住用地",  # 住宅用地(大类)
    "0701": "居住用地",  # 城镇住宅用地
    "0702": "居住用地",  # 农村宅基地
    # ── 08 公共管理 → 公共服务用地 ──
    "0800": "公共服务用地",  # 公共管理(大类)
    "0801": "公共服务用地",  # 书籍、展览用地
    "0802": "公共服务用地",  # 教育用地
    "0803": "公共服务用地",  # 医疗卫生用地
    "0806": "公共服务用地",  # 社会福利用地
    "0810": "公共服务用地",  # 公园与绿地
    "0900": "公共服务用地",  # 特殊用地(三调归入公共)
    # ── 10 交通运输 → 交通用地 ──
    "1000": "交通用地",  # 交通运输(大类)
    "1001": "交通用地",  # 铁路用地
    "1002": "交通用地",  # 轨道交通用地
    "1003": "交通用地",  # 公路用地
    "1004": "交通用地",  # 城镇道路用地
    "1005": "交通用地",  # 交通服务场站用地
    "1006": "交通用地",  # 农村道路
    "1040": "交通用地",  # 农村道路(三调)
    # ── 11 水域 → 水域 ──
    "1101": "水域",  # 河流水面
    "1102": "水域",  # 湖泊水面
    "1103": "水域",  # 水库水面
    "1104": "水域",  # 坑塘水面
    "1105": "水域",  # 沿海滩涂
    "1106": "水域",  # 内陆滩涂
    "1109": "水域",  # 水工建筑用地
    "1110": "水域",  # 河流水面(三调)
    "1140": "水域",  # 坑塘水面(三调)
    "1180": "水域",  # 水工建筑用地(三调, 水利设施归入水域)
    "3100": "水域",  # 水域(大类)
    # ── 12 其他土地 ──
    "1200": "农业用地",  # 其他土地(大类, 含田坎等农业附属)
    "1201": "农业用地",  # 空闲地
    # ── 三调21XX 村庄内部编码 ──
    "2030": "居住用地",  # 村庄(宅基地, 规划编码)
    "2100": "产业用地",  # 商服用地(三调)
    "2121": "居住用地",  # 宅基地
    "2122": "公共服务用地",  # 基础设施用地
    "2124": "产业用地",  # 经营性建设用地
    "2125": "公共服务用地",  # 景观与绿化用地
    "2126": "交通用地",  # 村内交通用地
    "2200": "交通用地",  # 对外交通用地
    "2270": "农业用地",  # 设施农用地/水利设施用地
    # ── 扩展编码 ──
    "1510": "农业用地",  # 设施农用地
    "3200": "农业用地",  # 自然保留地
}

# Zone type → list of DLBM codes (reverse mapping, synced with DLBM_TO_ZONE_TYPE)
ZONE_TYPE_TO_DLBMS: Dict[str, List[str]] = {
    "居住用地": ["0700", "0701", "0702", "2121", "2030"],
    "产业用地": ["0600", "0601", "0602", "0603", "0610", "0620", "2100", "2124"],
    "公共服务用地": ["0800", "0801", "0802", "0803", "0806", "0810", "0900", "2122", "2125"],
    "生态绿地": [
        "0300", "0301", "0302", "0303", "0304", "0305", "0306", "0307",
        "0310", "0330", "1340", "1350",
        "0400", "0401", "0402", "0403", "0404", "1400",
    ],
    "交通用地": ["1000", "1001", "1002", "1003", "1004", "1005", "1006", "1040", "2126", "2200"],
    "水域": ["1101", "1102", "1103", "1104", "1105", "1106", "1109", "1110", "1140", "1180", "3100"],
    "农业用地": [
        "0100", "0101", "0102", "0103", "0110", "0120", "0130",
        "0200", "0201", "0202", "0203", "0204", "0210", "0220", "1100",
        "1200", "1201", "1510", "2270", "3200",
    ],
    "商业用地": ["0500"],
}


def get_zone_color(zone_type: str) -> Dict[str, str]:
    """Get fill/stroke color for a zone type."""
    return ZONE_TYPE_COLORS.get(zone_type, DEFAULT_ZONE_COLOR)


def get_zone_type_for_dlbm(dlbm: str) -> str:
    """Get PLANNING_COLORS zone type key for a DLBM code."""
    return DLBM_TO_ZONE_TYPE.get(dlbm, "农业用地")


def get_dlbms_for_zone_type(zone_type: str) -> List[str]:
    """Get all DLBM codes that map to a zone type."""
    return ZONE_TYPE_TO_DLBMS.get(zone_type, [])


# ============================================
# 规划 DLBM 编码体系 (GB/T 21010 规划用途分类)
# 与现状 DLBM 不同: 0110/0130/0310/2030 等
# ============================================

# 规划 DLBM → Zone type
PLANNED_DLBM_TO_ZONE_TYPE: Dict[str, str] = {
    # 耕地 → 农业用地
    "0110": "农业用地",  # 水田
    "0120": "农业用地",  # 水浇地
    "0130": "农业用地",  # 旱地
    # 园地 → 农业用地
    "0210": "农业用地",  # 果园
    "0220": "农业用地",  # 茶园
    # 林地 → 生态绿地
    "0310": "生态绿地",  # 乔木林地
    "0330": "生态绿地",  # 其他林地
    # 草地 → 生态绿地
    "1040": "交通用地",  # 农村道路
    # 水域
    "1110": "水域",      # 河流水面
    "1140": "水域",      # 坑塘水面
    "1180": "水域",  # 水工建筑用地
    # 建设用地
    "2030": "居住用地",  # 村庄(宅基地)
    "3100": "水域",      # 水域
}

# 规划用途名称 (GHYTMC) → Zone type
# GHYTMC 是 landuse_planned 中 planning-specific 的分类字段
GHYTMC_TO_ZONE_TYPE: Dict[str, str] = {
    "耕地": "农业用地",
    "水田": "农业用地",
    "旱地": "农业用地",
    "水浇地": "农业用地",
    "园地": "农业用地",
    "果园": "农业用地",
    "茶园": "农业用地",
    "设施农用地": "农业用地",
    "水利设施用地": "农业用地",
    "其他农用地": "农业用地",
    "商品林": "生态绿地",
    "生态林": "生态绿地",
    "乔木林地": "生态绿地",
    "其他林地": "生态绿地",
    "灌木林地": "生态绿地",
    "景观与绿化用地": "生态绿地",
    "宅基地": "居住用地",
    "经营性建设用地": "产业用地",
    "公共服务设施用地": "公共服务用地",
    "基础设施用地": "交通用地",
    "村内交通用地": "交通用地",
    "对外交通用地": "交通用地",
    "农村道路": "交通用地",
    "水域": "水域",
    "河流水面": "水域",
    "坑塘水面": "水域",
    "商业服务业用地": "商业用地",
}

# GHYTMC → 国标名称 (for display)
GHYTMC_TO_DLMC: Dict[str, str] = {
    "耕地": "耕地",
    "水田": "水田",
    "旱地": "旱地",
    "园地": "园地",
    "果园": "果园",
    "商品林": "商品林",
    "生态林": "生态林",
    "乔木林地": "乔木林地",
    "宅基地": "宅基地",
    "经营性建设用地": "经营性建设用地",
    "公共服务设施用地": "公共服务设施用地",
    "村内交通用地": "村内交通用地",
    "对外交通用地": "对外交通用地",
    "基础设施用地": "基础设施用地",
    "景观与绿化用地": "景观与绿化用地",
    "设施农用地": "设施农用地",
    "水利设施用地": "水利设施用地",
    "其他农用地": "其他农用地",
    "水域": "水域",
}


def get_zone_type_for_planned_dlbm(dlbm: str) -> str:
    """Get zone type for a planned DLBM code (规划编码体系)."""
    return PLANNED_DLBM_TO_ZONE_TYPE.get(str(dlbm).strip(), "农业用地")


def get_zone_type_for_ghytmc(ghytmc: str) -> str:
    """Get zone type from GHYTMC planning use category name."""
    return GHYTMC_TO_ZONE_TYPE.get(str(ghytmc).strip(), "农业用地")


# ============================================
# 基本农田 / 一般农地区 DLBM 编码集
# 永久基本农田划定应基于 YJJBNTTB 图层，非 DLBM 映射
# 此集合仅作为无 YJJBNTTB 时的 fallback 分类
# ============================================

# 永久基本农田 DLBM（仅耕地 01 类：水田/水浇地/旱地）
BASIC_FARMLAND_CODES: Set[str] = {
    "0101", "0102", "0103",  # GB/T: 水田/水浇地/旱地
    "0110", "0120", "0130",  # 三调: 水田/水浇地/旱地
}

# 一般农地区 DLBM（园地 + 设施农用地 + 其他）
GENERAL_AGRICULTURE_CODES: Set[str] = {
    "0100",  # 耕地(大类)
    "0200", "0201", "0202", "0203", "0204",  # 园地
    "0210", "0220",  # 果园/茶园(三调)
    "1100",  # 果园(三调村庄规划专用编码)
    "1200", "1201",  # 其他土地
    "1510",  # 设施农用地
    "2270",  # 水利设施用地
    "3200",  # 自然保留地
}

# 受保护 DLBM — 不可分配到建设用地的编码
# = 基本农田 + 一般农地 + 生态绿地/水域 DLBM
ECOLOGICAL_CODES: Set[str] = set()
for _zt in ("生态绿地", "水域"):
    ECOLOGICAL_CODES.update(ZONE_TYPE_TO_DLBMS.get(_zt, []))

PROTECTED_DLBM_CODES: Set[str] = BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES | ECOLOGICAL_CODES

# 建设用地 zone types
CONSTRUCTION_ZONE_TYPES: Set[str] = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}


def is_basic_farmland(dlbm: str) -> bool:
    """Check if a DLBM code belongs to basic farmland (耕地类)."""
    return str(dlbm).strip() in BASIC_FARMLAND_CODES


def is_general_agriculture(dlbm: str) -> bool:
    """Check if a DLBM code belongs to general agriculture area."""
    return str(dlbm).strip() in GENERAL_AGRICULTURE_CODES


# ============================================
# Planning zone colors (4-zone 土地用途分区)
# Used by SpatialLayoutEngine._generate_planning_zones
# ============================================

PLANNING_ZONE_COLORS: Dict[str, str] = {
    "永久基本农田保护区": "#FFE4B5",
    "村庄建设区": "#FF6347",
    "生态保护区": "#2E8B57",
    "一般农地区": "#98FB98",
}


__all__ = [
    "ZONE_TYPE_COLORS",
    "FACILITY_STATUS_COLORS",
    "DEFAULT_ZONE_COLOR",
    "DLBM_TO_DLMC",
    "DLBM_TO_ZONE_TYPE",
    "ZONE_TYPE_TO_DLBMS",
    "BASIC_FARMLAND_CODES",
    "GENERAL_AGRICULTURE_CODES",
    "ECOLOGICAL_CODES",
    "PROTECTED_DLBM_CODES",
    "CONSTRUCTION_ZONE_TYPES",
    "PLANNED_DLBM_TO_ZONE_TYPE",
    "GHYTMC_TO_ZONE_TYPE",
    "GHYTMC_TO_DLMC",
    "PLANNING_ZONE_COLORS",
    "get_zone_color",
    "get_zone_type_for_dlbm",
    "get_zone_type_for_planned_dlbm",
    "get_zone_type_for_ghytmc",
    "get_dlbms_for_zone_type",
    "is_basic_farmland",
    "is_general_agriculture",
]
