"""Code sets - encoding-derived dicts and lookup functions.

All DLBM ↔ zone_type ↔ planning_zone mappings are derived from DictionaryCenter
YAML data. This module is the single runtime source for all encoding lookups.
Extracted from __init__.py to keep the barrel file focused on exports only.

v2.0 (2026-07-26) changes:
- PLANNING_ZONE_TO_PRIMARY_ZONE: from YAML (planning_zone_rules.yaml), not hardcoded
- SPACE_CONTROL_ZONE_CODES: from YAML (construction_zone_codes.yaml), not hardcoded
- New: DLBM_TO_GHYTBM forward mapping (from dlbm_to_ghytbm.yaml)
- New: GHFLBM_TO_TDYTFQDM mapping (from ghflbm_to_tdytfqdm.yaml)
- New: SPACE_CONTROL_ZONE_CODES from construction_zone_codes.yaml (01-06, replaces 510-540)
- New: PLANNING_ZONE_TO_CONTROL_CODE from construction_zone_codes.yaml
- Removed dead code: GHYTMC_TO_DLMC (identity), ECOLOGICAL_CONTROL_CODES (empty)
- Removed backward-compat aliases: FORESTRY_CODES (use FOREST_CODES),
  CONSTRUCTION_ZONE_TYPES (use CONSTRUCTION_USE_TYPES),
  SPACE_CONTROL_ZONE_TYPES (use SPACE_CONTROL_ZONE_CODES)
- Fixed: field_defaults lookups (ghflbm_to_code, ghflbm_to_name, space_control_code,
  space_control_name) now implemented
"""

from __future__ import annotations

import functools
from typing import Dict, List, Optional, Set, Tuple

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
_sddlbm = get_center().get_mapping("sddlbm_to_ydyhfldm")

# New YAML sources (v2.0)
_cz_codes = get_center().get("construction_zone_codes")
_ghflbm_tdyt = get_center().get_mapping("ghflbm_to_tdytfqdm")
_dlbm_ghytbm = get_center().get_mapping("dlbm_to_ghytbm")

# ── Code sets from tugui (土规标准定义的 categories) ──
BASIC_FARMLAND_CODES: Set[str] = _tugui.to_set("code", filter_tag="BASIC_FARMLAND")
GENERAL_AGRICULTURE_CODES: Set[str] = _tugui.to_set("code", filter_tag="GENERAL_AGRICULTURE")
ECOLOGICAL_CODES: Set[str] = _tugui.to_set("code", filter_tag="ECOLOGICAL")
FOREST_CODES: Set[str] = _tugui.to_set("code", filter_tag="FOREST")
WATER_CODES: Set[str] = _tugui.to_set("code", filter_tag="WATER")


ECOLOGICAL_PROTECTION_CODES: Set[str] = FOREST_CODES | WATER_CODES
PROTECTED_DLBM_CODES: Set[str] = BASIC_FARMLAND_CODES | GENERAL_AGRICULTURE_CODES | ECOLOGICAL_CODES

CONSTRUCTION_USE_TYPES: Set[str] = {"居住用地", "产业用地", "公共服务用地", "交通用地", "商业用地"}

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
# ⚠️ 启发规则，非确定性推导
# 同一 DLBM 可映射到不同 planning_zone（如 0301 乔木林地→林业发展区/生态保护区）。
# PARSE 应明确产出 planning_zone 判断；此映射仅作 ConstraintCompiler fallback。
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

# ── GHYTBM -> Planning zone (from YAML, replaces old hardcoded _GHYTBM_TO_PLANNING_ZONE) ──
_ghytbm_pz = get_center().get("ghytbm_to_planning_zone").raw
GHYTBM_TO_PLANNING_ZONE: Dict[str, str] = dict(
    _ghytbm_pz.get("ghytbm_to_planning_zone", {})
)
GHYTMC_TO_PLANNING_ZONE: Dict[str, str] = {
    GHYTBM_TO_GHYTMC.get(ghytbm, ""): pz
    for ghytbm, pz in GHYTBM_TO_PLANNING_ZONE.items()
    if ghytbm in GHYTBM_TO_GHYTMC
}

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
    _ghflbm = _entry.get("source", "")
    _targets = _entry.get("targets", [])
    _tdytfqdm = _targets[0].get("code", "") if _targets else ""
    _name = _targets[0].get("name", "") if _targets else ""
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
    _dlbm = _entry.get("source", "")
    _targets = _entry.get("targets", [])
    _default = _entry.get("default", "")
    _decision = _entry.get("decision", "auto")
    _ghytbm = _targets[0].get("code", "") if _targets else _default
    if _dlbm and _ghytbm:
        DLBM_TO_GHYTBM[_dlbm] = _ghytbm
        DLBM_TO_GHYTBM_CONVERSIONS[_dlbm] = (_ghytbm, _decision, "")


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
    """DLBM → planning_zone 启发式映射。

    从 YAML 加载 (ghytbm_to_planning_zone.yaml), 不再使用硬编码 fallback。
    PARSE 应明确产出 planning_zone 判断，此函数仅作 fallback。
    """
    dlbm_s = str(dlbm).strip()
    return DLBM_TO_PLANNING_ZONE.get(dlbm_s, "一般农业区")

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


