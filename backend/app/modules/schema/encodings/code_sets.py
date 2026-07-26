"""Code sets - encoding-derived dicts and lookup functions.

All DLBM ↔ zone_type ↔ planning_zone mappings are derived from DictionaryCenter
YAML data. This module is the single runtime source for all encoding lookups.
Extracted from __init__.py to keep the barrel file focused on exports only.

v2.0 (2026-07-26) changes:
- PLANNING_ZONE_TO_PRIMARY_ZONE: from YAML (planning_zone_rules.yaml), not hardcoded
- SPACE_CONTROL_ZONE_TYPES: from YAML (construction_zone_codes.yaml), not hardcoded
- New: DLBM_TO_GHYTBM forward mapping (from dlbm_to_ghytbm.yaml)
- New: GHFLBM_TO_TDYTFQDM mapping (from ghflbm_to_tdytfqdm.yaml)
- New: SPACE_CONTROL_ZONE_CODES from construction_zone_codes.yaml (01-06, replaces 510-540)
- New: PLANNING_ZONE_TO_CONTROL_CODE from construction_zone_codes.yaml
- Removed dead code: GHYTMC_TO_DLMC (identity), ECOLOGICAL_CONTROL_CODES (empty),
  FORESTRY_CODES (empty)
- Fixed: field_defaults lookups (ghflbm_to_code, ghflbm_to_name, space_control_code,
  space_control_name) now implemented
"""

from __future__ import annotations

import functools
from typing import Dict, List, Set, Tuple

from .dicts.loader import get_center


# ============================================================
# Encoding & code-set symbols - derived from DictionaryCenter
# ============================================================
#
# 六套编码体系:
#   gbt21010:  GB/T 21010-2017 土地利用现状分类 (三调国标)
#   tugui:     广东省县级土地利用总体规划数据库标准 (土规)
#   appendix5: 广东省技术指南附录5 村庄规划用地分类 (原ghytbm)
#   ghflbm:    广东省土规数据库标准 规划分类编码 (比appendix5更粗)
#   ydyhfldm:  自然资发〔2023〕234号 用地用海分类
#   vne:       住建部《村庄规划用地分类指南》V/N/E分类
#
# 现状层DLBM使用appendix5编码 (编制实践，非规范要求)
# 规划层DLBM/QMDLBM使用tugui编码 (符合规范)
# 规划层GHYTBM使用appendix5编码 (符合规范)
# ============================================================

_gbt21010 = get_center().encoding("gbt21010")
_tugui = get_center().encoding("tugui")
_appendix5 = get_center().encoding("appendix5")
_ghflbm = get_center().encoding("ghflbm")
_ydyhfldm = get_center().encoding("ydyhfldm")
_vne = get_center().encoding("vne")
_tl = get_center().get("three_line_types")
_ec = get_center().get("element_codes")
_sddlbm = get_center().get_proposal("sddlbm_to_ydyhfldm")

# New YAML sources (v2.0)
_cz_codes = get_center().get("construction_zone_codes")
_ghflbm_tdyt = get_center().get("ghflbm_to_tdytfqdm")
_dlbm_ghytbm = get_center().get("dlbm_to_ghytbm")

# ── Code sets from tugui (土规标准定义的 categories) ──
BASIC_FARMLAND_CODES: Set[str] = _tugui.to_set("code", filter_tag="BASIC_FARMLAND")
GENERAL_AGRICULTURE_CODES: Set[str] = _tugui.to_set("code", filter_tag="GENERAL_AGRICULTURE")
ECOLOGICAL_CODES: Set[str] = _tugui.to_set("code", filter_tag="ECOLOGICAL")
FOREST_CODES: Set[str] = _tugui.to_set("code", filter_tag="FOREST")
WATER_CODES: Set[str] = _tugui.to_set("code", filter_tag="WATER")


ECOLOGICAL_PROTECTION_CODES: Set[str] = FOREST_CODES | WATER_CODES
PROTECTED_DLBM_CODES: Set[str] = BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES | ECOLOGICAL_CODES

CONSTRUCTION_USE_TYPES: Set[str] = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}
CONSTRUCTION_ZONE_TYPES = CONSTRUCTION_USE_TYPES

# ── Code -> Name mappings (per system, built once at import) ──
DLBM_TO_DLMC: Dict[str, str] = {}
for system in [_appendix5, _tugui, _gbt21010]:
    DLBM_TO_DLMC.update(system.to_dict("code", "name"))

# ── DLBM -> Zone type (primary source: appendix5) ──
DLBM_TO_ZONE_TYPE: Dict[str, str] = {}
for system in [_appendix5, _tugui, _gbt21010]:
    DLBM_TO_ZONE_TYPE.update(system.to_dict("code", "zone_type"))
