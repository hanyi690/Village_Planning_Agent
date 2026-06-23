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
    "1100": "水域及水利设施用地",
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
    "0500": "产业用地",
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
    "1100": "水域",
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
    "水域": ["1100", "3100"],
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


__all__ = [
    "ZONE_TYPE_COLORS",
    "FACILITY_STATUS_COLORS",
    "DEFAULT_ZONE_COLOR",
    "DLBM_TO_DLMC",
    "DLBM_TO_ZONE_TYPE",
    "ZONE_TYPE_TO_DLBMS",
    "get_zone_color",
    "get_zone_type_for_dlbm",
    "get_dlbms_for_zone_type",
]