# ============================================================
# Land-use name lookup + normalization (replaces vocabulary.py)
# ============================================================

_LANDUSE_ALIASES: Dict[str, str] = {
    "水田": "耕地", "旱地": "耕地", "水浇地": "耕地", "菜地": "耕地",
    "果园": "园地", "茶园": "园地", "橡胶园": "园地",
    "乔木林地": "商品林", "竹林地": "商品林", "灌木林地": "商品林",
    "有林地": "商品林", "其他林地": "商品林", "林地": "商品林",
    "生态林地": "生态林",
    "天然牧草地": "草地", "人工牧草地": "草地", "其他草地": "草地",
    "农村宅基地": "宅基地", "村庄": "宅基地", "住宅": "宅基地",
    "基础设施用地": "基础设施", "公用设施": "基础设施",
    "道路用地": "村内交通", "农村道路": "村内交通", "村道": "村内交通",
    "坑塘水面": "水域", "河流水面": "水域", "水库水面": "水域",
    "养殖坑塘": "水域",
    "沟渠": "水利设施用地", "水利设施": "水利设施用地",
    "设施农用地": "设施农用地",
    "工业用地": "经营性建设用地", "商业用地": "经营性建设用地",
    "产业用地": "经营性建设用地", "经营性": "经营性建设用地",
    "公共服务": "公共服务设施", "学校": "公共服务设施", "卫生所": "公共服务设施",
    "采矿用地": "采矿用地",
    "风景名胜": "风景名胜用地", "风景名胜用地": "风景名胜用地",
    "特殊用地": "特殊用地",
    "自然保留地": "自然保留地", "空闲地": "自然保留地",
    "城镇": "城镇用地",
    "对外交通": "对外交通",
    "景观绿化": "景观与绿化", "绿地": "景观与绿化",
    "商品林": "商品林", "生态林": "生态林",
    "园地": "园地", "耕地": "耕地", "草地": "草地", "水域": "水域",
}


def normalize_landuse(raw: str) -> Tuple[Optional[str], str]:
    """LLM 自由文本 → 规范化地类名称。

    匹配策略（按优先级）：
    1. 精确匹配 GHYTMC 规范名称
    2. 别名表匹配
    3. 字符串包含匹配
    4. 失配 → (None, 说明)

    Returns:
        (规范化名称 | None, 匹配说明)
    """
    raw = raw.strip()
    if not raw:
        return None, "空字符串"

    # 1. 精确匹配规范名称（GHYTMC 名称集合）
    canonical_names = set(GHYTMC_TO_ZONE_TYPE.keys())
    if raw in canonical_names:
        return raw, f"精确匹配: {raw}"

    # 2. 别名表匹配
    if raw in _LANDUSE_ALIASES:
        return _LANDUSE_ALIASES[raw], f"别名匹配: {raw} → {_LANDUSE_ALIASES[raw]}"

    # 3. 字符串包含匹配
    for alias, canonical in _LANDUSE_ALIASES.items():
        if alias in raw or raw in alias:
            return canonical, f"包含匹配: '{raw}' ⊂ '{alias}' → {canonical}"

    # 4. 尝试 DLBM_TO_DLMC 匹配
    for name in DLBM_TO_DLMC.values():
        if raw == name or name in raw or raw in name:
            return name, f"编码匹配: {raw} → {name}"

    return None, f"失配: '{raw}' 未在任何词表中找到匹配"


def get_planning_zone_from_landuse(landuse: str) -> str:
    """地类名称 → 规划分区的启发式映射。

    Args:
        landuse: 规范化地类名称（GHYTMC）。

    Returns:
        对应的规划分区名称。
    """
    for code, name in GHYTBM_TO_GHYTMC.items():
        if name == landuse and code in GHYTBM_TO_PLANNING_ZONE:
            return GHYTBM_TO_PLANNING_ZONE[code]
    return "一般农业区"


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
    "YDYHFLDM_TO_NAME", "GHYTBM_TO_ZONE_TYPE", "GHYTBM_TO_PLANNING_ZONE",
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
    "CONSTRUCTION_USE_TYPES",
    # v2.0: Construction zone codes (01-06)
    "SPACE_CONTROL_ZONE_CODES", "SPACE_CONTROL_ZONE_COLORS",
    "SPACE_CONTROL_NAME_TO_CODE",
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
    # Name normalization (replaces vocabulary.py)
    "normalize_landuse",
    "get_planning_zone_from_landuse",
]
