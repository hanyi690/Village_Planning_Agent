"""
Zone schema: DLBM/planning zone mappings, color definitions, and code sets.

Single source of truth for:
  - DLBM → planning zone mapping (DLBM_TO_PLANNING_ZONE)
  - DLBM → zone type rendering mapping (DLBM_TO_ZONE_TYPE)
  - Planning zone → rendering attributes (PLANNING_ZONE_RENDERING)
  - DLBM code sets (BASIC_FARMLAND_CODES, GENERAL_AGRICULTURE_CODES, etc.)

Synchronized with frontend: frontend/src/features/planning/constants/gis.ts
"""

from typing import Dict, List, Set, Tuple


# ============================================
# SEMANTIC NOTE: Two orthogonal classification systems
#
# 1. Function zones (7 types) — DLBM_TO_ZONE_TYPE
#    Based on GB/T 21010 current land use classification.
#    Used by: function_zone layer, render_planning_layout, _build_default_intent.
#    Categories: 农业用地, 生态绿地, 居住用地, 产业用地,
#                公共服务用地, 商业用地, 交通用地, 水域
#
# 2. Planning zones (4 zones) — DLBM_TO_PLANNING_ZONE
#    Based on 国土空间规划 "三区三线" (three zones, three lines).
#    Used by: planning_zone layer, metric_anchors zone_ratios,
#             MIP allocator, PLANNING_ZONE_COLORS.
#    Categories: 农田保护区, 生态保护区, 村庄建设区, 一般农业区
#
# Mapping: 7→4 is many-to-one (e.g. 居住+产业+公服+商业+交通 → 村庄建设区).
# These two systems MUST NOT be mixed — a single DLBM code maps to
# exactly one zone_type AND exactly one planning_zone, but the
# aggregated areas are computed independently.
# ============================================


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
    "2123": "宅基地退出",
    "2124": "经营性建设用地",
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
    "1100": "农业用地",  # 耕地(三调村庄规划专用编码)
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
    "2123": "居住用地",  # 宅基地退出(GB/T 21010-2017 村庄规划专用)
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
    "居住用地": ["0700", "0701", "0702", "2121", "2123", "2030"],
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

def get_zone_type_for_planned_dlbm(dlbm: str) -> str:
    """Get zone type for a planned DLBM code (规划编码体系).

    Delegates to get_zone_type_for_dlbm — PLANNED_DLBM_TO_ZONE_TYPE
    was a redundant subset of DLBM_TO_ZONE_TYPE and has been removed.
    """
    return get_zone_type_for_dlbm(dlbm)

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
    """Get zone type for a planned DLBM code (规划编码体系).

    Delegates to get_zone_type_for_dlbm — PLANNED_DLBM_TO_ZONE_TYPE
    was a redundant subset of DLBM_TO_ZONE_TYPE and has been removed.
    """
    return get_zone_type_for_dlbm(dlbm)


def get_zone_type_for_ghytmc(ghytmc: str) -> str:
    """Get zone type from GHYTMC planning use category name."""
    return GHYTMC_TO_ZONE_TYPE.get(str(ghytmc).strip(), "农业用地")


# ============================================
# 基本农田 / 一般农业区 DLBM 编码集
# 永久基本农田划定应基于 YJJBNTTB 图层，非 DLBM 映射
# 此集合仅作为无 YJJBNTTB 时的 fallback 分类
# ============================================

# 永久基本农田 DLBM（仅耕地 01 类：水田/水浇地/旱地）
BASIC_FARMLAND_CODES: Set[str] = {
    "0101", "0102", "0103",  # GB/T: 水田/水浇地/旱地
    "0110", "0120", "0130",  # 三调: 水田/水浇地/旱地
    "1100",  # 三调耕地(村庄规划专用编码)
}

