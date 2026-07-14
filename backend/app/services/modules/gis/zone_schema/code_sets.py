"""DLBM code sets, three-line control types, V/N/E classification, and base conversion tables.

Includes:
  - BASIC_FARMLAND_CODES / GENERAL_AGRICULTURE_CODES / ECOLOGICAL_CODES
  - THREE_LINE_TYPES (三线管控图层)
  - V/N/E village planning land classification
  - SDDLBM → YDYHFLDM base conversion (三调基数转换)
  - GHYTBM → V/N/E cross-mapping
  - DB22/T 3407-2022 element classification codes
"""

from typing import Dict, List, Set, Tuple

# ── DLBM code sets ───────────────────────────────────────────

BASIC_FARMLAND_CODES: Set[str] = {
    "0101", "0102", "0103",
    "0110", "0120", "0130",
    "1100",
}

GENERAL_AGRICULTURE_CODES: Set[str] = {
    "0100",
    "0200", "0201", "0202", "0203", "0204",
    "0210", "0220",
    "1200", "1201",
    "1510",
    "2270",
    "3200",
}

ECOLOGICAL_CODES: Set[str] = {
    "0300", "0301", "0302", "0303", "0304", "0305", "0306", "0307",
    "0310", "0330", "1340", "1350",
    "0400", "0401", "0402", "0403", "0404", "1400",
    "1101", "1102", "1103", "1104", "1105", "1106", "1109",
    "1110", "1140", "1180", "3100",
}

# Sub-sets for 6-class secondary zoning (dual-layer system)
FOREST_CODES: Set[str] = {
    "0300", "0301", "0302", "0303", "0304", "0305", "0306", "0307",
    "0310", "0330",
}

GRASSLAND_CODES: Set[str] = {
    "0400", "0401", "0402", "0403", "0404", "1400",
}

FORESTRY_CODES: Set[str] = {
    "1340", "1350",
}

WATER_CODES: Set[str] = {
    "1101", "1102", "1103", "1104", "1105", "1106", "1109",
    "1110", "1140", "1180", "3100",
}

# Strict ecological protection zone: forest + water (redline-managed)
ECOLOGICAL_PROTECTION_CODES: Set[str] = FOREST_CODES | WATER_CODES

# Ecological control zone: grassland (non-redline ecological space)
ECOLOGICAL_CONTROL_CODES: Set[str] = GRASSLAND_CODES

PROTECTED_DLBM_CODES: Set[str] = BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES | ECOLOGICAL_CODES

CONSTRUCTION_USE_TYPES: Set[str] = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}
CONSTRUCTION_ZONE_TYPES = CONSTRUCTION_USE_TYPES


def is_basic_farmland(dlbm: str) -> bool:
    """Check if a DLBM code belongs to basic farmland."""
    return str(dlbm).strip() in BASIC_FARMLAND_CODES


def is_general_agriculture(dlbm: str) -> bool:
    """Check if a DLBM code belongs to general agriculture area."""
    return str(dlbm).strip() in GENERAL_AGRICULTURE_CODES


# ── Three-line control layer definitions ─────────────────────

THREE_LINE_TYPES: Dict[str, Dict[str, str]] = {
    "ecological_redline": {
        "color": "#FF0000", "line_style": "dash", "fill_opacity": "0.0",
        "stroke_width": "2.5", "label": "生态保护红线", "gdb_key": "ecological_redline",
    },
    "farmland_protection": {
        "color": "#00AA00", "line_style": "solid", "fill_opacity": "0.15",
        "stroke_width": "2.0", "label": "永久基本农田", "gdb_key": "farmland_protection",
    },
    "historical_protection": {
        "color": "#FF8800", "line_style": "dot-dash", "fill_opacity": "0.0",
        "stroke_width": "2.0", "label": "历史文化保护线", "gdb_key": "historical_protection",
    },
}

CONSTRUCTION_ZONE_DEF: Dict[str, str] = {
    "color": "#FF4444", "fill_opacity": "0.2", "stroke_width": "1.5",
    "line_style": "solid", "label": "有条件建设区",
    "lx_field": "有条件建设区", "gdb_key": "construction_zone",
}

ANNOTATION_CATEGORIES: Dict[str, str] = {
    "现状设施点": "current", "规划设施点": "planned",
    "地名": "toponym", "水系": "hydrology",
}


# ── V/N/E village planning land classification ───────────────

VNE_CODE_TO_NAME: Dict[str, str] = {
    "V": "村庄建设用地",
    "V1": "村民住宅用地", "V11": "住宅用地", "V12": "混合式住宅用地",
    "V2": "村庄公共服务用地", "V21": "村庄公共服务设施用地", "V22": "村庄公共场地",
    "V3": "村庄产业用地", "V31": "村庄商业服务业设施用地", "V32": "村庄生产仓储用地",
    "V4": "村庄基础设施用地", "V41": "村庄道路用地", "V42": "村庄交通设施用地",
    "V43": "村庄公用设施用地",
    "V9": "村庄其他建设用地",
    "N": "非村庄建设用地", "N1": "对外交通设施用地", "N2": "国有建设用地",
    "E": "非建设用地",
    "E1": "水域", "E11": "自然水域", "E12": "水库", "E13": "坑塘沟渠",
    "E2": "农林用地", "E21": "设施农用地", "E22": "农用道路", "E23": "其他农林用地",
    "E9": "其他非建设用地",
}