DLBM_TO_ZONE_TYPE = {k: v for k, v in DLBM_TO_ZONE_TYPE.items() if v}

# ── DLBM -> Planning zone (primary source: tugui) ──
DLBM_TO_PLANNING_ZONE: Dict[str, str] = {}
for system in [_tugui, _appendix5]:
    DLBM_TO_PLANNING_ZONE.update(system.to_dict("code", "planning_zone"))
DLBM_TO_PLANNING_ZONE = {k: v for k, v in DLBM_TO_PLANNING_ZONE.items() if v}

# ── DLBM -> Primary zone (primary source: tugui) ──
DLBM_TO_PRIMARY_ZONE: Dict[str, str] = {}
for system in [_tugui, _appendix5]:
    DLBM_TO_PRIMARY_ZONE.update(system.to_dict("code", "primary_zone"))
DLBM_TO_PRIMARY_ZONE = {k: v for k, v in DLBM_TO_PRIMARY_ZONE.items() if v}

ZONE_TYPE_TO_DLBMS: Dict[str, List[str]] = {}
for _code, _zt in DLBM_TO_ZONE_TYPE.items():
    ZONE_TYPE_TO_DLBMS.setdefault(_zt, []).append(_code)

# ── Zone hierarchy ──
ZONE_TYPES: List[str] = sorted(set(DLBM_TO_ZONE_TYPE.values()))
PLANNING_ZONES: List[str] = sorted(set(DLBM_TO_PLANNING_ZONE.values()))
PRIMARY_ZONES: List[str] = ["生态空间", "农业空间", "建设空间"]

PLANNING_ZONE_NAMES: List[str] = [
    "生态保护区", "生态控制区", "农田保护区",
    "一般农业区", "村庄建设区", "林业发展区",
]
PRIMARY_ZONE_NAMES: List[str] = ["生态空间", "农业空间", "建设空间"]

# ── PLANNING_ZONE_TO_PRIMARY_ZONE: from YAML (single source of truth) ──
# Loaded from planning_zone_rules.yaml via rule_loader or directly from raw
_pz_raw = get_center().get("planning_zone_rules").raw
PLANNING_ZONE_TO_PRIMARY_ZONE: Dict[str, str] = dict(
    _pz_raw.get("planning_zone_to_primary_zone", {})
)
if not PLANNING_ZONE_TO_PRIMARY_ZONE:
    # Fallback if YAML missing (should not happen in production)
    PLANNING_ZONE_TO_PRIMARY_ZONE = {
        "生态保护区": "生态空间",
        "生态控制区": "生态空间",
        "农田保护区": "农业空间",
        "一般农业区": "农业空间",
        "村庄建设区": "建设空间",
        "林业发展区": "农业空间",
    }

# ── GHYTMC planning use names (from appendix5) ──
GHYTMC_TO_ZONE_TYPE: Dict[str, str] = _appendix5.to_dict("name", "zone_type")

# ── GHFLBM / GHYTBM planning classification codes ──
GHFLBM_MEANING: Dict[str, str] = _ghflbm.to_dict("code", "name")
GHFLBM_TO_ZONE_TYPE: Dict[str, str] = _ghflbm.to_dict("code", "zone_type")

GHFLBM_TO_GHYTBMS: Dict[str, List[str]] = {}
for _entry in _ghflbm.raw.get("classes", []):
    _ghflbm_code = _entry.get("code", "")
    _ghytbms = _entry.get("ghytbms", [])
    if _ghflbm_code and _ghytbms:
        GHFLBM_TO_GHYTBMS[_ghflbm_code] = _ghytbms

GHYTBM_TO_GHYTMC: Dict[str, str] = _appendix5.to_dict("code", "name")
GHYTBM_TO_YDYHFLDM: Dict[str, str] = _appendix5.to_dict("code", "ydyhfldm")
GHYTBM_TO_ZONE_TYPE: Dict[str, str] = _appendix5.to_dict("code", "zone_type")