# 一般农业区 DLBM（园地 + 设施农用地 + 其他）
GENERAL_AGRICULTURE_CODES: Set[str] = {
    "0100",  # 耕地(大类, 非基本农田)
    "0200", "0201", "0202", "0203", "0204",  # 园地
    "0210", "0220",  # 果园/茶园(三调)
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
# Construction-use zone types — the 5 zone types that constitute 建设用地
# NOTE: This is different from CONSTRUCTION_ZONE_DEF which refers to the GDB layer
# "有条件建设区" (conditional construction zone). This set refers to the
# zone_type categories that are classified as construction land use.
CONSTRUCTION_USE_TYPES: Set[str] = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}

# Backward-compatible alias (deprecated: use CONSTRUCTION_USE_TYPES)
CONSTRUCTION_ZONE_TYPES = CONSTRUCTION_USE_TYPES


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
    "农田保护区": "#FFE4B5",
    "村庄建设区": "#FF6347",
    "生态保护区": "#2E8B57",
    "一般农业区": "#98FB98",
}

# ============================================
# DLBM → 规划分区 单一映射源
# Based on GB/T 21010-2017 + 三区三线 + 各省村庄规划编制技术规范
#
# 规划分区层级(简化为村级4区):
#   农田保护区(300) — 永久基本农田对应耕地
#   生态保护区(100) — 生态红线内林地/草地/水域
#   村庄建设区(510) — 乡村发展区下建设空间
#   一般农业区(520) — 乡村发展区下一般农地
#
# 所有组件必须引用此表，不得另行定义 DLBM→分区映射
# ============================================

DLBM_TO_PLANNING_ZONE: Dict[str, str] = {
    # === 耕地(01) → 农田保护区 ===
    "0101": "农田保护区", "0102": "农田保护区", "0103": "农田保护区",  # GB/T: 水田/水浇地/旱地
    "0110": "农田保护区", "0120": "农田保护区", "0130": "农田保护区",  # 三调: 水田/水浇地/旱地
    "1100": "农田保护区",  # 三调耕地(村庄规划专用编码)
    "1180": "农田保护区",  # 设施农用地(耕地配套)
    # === 耕地大类 → 一般农业区 ===
    "0100": "一般农业区",  # 耕地大类(非基本农田)
    # === 园地(02) → 一般农业区 ===
    "0200": "一般农业区", "0201": "一般农业区", "0202": "一般农业区",
    "0203": "一般农业区", "0204": "一般农业区",  # GB/T
    "0210": "一般农业区", "0220": "一般农业区",  # 三调
    # === 林地(03) → 生态保护区 ===
    "0300": "生态保护区", "0301": "生态保护区", "0302": "生态保护区",
    "0303": "生态保护区", "0304": "生态保护区", "0305": "生态保护区",
    "0306": "生态保护区", "0307": "生态保护区",  # GB/T
    "0310": "生态保护区", "0330": "生态保护区",  # 三调
    "1340": "生态保护区", "1350": "生态保护区",  # 商品林/生态林(三调村庄规划专用)
    # === 草地(04) → 生态保护区 ===
    "0400": "生态保护区", "0401": "生态保护区", "0402": "生态保护区",
    "0403": "生态保护区", "0404": "生态保护区",  # GB/T
    "1400": "生态保护区",  # 三调
    # === 商服(05) → 村庄建设区 ===
    "0500": "村庄建设区",
    # === 工矿(06) → 村庄建设区 ===
    "0600": "村庄建设区", "0601": "村庄建设区", "0602": "村庄建设区", "0603": "村庄建设区",
    "0610": "村庄建设区", "0620": "村庄建设区",
    # === 住宅(07/21) → 村庄建设区 ===
    "0700": "村庄建设区", "0701": "村庄建设区", "0702": "村庄建设区",
    "2030": "村庄建设区", "2121": "村庄建设区", "2123": "村庄建设区",
    # === 公服(08/09) → 村庄建设区 ===
    "0800": "村庄建设区", "0801": "村庄建设区", "0802": "村庄建设区",
    "0803": "村庄建设区", "0806": "村庄建设区", "0810": "村庄建设区",
    "0900": "村庄建设区", "2122": "村庄建设区", "2125": "村庄建设区",
    # === 产业(2124) → 村庄建设区 ===
    "2100": "村庄建设区", "2124": "村庄建设区",
    # === 交通(10/22) → 村庄建设区 ===
    "1000": "村庄建设区", "1001": "村庄建设区", "1002": "村庄建设区",
    "1003": "村庄建设区", "1004": "村庄建设区", "1005": "村庄建设区",
    "1006": "村庄建设区", "1040": "村庄建设区",
    "2126": "村庄建设区", "2200": "村庄建设区",
    # === 水域(11/31) → 生态保护区 ===
    "1101": "生态保护区", "1102": "生态保护区", "1103": "生态保护区",
    "1104": "生态保护区", "1105": "生态保护区", "1106": "生态保护区",
    "1109": "生态保护区", "1110": "生态保护区", "1140": "生态保护区",
    "3100": "生态保护区",
    # === 其他农业 → 一般农业区 ===
    "1200": "一般农业区", "1201": "一般农业区",  # 其他土地
    "1510": "一般农业区",  # 设施农用地
    "2270": "一般农业区",  # 水利设施用地(属水域及水利设施大类11, 农业基础设施)
    "3200": "一般农业区",  # 自然保留地
}