VNE_TO_ZONE_TYPE: Dict[str, str] = {
    "V": "居住用地", "V1": "居住用地", "V11": "居住用地", "V12": "居住用地",
    "V2": "公共服务用地", "V21": "公共服务用地", "V22": "公共服务用地",
    "V3": "产业用地", "V31": "商业用地", "V32": "产业用地",
    "V4": "交通用地", "V41": "交通用地", "V42": "交通用地", "V43": "公共服务用地",
    "V9": "居住用地",
    "N": "交通用地", "N1": "交通用地", "N2": "产业用地",
    "E": "农业用地", "E1": "水域", "E11": "水域", "E12": "水域", "E13": "水域",
    "E2": "农业用地", "E21": "农业用地", "E22": "交通用地", "E23": "农业用地",
    "E9": "农业用地",
}

ZONE_TYPE_TO_VNE: Dict[str, str] = {
    "居住用地": "V1", "产业用地": "V3", "商业用地": "V31",
    "公共服务用地": "V2", "交通用地": "V4",
    "农业用地": "E2", "生态绿地": "E2", "水域": "E1",
}


def get_zone_type_for_vne(vne_code: str) -> str:
    """Get zone type from V/N/E classification code."""
    return VNE_TO_ZONE_TYPE.get(str(vne_code).strip(), "农业用地")


def get_vne_for_zone_type(zone_type: str) -> str:
    """Get V/N/E major category for a zone type."""
    return ZONE_TYPE_TO_VNE.get(zone_type, "E9")


# ── SDDLBM → YDYHFLDM base conversion ────────────────────────

SDDLBM_TO_YDYHFLDM: Dict[str, Tuple[str, str]] = {
    "0101": ("0101", "一一对应"), "0102": ("0102", "一一对应"), "0103": ("0103", "一一对应"),
    "0201": ("0201", "一一对应"), "0202": ("0202", "一一对应"),
    "0203": ("0203", "一一对应"), "0204": ("0204", "一一对应"),
    "0301": ("0301", "一一对应"), "0302": ("0302", "一一对应"),
    "0303": ("0303", "一一对应"), "0304": ("0304", "一一对应"),
    "0305": ("0305", "一一对应"), "0306": ("0306", "一一对应"),
    "0307": ("0307", "一一对应"),
    "0401": ("0401", "一一对应"), "0402": ("0402", "一一对应"),
    "0403": ("0403", "一一对应"), "0404": ("0404", "一一对应"),
    "0601": ("1001", "一一对应"), "0602": ("1002", "一一对应"), "0603": ("1003", "一一对应"),
    "0701": ("0701", "一一对应"), "0702": ("0702", "一一对应"),
    "1101": ("1701", "一一对应"), "1102": ("1702", "一一对应"),
    "1103": ("1703", "一一对应"), "1104": ("1704", "一一对应"),
    "1109": ("1311", "一一对应"),
    "05H1": ("0900", "一对多"), "08H2": ("0800", "一对多"),
    "1004": ("1207", "一对多"), "1006": ("0601", "一对多"),
    "1001": ("1201", "一对多"), "1005": ("1208", "一对多"),
    "1008": ("1204", "一对多"),
    "2121": ("0702", "一一对应"), "2122": ("0800", "一对多"),
    "2123": ("1300", "一对多"), "2124": ("0900", "一对多"),
    "2125": ("1401", "一对多"), "2126": ("0601", "一对多"),
}


def convert_sddlbm_to_ydyhfldm(sddlbm: str) -> Tuple[str, str]:
    """Convert third-survey DLBM to land-use classification code.

    Returns (ydyhfldm, conversion_type).
    """
    result = SDDLBM_TO_YDYHFLDM.get(str(sddlbm).strip())
    if result:
        return result
    return (sddlbm, "无对应")


# ── GHYTBM → V/N/E cross-mapping ─────────────────────────────

GHYTBM_TO_VNE: Dict[str, str] = {
    "2121": "V11", "2122": "V21", "2123": "V43", "2124": "V31",
    "2125": "V22", "2126": "V41",
    "2200": "N1",
    "1100": "E23", "1200": "E23", "1340": "E23", "1350": "E23",
    "1400": "E23", "1510": "E21", "1500": "E23",
    "2270": "E12", "3100": "E11", "3200": "E9",
}


def get_vne_for_ghytbm(ghytbm: str) -> str:
    """Get V/N/E code from GHYTBM."""
    return GHYTBM_TO_VNE.get(str(ghytbm).strip(), "E9")


# ── DB22/T 3407-2022 element classification codes ─────────────

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
    """Parse a DB22/T 3407-2022 element classification code."""
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