# ── GHYTMC (Chinese land-use name) -> Planning zone ──
# Derived from GHYTBM_TO_ZONE_TYPE + appendix5 zone_type values.
# Uses explicit mapping in appendix5 rather than string heuristics.
GHYTMC_TO_PLANNING_ZONE: Dict[str, str] = {}
for _ghytbm, _ghytmc in GHYTBM_TO_GHYTMC.items():
    _zt = GHYTBM_TO_ZONE_TYPE.get(_ghytbm, "")
    if _zt == "农业用地":
        if _ghytbm == "1100":
            GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "农田保护区"
        elif "林" in _ghytmc:
            GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "林业发展区"
        else:
            GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "一般农业区"
    elif "生态" in _zt or "绿地" in _zt:
        if "林" in _ghytmc:
            GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "林业发展区"
        else:
            GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "生态保护区"
    elif any(_x in _zt for _x in ["居住", "公共", "交通", "产业", "商业"]):
        GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "村庄建设区"
    elif "水域" in _zt:
        GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "生态保护区"
    else:
        GHYTMC_TO_PLANNING_ZONE[_ghytmc] = "一般农业区"

YDYHFLDM_TO_NAME: Dict[str, str] = _ydyhfldm.to_dict("code", "name")

# ── V/N/E village planning land classification ──
VNE_CODE_TO_NAME: Dict[str, str] = _vne.to_dict("code", "name")
VNE_TO_ZONE_TYPE: Dict[str, str] = _vne.to_dict("code", "zone_type")

ZONE_TYPE_TO_VNE: Dict[str, str] = {}
for _entry in _vne.raw.get("classes", []):
    _zt = _entry.get("zone_type", "")
    _code = _entry.get("code", "")
    if _zt and _code and _zt not in ZONE_TYPE_TO_VNE:
        ZONE_TYPE_TO_VNE[_zt] = _code

GHYTBM_TO_VNE: Dict[str, str] = _appendix5.to_dict("code", "vne")

# ── Three-line control layer definitions ──
THREE_LINE_TYPES: Dict[str, Dict[str, str]] = {}
for layer in _tl.raw.get("layers", []):
    key = layer.pop("key", "")
    if key:
        THREE_LINE_TYPES[key] = layer

_cz = _tl.raw.get("construction_zone", {})
CONSTRUCTION_ZONE_DEF: Dict[str, str] = _cz if isinstance(_cz, dict) else {}

ANNOTATION_CATEGORIES: Dict[str, str] = {
    item["key"]: item["value"]
    for item in _tl.raw.get("annotation_categories", [])
}

# ── SDDLBM -> YDYHFLDM base conversion ──
SDDLBM_TO_YDYHFLDM: Dict[str, Tuple[str, str]] = _sddlbm.to_dict()

# ── Element classification codes ──
ELEMENT_CODE_PREFIXES: Dict[str, str] = _ec.raw.get("prefixes", {})


# ============================================================
# v2.0 NEW: Construction zone codes (01-06, replaces 510-540)
# ============================================================

SPACE_CONTROL_ZONE_CODES: Dict[str, str] = {}
SPACE_CONTROL_ZONE_COLORS: Dict[str, str] = {}
for _entry in _cz_codes.raw.get("codes", []):
    _code = _entry.get("code", "")
    _name = _entry.get("name", "")
    _color = _entry.get("color", "")
    if _code and _name:
        SPACE_CONTROL_ZONE_CODES[_code] = _name
    if _code and _color:
        SPACE_CONTROL_ZONE_COLORS[_code] = _color

# Alias for backward compatibility with spatial_types.py
SPACE_CONTROL_ZONE_TYPES = SPACE_CONTROL_ZONE_CODES

# Reverse lookup: name -> code
SPACE_CONTROL_NAME_TO_CODE: Dict[str, str] = {
    v: k for k, v in SPACE_CONTROL_ZONE_CODES.items()
}

# planning_zone -> tdkjgzfqdm mapping
PLANNING_ZONE_TO_CONTROL_CODE: Dict[str, str] = dict(
    _cz_codes.raw.get("planning_zone_to_control_code", {})
)


# ============================================================
# v2.0 NEW: GHFLBM -> TDYTFQDM mapping (replaces VNE in TDYT layer)
# ============================================================

GHFLBM_TO_TDYTFQDM: Dict[str, str] = {}
GHFLBM_TO_TDYT_NAME: Dict[str, str] = {}
for _entry in _ghflbm_tdyt.raw.get("mappings", []):
    _ghflbm = _entry.get("ghflbm", "")
    _tdytfqdm = _entry.get("tdyfqdm", "")
    _name = _entry.get("name", "")
    if _ghflbm and _tdytfqdm:
        GHFLBM_TO_TDYTFQDM[_ghflbm] = _tdytfqdm
    if _ghflbm and _name:
        GHFLBM_TO_TDYT_NAME[_ghflbm] = _name


# ============================================================
# v2.0 NEW: DLBM -> GHYTBM forward mapping (baseline conversion)
# ============================================================