# 规划分区 → 渲染属性派生
PLANNING_ZONE_RENDERING: Dict[str, Dict[str, str]] = {
    "农田保护区": {"zone_type": "农业用地", "fill": "#FFE4B5", "stroke": "#DAA520"},
    "村庄建设区": {"zone_type": "居住用地", "fill": "#FF6347", "stroke": "#CC4F39"},
    "生态保护区": {"zone_type": "生态绿地", "fill": "#2E8B57", "stroke": "#1B5E20"},
    "一般农业区": {"zone_type": "农业用地", "fill": "#98FB98", "stroke": "#66CD66"},
}


def dlbm_to_planning_zone(dlbm: str) -> str:
    """Map DLBM code to planning zone. Single source of truth."""
    return DLBM_TO_PLANNING_ZONE.get(str(dlbm).strip(), "一般农业区")


# ============================================
# 规划分类编码体系 (GHFLBM / GHYTBM)
# 来源：金田村 GDB JT_期末地类_LJJ_20221212 实测数据
#
# 三层编码体系：
#   DLBM → 现状地类编码 (GB/T 21010-2017)
#   GHFLBM → 规划分类编码 (国土空间规划用地分类)
#   GHYTBM → 规划用途编码 (村庄规划用途分类，更细粒度)
#
# 关系：GHYTBM 比 GHFLBM 更细（如 GHFLBM=2120 对应多个 GHYTBM）
# ============================================

# GHFLBM → 含义
GHFLBM_MEANING: Dict[str, str] = {
    "1110": "耕地(规划)",
    "1120": "园地(规划)",
    "1130": "林地(规划)",
    "1200": "草地(规划)",
    "1310": "商品林(规划)",
    "1330": "生态林(规划)",
    "1520": "设施农用地(规划)",
    "1530": "其他农用地(规划)",
    "2120": "农村建设用地(规划)",
    "2270": "水利设施用地(规划)",
    "3110": "水域(规划)",
}

