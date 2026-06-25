"""
DLBM/DLMC/PLANNING_COLORS mapping and zone color definitions.

Synchronized with frontend: frontend/src/features/planning/constants/gis.ts
"""

from typing import Dict, List, Tuple


# ============================================
# Zone type colors (synced with frontend PLANNING_COLORS.function_zone)
# ============================================

ZONE_TYPE_COLORS: Dict[str, Dict[str, str]] = {
    "居住用地": {"fill": "#FFD700", "stroke": "#B8860B"},
    "产业用地": {"fill": "#FF6B6B", "stroke": "#CC0000"},
    "公共服务用地": {"fill": "#4A90D9", "stroke": "#1E3A5F"},
    "生态绿地": {"fill": "#90EE90", "stroke": "#228B22"},
    "交通用地": {"fill": "#808080", "stroke": "#404040"},
    "水域": {"fill": "#87CEEB", "stroke": "#4169E1"},
    "农业用地": {"fill": "#8B4513", "stroke": "#654321"},
    "商业用地": {"fill": "#FFA500", "stroke": "#CC8400"},
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
    "0900": "交通运输用地",
    "1000": "交通运输用地",
    "1100": "耕地",
    "1200": "其他土地",
    "1400": "草地",
    "2100": "商服用地",
    "2121": "宅基地",
    "3100": "水域",
}

# DLBM → PLANNING_COLORS zone type key
# Maps national land use codes to frontend rendering categories
DLBM_TO_ZONE_TYPE: Dict[str, str] = {
    # 居住用地
    "0700": "居住用地",
    "2121": "居住用地",
    # 产业用地
    "0600": "产业用地",
    "0610": "产业用地",
    "0620": "产业用地",
    "2100": "产业用地",
    # 公共服务用地
    "0800": "公共服务用地",
    "0900": "公共服务用地",
    # 生态绿地
    "0300": "生态绿地",
    "0400": "生态绿地",
    "1400": "生态绿地",
    # 交通用地
    "1000": "交通用地",
    # 水域
    "1100": "农业用地",
    "3100": "水域",
    # 农业用地
    "0100": "农业用地",
    "0110": "农业用地",
    "0120": "农业用地",
    "0200": "农业用地",
    "1200": "农业用地",
    # 商业用地
    "0500": "商业用地",
}

# Zone type → list of DLBM codes (reverse mapping)
ZONE_TYPE_TO_DLBMS: Dict[str, List[str]] = {
    "居住用地": ["0700", "2121"],
    "产业用地": ["0600", "0610", "0620", "2100"],
    "公共服务用地": ["0800", "0900"],
    "生态绿地": ["0300", "0400", "1400"],
    "交通用地": ["1000"],
    "水域": ["3100"],
    "农业用地": ["0100", "0110", "0120", "0200", "1200"],
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
    "1180": "农业用地",  # 水工建筑用地
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
    "PLANNED_DLBM_TO_ZONE_TYPE",
    "GHYTMC_TO_ZONE_TYPE",
    "GHYTMC_TO_DLMC",
    "PLANNING_ZONE_COLORS",
    "get_zone_color",
    "get_zone_type_for_dlbm",
    "get_zone_type_for_planned_dlbm",
    "get_zone_type_for_ghytmc",
    "get_dlbms_for_zone_type",
]