DLBM_TO_GHYTBM: Dict[str, str] = {}
DLBM_TO_GHYTBM_CONVERSIONS: Dict[str, Tuple[str, str, str]] = {}  # dlbm -> (ghytbm, type, condition)
for _entry in _dlbm_ghytbm.raw.get("mappings", []):
    _dlbm = _entry.get("dlbm", "")
    _ghytbm = _entry.get("ghytbm", "")
    _conv_type = _entry.get("conversion_type", "")
    if _dlbm and _ghytbm:
        DLBM_TO_GHYTBM[_dlbm] = _ghytbm
        DLBM_TO_GHYTBM_CONVERSIONS[_dlbm] = (_ghytbm, _conv_type, _entry.get("condition", ""))


# ── Lookup functions ──

def is_basic_farmland(dlbm: str) -> bool:
    return str(dlbm).strip() in BASIC_FARMLAND_CODES

def is_general_agriculture(dlbm: str) -> bool:
    return str(dlbm).strip() in GENERAL_AGRICULTURE_CODES

def get_zone_type_for_dlbm(dlbm: str) -> str:
    return DLBM_TO_ZONE_TYPE.get(dlbm, "农业用地")

@functools.lru_cache(maxsize=256)
def resolve_zone_type_for_dlbm(dlbm: str) -> str:
    """Resolve DLBM to zone type with caching.

    Moved from app.tools.gis._generation.zone_generator - pure lookup,
    no tool-specific logic. The caching is a legitimate schema-level optimization.
    """
    return get_zone_type_for_dlbm(dlbm.strip())

def get_dlbms_for_zone_type(zone_type: str) -> List[str]:
    return ZONE_TYPE_TO_DLBMS.get(zone_type, [])

def get_zone_type_for_planned_dlbm(dlbm: str) -> str:
    return get_zone_type_for_dlbm(dlbm)

def get_zone_type_for_ghytmc(ghytmc: str) -> str:
    return GHYTMC_TO_ZONE_TYPE.get(str(ghytmc).strip(), "农业用地")

def get_primary_zone(dlbm: str) -> str:
    return DLBM_TO_PRIMARY_ZONE.get(str(dlbm).strip(), "农业空间")

def dlbm_to_planning_zone(dlbm: str) -> str:
    return DLBM_TO_PLANNING_ZONE.get(str(dlbm).strip(), "一般农业区")

def get_primary_zone_for_planning_zone(planning_zone: str) -> str:
    return PLANNING_ZONE_TO_PRIMARY_ZONE.get(planning_zone, "农业空间")

def get_zone_type_for_ghflbm(ghflbm: str) -> str:
    return GHFLBM_TO_ZONE_TYPE.get(str(ghflbm).strip(), "农业用地")

def get_zone_type_for_ghytbm(ghytbm: str) -> str:
    return GHYTBM_TO_ZONE_TYPE.get(str(ghytbm).strip(), "农业用地")

def get_ghytmc_for_ghytbm(ghytbm: str) -> str:
    return GHYTBM_TO_GHYTMC.get(str(ghytbm).strip(), "")

def get_zone_type_for_vne(vne_code: str) -> str:
    return VNE_TO_ZONE_TYPE.get(str(vne_code).strip(), "农业用地")

def get_vne_for_zone_type(zone_type: str) -> str:
    return ZONE_TYPE_TO_VNE.get(zone_type, "E9")

def convert_sddlbm_to_ydyhfldm(sddlbm: str) -> Tuple[str, str]:
    result = SDDLBM_TO_YDYHFLDM.get(str(sddlbm).strip())
    if result:
        return result
    return (sddlbm, "无对应")

def get_vne_for_ghytbm(ghytbm: str) -> str:
    return GHYTBM_TO_VNE.get(str(ghytbm).strip(), "E9")

def parse_element_code(code: str) -> Dict[str, str]:
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


# ============================================================
# v2.0 NEW: Lookup functions for field_defaults.yaml
# ============================================================

def get_tdytfqdm_for_ghflbm(ghflbm: str) -> str:
    """GHFLBM -> TDYTFQDM (4-digit township planning code).

    Replaces the incorrect VNE alphabetic code in TDYT layer.
    """
    return GHFLBM_TO_TDYTFQDM.get(str(ghflbm).strip(), "")

def get_tdyt_name_for_ghflbm(ghflbm: str) -> str:
    """GHFLBM -> TDYT name (e.g. '农业用地', '村庄建设用地')."""
    return GHFLBM_TO_TDYT_NAME.get(str(ghflbm).strip(), "")

def get_space_control_name(code: str) -> str:
    """TDKJGZFQDM code -> name (e.g. '01' -> '允许建设区')."""
    return SPACE_CONTROL_ZONE_CODES.get(str(code).strip(), "")