# GHYTBM(规划用途编码) → GHYTMC(规划用途名称)
# Based on: DB64/T 1993-2024 (18一级类/77二级类/26三级类)
#           国土空间调查用地用海分类指南(2023) 自然资发〔2023〕234号
#           GB/T 21010-2017 土地利用现状分类
# Covers: 18 一级类 + 77 二级类 + village-specific 21xx codes
GHYTBM_TO_GHYTMC: Dict[str, str] = {
    # ── 01 耕地 ──
    "0100": "耕地", "0101": "水田", "0102": "水浇地", "0103": "旱地",
    # ── 02 园地 ──
    "0200": "园地", "0201": "果园", "0204": "油料园地", "0205": "其他园地",
    # ── 03 林地 ──
    "0300": "林地", "0301": "乔木林地", "0302": "竹林地",
    "0303": "灌木林地", "0304": "其他林地",
    "1340": "商品林", "1350": "生态林",
    # ── 04 草地 ──
    "0400": "草地", "0401": "天然牧草地", "0402": "人工牧草地", "0403": "其他草地",
    # ── 05 湿地 ──
    "0500": "湿地", "0501": "森林沼泽", "0502": "灌木沼泽",
    "0503": "沼泽草地", "0506": "内陆滩涂",
    # ── 06 农业设施建设用地 ──
    "0600": "农业设施建设用地",
    "0601": "农村道路", "0602": "设施农用地",
    # ── 07 居住用地 ──
    "0700": "居住用地", "0703": "农村宅基地", "0704": "农村社区服务设施用地",
    "070301": "一类农村宅基地", "070302": "二类农村宅基地", "070303": "混合式住宅用地",
    # ── 08 公共管理与公共服务 ──
    "0800": "公共管理与公共服务用地",
    "0801": "机关团体用地", "0802": "科研用地",
    "0803": "文化用地", "0804": "教育用地",
    "080402": "中等职业教育用地", "080403": "中小学用地", "080404": "幼儿园用地",
    "0805": "体育用地", "0806": "医疗卫生用地",
    "080601": "医院用地", "080602": "基层医疗卫生设施用地",
    "0807": "社会福利用地",
    # ── 09 商业服务业 ──
    "0900": "商业服务业用地", "0901": "商业用地",
    "0902": "商务金融用地", "0903": "娱乐用地",
    # ── 10 工矿用地 ──
    "1000": "工矿用地", "1001": "工业用地", "1002": "采矿用地",
    # ── 11 仓储用地 ──
    "1100": "仓储用地", "1101": "物流仓储用地",
    # ── 12 交通运输用地 ──
    "1200": "交通运输用地", "1201": "铁路用地", "1202": "公路用地",
    "1207": "城镇村道路用地", "1208": "交通场站用地",
    # ── 13 公用设施用地 ──
    "1300": "公用设施用地",
    "1301": "供水用地", "1302": "排水用地", "1303": "供电用地",
    "1306": "通信用地", "1309": "环卫用地", "1310": "消防用地",
    "1311": "水工设施用地",
    # ── 14 绿地与开敞空间用地 ──
    "1400": "绿地与开敞空间用地", "1401": "公园绿地", "1402": "防护绿地",
    "1403": "广场用地",
    # ── 村庄规划专用编码 (三调21xx + GHYTBM) ──
    "2121": "宅基地", "2122": "公共服务设施用地",
    "2123": "基础设施用地", "2124": "经营性建设用地",
    "2125": "景观与绿化用地", "2126": "村内交通用地",
    "2200": "对外交通用地", "2270": "水利设施用地",
    "3100": "水域",
    "1500": "特殊用地", "1510": "设施农用地",
    # ── 16 留白用地 ──
    "1600": "留白用地",
    # ── 17 陆地水域 ──
    "1700": "陆地水域", "1701": "河流水面", "1702": "湖泊水面",
    "1703": "水库水面", "1704": "坑塘水面", "1705": "沟渠",
    # ── 18 其他土地 ──
    "1800": "其他土地", "1801": "空闲地", "1802": "田坎",
    "1803": "盐碱地", "1804": "沙地", "1805": "裸土地",
    "1806": "裸岩石砾地",
}

