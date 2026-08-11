"""Code sets - encoding-derived dicts and lookup functions.

All DLBM ↔ zone_type ↔ planning_zone mappings are derived from DictionaryCenter
YAML data. This module is the single runtime source for same-system code→name
lookups.

v5.2 (advisory_crosswalks isolation) changes:
- Cross-system mappings (DLBM→zone_type, DLBM→planning_zone, DLBM→primary_zone,
  GHYTBM→VNE, zone_type→planning_zone, planning_zone→primary_zone, …) and their
  lookup functions MOVED to app.modules.schema.advisory_crosswalks.
- This module keeps only same-system code→name sets and pure code sets:
  DLBM_TO_DLMC, GHYTBM_TO_GHYTMC, GHYTBM_TO_YDYHFLDM, YDYHFLDM_TO_NAME,
  VNE_CODE_TO_NAME, GHFLBM_MEANING, GHFLBM_TO_GHYTBMS, zone-name lists
  (ZONE_TYPES, PLANNING_ZONES, PRIMARY_ZONES, PLANNING_ZONE_NAMES,
  PRIMARY_ZONE_NAMES), pure code sets (BASIC_FARMLAND_CODES, ECOLOGICAL_CODES,
  …), and pure helpers (is_basic_farmland, is_general_agriculture,
  parse_element_code).

v3.0 (2026-07-30) changes:
- zone_type / planning_zone / primary_zone promoted to first-class encodings
- New encodings: three_categories, zone_types_appendix5, zone_types_gbt50137,
  zone_types_town, zone_types_village, planning_zones, primary_zones
- DLBM_TO_DLMC now only uses _gbt21010 (no longer merged 3 systems)
- PRIMARY_ZONE_NAMES corrected: 建设空间 → 城镇空间 (per 《若干意见》2019)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .dicts.loader import get_center


# ============================================================
# Encoding & code-set symbols - derived from DictionaryCenter
# ============================================================
#
# 14 套独立编码体系 (v3.0):
#   ── 现状层 ──
#   gbt21010:           GB/T 21010-2017 土地利用现状分类 (三调国标)
#   tugui:              广东省县级土地利用总体规划数据库标准 (土规)
#   appendix5:          广东省技术指南附录5 村庄规划用地分类 (原ghytbm)
#   ghflbm:             广东省土规数据库标准 规划分类编码
#   vne:                住建部《村庄规划用地分类指南》V/N/E分类
#   ydyhfldm:           自然资发〔2023〕234号 用地用海分类
#   ── 分区层 (v3.0 新增) ──
#   three_categories:   《土地管理法》"三大类" (农用地/建设用地/未利用地)
#   zone_types_appendix5: 广东省附录5 5-tier 功能类
#   zone_types_gbt50137:  GB 50137-2011 城市用地分类 (R/A/B/M/W/S/U/G/D)
#   zone_types_town:    GB 50188-2007 镇规划 8 大类
#   zone_types_village: 村土地利用规划编制技术导则 3-tier
#   planning_zones:     TD/T 1027-2010 附录B 6 zones (规划分区)
#   primary_zones:      三区三线 (生态空间/农业空间/城镇空间)
#
# 现状层 DLBM 使用 gbt21010 编码
# 规划层 GHYTBM 使用 appendix5 编码
# 派生映射在 mappings/ 目录，参见 dicts/mappings/ 与 advisory_crosswalks/yaml/
# ============================================================

_gbt21010 = get_center().encoding("gbt21010")
_tugui = get_center().encoding("tugui")
_appendix5 = get_center().encoding("appendix5")
_ghflbm = get_center().encoding("ghflbm")
_ydyhfldm = get_center().encoding("ydyhfldm")
_vne = get_center().encoding("vne")

# v3.0: 新增 7 套独立 encoding
_zone_types_appendix5 = get_center().encoding("zone_types_appendix5")
_planning_zones = get_center().encoding("planning_zones")
_primary_zones = get_center().encoding("primary_zones")

_tl = get_center().get("three_line_types")
_ec = get_center().get("element_codes")

# New YAML sources (v2.0)
_cz_codes = get_center().get("construction_zone_codes")

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
# v3.0: DLBM_TO_DLMC only uses gbt21010 (no longer merged from 3 systems)
DLBM_TO_DLMC: Dict[str, str] = _gbt21010.to_dict("code", "name")

# ── Zone hierarchy (v3.0: from encoding dicts, not derived from mappings) ──
ZONE_TYPES: List[str] = sorted(e.get("code", "") for e in _zone_types_appendix5.raw.get("classes", []))
PLANNING_ZONES: List[str] = [e.get("code", "") for e in _planning_zones.raw.get("classes", [])]
PRIMARY_ZONES: List[str] = [e.get("code", "") for e in _primary_zones.raw.get("classes", [])]

PLANNING_ZONE_NAMES: List[str] = PLANNING_ZONES
PRIMARY_ZONE_NAMES: List[str] = PRIMARY_ZONES

# ── GHFLBM / GHYTBM planning classification codes ──
GHFLBM_MEANING: Dict[str, str] = _ghflbm.to_dict("code", "name")

GHFLBM_TO_GHYTBMS: Dict[str, List[str]] = {}
for _entry in _ghflbm.raw.get("classes", []):
    _ghflbm_code = _entry.get("code", "")
    _ghytbms = _entry.get("ghytbms", [])
    if _ghflbm_code and _ghytbms:
        GHFLBM_TO_GHYTBMS[_ghflbm_code] = _ghytbms

GHYTBM_TO_GHYTMC: Dict[str, str] = _appendix5.to_dict("code", "name")
GHYTBM_TO_YDYHFLDM: Dict[str, str] = _appendix5.to_dict("code", "ydyhfldm")

YDYHFLDM_TO_NAME: Dict[str, str] = _ydyhfldm.to_dict("code", "name")

# ── V/N/E village planning land classification ──
VNE_CODE_TO_NAME: Dict[str, str] = _vne.to_dict("code", "name")

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


# ── Lookup functions ──

def is_basic_farmland(dlbm: str) -> bool:
    return str(dlbm).strip() in BASIC_FARMLAND_CODES

def is_general_agriculture(dlbm: str) -> bool:
    return str(dlbm).strip() in GENERAL_AGRICULTURE_CODES

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
# Current functional classification (DLBM → zone_type) — same-system
# ============================================================
# Wave A.1 Task 8: current-state descriptive classification of the DLBM
# encoding ("this parcel is currently agriculture/residential/ecological")
# is same-system and belongs here. Planning-zone derivation (DLBM→planning_zone,
# planning_zone→control_code, VNE→zone_type used as planning) stays in
# advisory_crosswalks and is legacy-gated.

def _mapping_default_to_dict(m) -> Dict[str, str]:
    """Extract {source: default} from a MappingTable.to_dict() result."""
    raw = m.to_dict()
    return {k: v[0] for k, v in raw.items()}


# DLBM and zone_type are different namespaces.  The old implementation read
# cross-system mapping tables here and silently filled ``农业用地`` for misses.
# Keep compatibility symbols for offline callers, but make the default chain
# fail closed; explicit crosswalk use belongs to advisory_crosswalks only.
DLBM_TO_ZONE_TYPE: Dict[str, str] = {}
DLBM_TO_ZONE_TYPE_CURRENT: Dict[str, str] = {}
ZONE_TYPE_TO_DLBMS: Dict[str, List[str]] = {}


def get_zone_type_for_dlbm(dlbm: str) -> str:
    """Return no zone type without an explicitly declared target namespace."""
    return ""


def get_dlbms_for_zone_type(zone_type: str) -> List[str]:
    """Reverse lookup: all DLBM codes whose current functional classification is zone_type."""
    return ZONE_TYPE_TO_DLBMS.get(zone_type, [])


# ============================================================
# Land-use name normalization (same-system)
# ============================================================
# Wave A.1 Task 8: LLM free-text → canonical GHYTMC land-use name. Same-system
# name normalization; no planning-zone derivation.

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
    """LLM 自由文本 → 规范化地类名称.

    匹配策略（按优先级）:
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
    canonical_names = set(GHYTBM_TO_GHYTMC.values())
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


__all__ = [
    # Dicts
    "DLBM_TO_DLMC",
    "ZONE_TYPES", "PLANNING_ZONES", "PRIMARY_ZONES",
    "PLANNING_ZONE_NAMES", "PRIMARY_ZONE_NAMES",
    "GHFLBM_MEANING", "GHFLBM_TO_GHYTBMS",
    "GHYTBM_TO_GHYTMC", "GHYTBM_TO_YDYHFLDM",
    "YDYHFLDM_TO_NAME",
    "VNE_CODE_TO_NAME",
    "THREE_LINE_TYPES", "CONSTRUCTION_ZONE_DEF", "ANNOTATION_CATEGORIES",
    "ELEMENT_CODE_PREFIXES",
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
    # Functions
    "is_basic_farmland", "is_general_agriculture",
    "parse_element_code",
    # Current functional classification (same-system)
    "DLBM_TO_ZONE_TYPE", "DLBM_TO_ZONE_TYPE_CURRENT", "ZONE_TYPE_TO_DLBMS",
    "get_zone_type_for_dlbm", "get_dlbms_for_zone_type",
    "normalize_landuse",
]