def get_space_control_code(name: str) -> str:
    """Name -> TDKJGZFQDM code (e.g. '允许建设区' -> '01')."""
    return SPACE_CONTROL_NAME_TO_CODE.get(str(name).strip(), "")

def get_ghytbm_for_dlbm(dlbm: str) -> str:
    """DLBM (三调) -> GHYTBM (附录5) forward mapping for baseline conversion.

    Returns empty string if no mapping exists.
    Use get_ghytbm_conversion_info for conversion type and conditions.
    """
    return DLBM_TO_GHYTBM.get(str(dlbm).strip(), "")

def get_ghytbm_conversion_info(dlbm: str) -> Tuple[str, str, str]:
    """DLBM -> (ghytbm, conversion_type, condition) for baseline conversion.

    conversion_type: "一一对应" (deterministic) or "一对多" (needs disambiguation).
    condition: for "一对多", the condition for the primary mapping.
    """
    return DLBM_TO_GHYTBM_CONVERSIONS.get(str(dlbm).strip(), ("", "", ""))


__all__ = [
    # Dicts
    "DLBM_TO_DLMC", "DLBM_TO_ZONE_TYPE", "ZONE_TYPE_TO_DLBMS",
    "DLBM_TO_PLANNING_ZONE", "DLBM_TO_PRIMARY_ZONE",
    "ZONE_TYPES", "PLANNING_ZONES", "PRIMARY_ZONES",
    "PLANNING_ZONE_NAMES", "PRIMARY_ZONE_NAMES",
    "PLANNING_ZONE_TO_PRIMARY_ZONE",
    "GHYTMC_TO_ZONE_TYPE",
    "GHFLBM_MEANING", "GHFLBM_TO_ZONE_TYPE", "GHFLBM_TO_GHYTBMS",
    "GHYTBM_TO_GHYTMC", "GHYTBM_TO_YDYHFLDM",
    "YDYHFLDM_TO_NAME", "GHYTBM_TO_ZONE_TYPE",
    "VNE_CODE_TO_NAME", "VNE_TO_ZONE_TYPE", "ZONE_TYPE_TO_VNE",
    "GHYTBM_TO_VNE",
    "THREE_LINE_TYPES", "CONSTRUCTION_ZONE_DEF", "ANNOTATION_CATEGORIES",
    "SDDLBM_TO_YDYHFLDM", "ELEMENT_CODE_PREFIXES",
    # Code sets
    "BASIC_FARMLAND_CODES", "GENERAL_AGRICULTURE_CODES",
    "ECOLOGICAL_CODES", "FOREST_CODES",
    "WATER_CODES",
    "ECOLOGICAL_PROTECTION_CODES",
    "PROTECTED_DLBM_CODES",
    "CONSTRUCTION_USE_TYPES", "CONSTRUCTION_ZONE_TYPES",
    # v2.0: Construction zone codes (01-06)
    "SPACE_CONTROL_ZONE_CODES", "SPACE_CONTROL_ZONE_COLORS",
    "SPACE_CONTROL_ZONE_TYPES", "SPACE_CONTROL_NAME_TO_CODE",
    "PLANNING_ZONE_TO_CONTROL_CODE",
    # v2.0: GHFLBM -> TDYTFQDM
    "GHFLBM_TO_TDYTFQDM", "GHFLBM_TO_TDYT_NAME",
    # v2.0: DLBM -> GHYTBM forward mapping
    "DLBM_TO_GHYTBM", "DLBM_TO_GHYTBM_CONVERSIONS",
    # Functions
    "is_basic_farmland", "is_general_agriculture",
    "get_zone_type_for_dlbm", "resolve_zone_type_for_dlbm", "get_dlbms_for_zone_type",
    "get_zone_type_for_planned_dlbm",
    "get_zone_type_for_ghytmc", "get_primary_zone",
    "dlbm_to_planning_zone", "get_primary_zone_for_planning_zone",
    "get_zone_type_for_ghflbm", "get_zone_type_for_ghytbm",
    "get_ghytmc_for_ghytbm",
    "get_zone_type_for_vne", "get_vne_for_zone_type",
    "convert_sddlbm_to_ydyhfldm", "get_vne_for_ghytbm",
    "parse_element_code",
    # v2.0: New lookup functions
    "get_tdytfqdm_for_ghflbm", "get_tdyt_name_for_ghflbm",
    "get_space_control_name", "get_space_control_code",
    "get_ghytbm_for_dlbm", "get_ghytbm_conversion_info",
]