# GHYTBM → zone_type (比 GHYTMC 更精确的编码映射)
# Synced with GHYTBM_TO_GHYTMC — every key must have a zone_type mapping
GHYTBM_TO_ZONE_TYPE: Dict[str, str] = {
    # ── 01 耕地 → 农业用地 ──
    "0100": "农业用地", "0101": "农业用地", "0102": "农业用地", "0103": "农业用地",
    # ── 02 园地 → 农业用地 ──
    "0200": "农业用地", "0201": "农业用地", "0204": "农业用地", "0205": "农业用地",
    # ── 03 林地 → 生态绿地 ──
    "0300": "生态绿地", "0301": "生态绿地", "0302": "生态绿地",
    "0303": "生态绿地", "0304": "生态绿地",
    "1340": "生态绿地", "1350": "生态绿地",
    # ── 04 草地 → 生态绿地 ──
    "0400": "生态绿地", "0401": "生态绿地", "0402": "生态绿地", "0403": "生态绿地",
    # ── 05 湿地 → 生态绿地 ──
    "0500": "生态绿地", "0501": "生态绿地", "0502": "生态绿地",
    "0503": "生态绿地", "0506": "生态绿地",
    # ── 06 农业设施建设用地 ──
    "0600": "交通用地", "0601": "交通用地", "0602": "农业用地",
    # ── 07 居住用地 ──
    "0700": "居住用地", "0703": "居住用地", "0704": "公共服务用地",
    "070301": "居住用地", "070302": "居住用地", "070303": "居住用地",
    # ── 08 公共管理与公共服务 ──
    "0800": "公共服务用地", "0801": "公共服务用地", "0802": "公共服务用地",
    "0803": "公共服务用地", "0804": "公共服务用地",
    "080402": "公共服务用地", "080403": "公共服务用地", "080404": "公共服务用地",
    "0805": "公共服务用地", "0806": "公共服务用地",
    "080601": "公共服务用地", "080602": "公共服务用地",
    "0807": "公共服务用地",
    # ── 09 商业服务业 ──
    "0900": "商业用地", "0901": "商业用地",
    "0902": "商业用地", "0903": "商业用地",
    # ── 10 工矿用地 ──
    "1000": "产业用地", "1001": "产业用地", "1002": "产业用地",
    # ── 11 仓储用地 ──
    "1100": "产业用地", "1101": "产业用地",
    # ── 12 交通运输用地 ──
    "1200": "交通用地", "1201": "交通用地", "1202": "交通用地",
    "1207": "交通用地", "1208": "交通用地",
    # ── 13 公用设施用地 ──
    "1300": "公共服务用地",
    "1301": "公共服务用地", "1302": "公共服务用地", "1303": "公共服务用地",
    "1306": "公共服务用地", "1309": "公共服务用地", "1310": "公共服务用地",
    "1311": "农业用地",
    # ── 村庄规划专用编码 ──
    "2121": "居住用地", "2122": "公共服务用地",
    "2123": "交通用地", "2124": "产业用地",
    "2125": "生态绿地", "2126": "交通用地",
    "2200": "交通用地", "2270": "农业用地",
    "3100": "水域",
    "1500": "产业用地", "1510": "农业用地",
    # ── 14 绿地与开敞空间用地 → 生态绿地 ──
    "1400": "生态绿地", "1401": "生态绿地", "1402": "生态绿地",
    "1403": "生态绿地",
    # ── 16 留白用地 → 农业用地 (未确定用途，暂归农业) ──
    "1600": "农业用地",
    # ── 17 陆地水域 → 水域 ──
    "1700": "水域", "1701": "水域", "1702": "水域",
    "1703": "水域", "1704": "水域", "1705": "水域",
    # ── 18 其他土地 → 农业用地 ──
    "1800": "农业用地", "1801": "农业用地", "1802": "农业用地",
    "1803": "农业用地", "1804": "农业用地", "1805": "农业用地",
    "1806": "农业用地",
}


def get_zone_type_for_ghytbm(ghytbm: str) -> str:
    """Get zone type from GHYTBM planning use code."""
    return GHYTBM_TO_ZONE_TYPE.get(str(ghytbm).strip(), "农业用地")


def get_ghytmc_for_ghytbm(ghytbm: str) -> str:
    """Get GHYTMC (name) from GHYTBM (code)."""
    return GHYTBM_TO_GHYTMC.get(str(ghytbm).strip(), "")


# ============================================
# DB22/T 3407-2022 要素分类编码 (10位层次码)
# 结构: XX(大类) X(亚类) X(小类) X(一级) X(二级) XX(三级) X(四级) X(五级)
# 大类: 10=基础地理信息, 20=国土空间规划
# 亚类: 9=国土空间规划业务
# 小类: 6=村庄规划
# 一级: 1=全域总体规划, 2=专项规划, 3=详细规划
# ============================================

ELEMENT_CODE_PREFIXES: Dict[str, str] = {
    "base_geographic": "10",
    "spatial_planning": "2096",
    "current": "209631",
    "planned": "209632",
    "three_line": "20963201",
    "planning_control": "20963202",
    "protection": "20963203",
    "infrastructure": "20963204",
}


def parse_element_code(code: str) -> Dict[str, str]:
    """Parse a DB22/T 3407-2022 element classification code.

    Returns dict with keys: category, major_class, sub_class, level info.
    """
    code = str(code).strip()
    if len(code) < 10:
        return {"code": code, "category": "unknown", "major_class": code[:2] if len(code) >= 2 else ""}
    major = code[:2]
    category = "base_geographic" if major == "10" else "spatial_planning" if major == "20" else "other"
    result = {"code": code, "category": category, "major_class": major}
    if category == "spatial_planning" and len(code) >= 4:
        result["sub_class"] = code[2]
        result["minor_class"] = code[3]
        if code[3] == "6":
            result["planning_level"] = "village"
            if len(code) >= 5:
                first_level = code[4]
                level_map = {"1": "全域总体规划", "2": "专项规划", "3": "详细规划"}
                result["first_level"] = level_map.get(first_level, first_level)
    return result


# ============================================
# 三线管控图层定义
# 三线 = 生态保护红线 + 永久基本农田 + 村庄建设边界
# 对应 GDB 中的独立图层，非 sensitivity_zone 的聚合概念
# ============================================

THREE_LINE_TYPES: Dict[str, Dict[str, str]] = {
    "ecological_redline": {
        "color": "#FF0000",
        "line_style": "dash",
        "fill_opacity": "0.0",
        "stroke_width": "2.5",
        "label": "生态保护红线",
        "gdb_key": "ecological_redline",
    },
    "farmland_protection": {
        "color": "#00AA00",
        "line_style": "solid",
        "fill_opacity": "0.15",
        "stroke_width": "2.0",
        "label": "永久基本农田",
        "gdb_key": "farmland_protection",
    },
    "historical_protection": {
        "color": "#FF8800",
        "line_style": "dot-dash",
        "fill_opacity": "0.0",
        "stroke_width": "2.0",
        "label": "历史文化保护线",
        "gdb_key": "historical_protection",
    },
}

# 有条件建设区定义
CONSTRUCTION_ZONE_DEF: Dict[str, str] = {
    "color": "#FF4444",
    "fill_opacity": "0.2",
    "stroke_width": "1.5",
    "line_style": "solid",
    "label": "有条件建设区",
    "lx_field": "有条件建设区",
    "gdb_key": "construction_zone",
}

# 注记图层分类
ANNOTATION_CATEGORIES: Dict[str, str] = {
    "现状设施点": "current",
    "规划设施点": "planned",
    "地名": "toponym",
    "水系": "hydrology",
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
    "CONSTRUCTION_USE_TYPES",
    "CONSTRUCTION_ZONE_TYPES",
    "GHYTMC_TO_ZONE_TYPE",
    "GHYTMC_TO_DLMC",
    "PLANNING_ZONE_COLORS",
    "DLBM_TO_PLANNING_ZONE",
    "PLANNING_ZONE_RENDERING",
    "get_zone_color",
    "get_zone_type_for_dlbm",
    "get_zone_type_for_planned_dlbm",
    "get_zone_type_for_ghytmc",
    "get_dlbms_for_zone_type",
    "is_basic_farmland",
    "is_general_agriculture",
    "dlbm_to_planning_zone",
    # Planning classification codes
    "GHFLBM_MEANING",
    "GHYTBM_TO_GHYTMC",
    "GHYTBM_TO_ZONE_TYPE",
    "get_zone_type_for_ghytbm",
    "get_ghytmc_for_ghytbm",
    # Three-line control
    "THREE_LINE_TYPES",
    "CONSTRUCTION_ZONE_DEF",
    "ANNOTATION_CATEGORIES",
    # Element classification codes (DB22/T 3407-2022)
    "ELEMENT_CODE_PREFIXES",
    "parse_element_code",
]
