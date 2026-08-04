"""Cross-system land-use mapping tables and lookup functions.

Isolated from ``app.modules.schema.encodings.code_sets`` so that cross-system
derivation (DLBM→zone_type, DLBM→planning_zone, GHYTBM→VNE, zone_type→planning_zone,
… ) does not leak into same-system code sets.

Same-system code→name sets (``DLBM_TO_DLMC``, ``GHYTBM_TO_GHYTMC``, …) stay in
``code_sets``; this module imports the few it depends on (schema-internal import).
"""

from __future__ import annotations

import functools
from typing import Dict, List, Optional, Tuple

from app.modules.schema.encodings.code_sets import (
    DLBM_TO_DLMC,
    GHYTBM_TO_GHYTMC,
    SPACE_CONTROL_NAME_TO_CODE,
    SPACE_CONTROL_ZONE_CODES,
)
from app.modules.schema.encodings.dicts.loader import get_center


def _mapping_default_to_dict(m) -> Dict[str, str]:
    """Extract {source: default} from a MappingTable.to_dict() result."""
    raw = m.to_dict()
    return {k: v[0] for k, v in raw.items()}


_appendix5 = get_center().encoding("appendix5")

# YAML sources
_cz_codes = get_center().get("construction_zone_codes")
_ghflbm_tdyt = get_center().get_mapping("ghflbm_to_tdytfqdm")
_dlbm_ghytbm = get_center().get_mapping("dlbm_to_ghytbm")

_dlbm_to_three_categories = get_center().get_mapping("gbt21010_to_three_categories")
_dlbm_to_zone_types_appendix5 = get_center().get_mapping("gbt21010_to_zone_types_appendix5")
_dlbm_to_planning_zones = get_center().get_mapping("gbt21010_to_planning_zones")
_dlbm_to_primary_zones = get_center().get_mapping("gbt21010_to_primary_zones")
_dlbm_to_zone_types_current = get_center().get_mapping("gbt21010_to_zone_types_current")
_ghflbm_to_zone_types_appendix5 = get_center().get_mapping("ghflbm_to_zone_types_appendix5")
_planning_zones_to_primary_zones = get_center().get_mapping("planning_zones_to_primary_zones")
_appendix5_to_zone_types_appendix5 = get_center().get_mapping("appendix5_to_zone_types_appendix5")
_vne_to_zone_types_appendix5 = get_center().get_mapping("vne_to_zone_types_appendix5")
_zone_type_to_planning_zones = get_center().get_mapping("zone_type_to_planning_zones")
_sddlbm = get_center().get_mapping("sddlbm_to_ydyhfldm")


# ── DLBM -> Three categories (《土地管理法》三大类) ──
DLBM_TO_THREE_CATEGORIES: Dict[str, str] = _mapping_default_to_dict(_dlbm_to_three_categories)

# ── DLBM -> Zone type (from mapping, not encoding dict) ──
DLBM_TO_ZONE_TYPE: Dict[str, str] = _mapping_default_to_dict(_dlbm_to_zone_types_appendix5)

# ── DLBM -> Planning zone (from mapping) ──
# ⚠️ 启发规则，非确定性推导
# 同一 DLBM 可映射到不同 planning_zone（如 0301 乔木林地→林业发展区/生态保护区）。
# PARSE 应明确产出 planning_zone 判断；此映射仅作 ConstraintCompiler fallback。
DLBM_TO_PLANNING_ZONE: Dict[str, str] = _mapping_default_to_dict(_dlbm_to_planning_zones)

# ── DLBM -> Primary zone (from mapping) ──
DLBM_TO_PRIMARY_ZONE: Dict[str, str] = _mapping_default_to_dict(_dlbm_to_primary_zones)

# ── DLBM -> Zone type（附录5 现状码，地块 dlbm_system=appendix5）──
# 数据全部来自 mappings/gbt21010_to_zone_types_current.yaml（DictionaryCenter 注册）。
# 旧附录5 字典（gbt21010_to_zone_types_appendix5）source 为 dlbm_ref 码（01-12），
# 与地块现状码（1100/1340/2121/3100…）数字冲突（dlbm_ref 1100=水域 vs 现状 1100=耕地），
# 因此现状码字典优先；未命中再回退旧字典。
DLBM_TO_ZONE_TYPE_CURRENT: Dict[str, str] = _mapping_default_to_dict(_dlbm_to_zone_types_current)

# ── zone_type（附录5 现状分类）→ planning_zone ──
ZONE_TYPE_TO_PLANNING_ZONE: Dict[str, str] = _mapping_default_to_dict(_zone_type_to_planning_zones)


def _zone_type_for_dlbm_with_fallback(dlbm: str) -> str:
    code = str(dlbm).strip()
    zt = DLBM_TO_ZONE_TYPE_CURRENT.get(code)
    if zt:
        return zt
    zt = DLBM_TO_ZONE_TYPE_CURRENT.get(code[:2])
    if zt:
        return zt
    return DLBM_TO_ZONE_TYPE.get(code, "农业用地")


ZONE_TYPE_TO_DLBMS: Dict[str, List[str]] = {}
for _code, _zt in DLBM_TO_ZONE_TYPE.items():
    ZONE_TYPE_TO_DLBMS.setdefault(_zt, []).append(_code)
for _code, _zt in DLBM_TO_ZONE_TYPE_CURRENT.items():
    ZONE_TYPE_TO_DLBMS.setdefault(_zt, []).append(_code)

# ── PLANNING_ZONE_TO_PRIMARY_ZONE (from mappings/planning_zones_to_primary_zones.yaml) ──
PLANNING_ZONE_TO_PRIMARY_ZONE: Dict[str, str] = _mapping_default_to_dict(_planning_zones_to_primary_zones)
if not PLANNING_ZONE_TO_PRIMARY_ZONE:
    # Fallback if YAML missing (should not happen in production)
    PLANNING_ZONE_TO_PRIMARY_ZONE = {
        "生态保护区": "生态空间",
        "生态控制区": "生态空间",
        "农田保护区": "农业空间",
        "一般农业区": "农业空间",
        "村庄建设区": "城镇空间",
        "林业发展区": "农业空间",
    }

# ── GHFLBM / GHYTBM planning classification codes ──
GHFLBM_TO_ZONE_TYPE: Dict[str, str] = _mapping_default_to_dict(_ghflbm_to_zone_types_appendix5)

GHYTBM_TO_ZONE_TYPE: Dict[str, str] = _mapping_default_to_dict(_appendix5_to_zone_types_appendix5)

# ── zone_type（附录5 现状分类）derived from GHYTBM_TO_ZONE_TYPE + GHYTBM_TO_GHYTMC ──
GHYTMC_TO_ZONE_TYPE: Dict[str, str] = {
    GHYTBM_TO_GHYTMC.get(ghytbm, ""): zt
    for ghytbm, zt in GHYTBM_TO_ZONE_TYPE.items()
    if GHYTBM_TO_GHYTMC.get(ghytbm, "")
}

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

# ── V/N/E village planning land classification ──
VNE_TO_ZONE_TYPE: Dict[str, str] = _mapping_default_to_dict(_vne_to_zone_types_appendix5)

ZONE_TYPE_TO_VNE: Dict[str, str] = {}
for _code, _zt in VNE_TO_ZONE_TYPE.items():
    if _zt and _code and _zt not in ZONE_TYPE_TO_VNE:
        ZONE_TYPE_TO_VNE[_zt] = _code

GHYTBM_TO_VNE: Dict[str, str] = _appendix5.to_dict("code", "vne")

# ── SDDLBM -> YDYHFLDM base conversion ──
SDDLBM_TO_YDYHFLDM: Dict[str, Tuple[str, str]] = _sddlbm.to_dict()

# ── planning_zone -> tdkjgzfqdm mapping ──
PLANNING_ZONE_TO_CONTROL_CODE: Dict[str, str] = dict(
    _cz_codes.raw.get("planning_zone_to_control_code", {})
)

# ── GHFLBM -> TDYTFQDM mapping (replaces VNE in TDYT layer) ──
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

# ── DLBM -> GHYTBM forward mapping (baseline conversion) ──
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

def get_zone_type_for_dlbm(dlbm: str) -> str:
    return _zone_type_for_dlbm_with_fallback(dlbm)


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
    """DLBM → planning_zone 启发式映射（现状码优先，两级查序）。

    查序（注释见 mappings/ 各文件头部）：
      1) 附录5 现状码（dlbm_system=appendix5，1100 耕地/2121 宅基地…）：
         gbt21010_to_zone_types_current.yaml 精确/前缀命中 →
         zone_type（zone_types_appendix5）→ planning_zone
         （zone_type_to_planning_zones.yaml）
      2) 未命中（2017/dlbm_ref 码）→ gbt21010_to_planning_zones.yaml
         （键为 dlbm_ref 码 01-12，土规体系）
      3) 兜底"一般农业区"
    现状码优先的原因：dlbm_ref 1100=水域 与 现状码 1100=耕地 数字冲突，
    必须先按现状码判定。
    PARSE 应明确产出 planning_zone 判断，此函数仅作 fallback。
    """
    dlbm_s = str(dlbm).strip()
    zt = DLBM_TO_ZONE_TYPE_CURRENT.get(dlbm_s) or DLBM_TO_ZONE_TYPE_CURRENT.get(dlbm_s[:2])
    if zt:
        pz = ZONE_TYPE_TO_PLANNING_ZONE.get(zt)
        if pz:
            return pz
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
    "DLBM_TO_ZONE_TYPE", "DLBM_TO_ZONE_TYPE_CURRENT",
    "DLBM_TO_PLANNING_ZONE", "DLBM_TO_PRIMARY_ZONE", "DLBM_TO_THREE_CATEGORIES",
    "ZONE_TYPE_TO_DLBMS", "ZONE_TYPE_TO_PLANNING_ZONE",
    "PLANNING_ZONE_TO_PRIMARY_ZONE", "PLANNING_ZONE_TO_CONTROL_CODE",
    "GHYTBM_TO_PLANNING_ZONE", "GHYTBM_TO_ZONE_TYPE", "GHYTBM_TO_VNE",
    "GHYTMC_TO_ZONE_TYPE", "GHYTMC_TO_PLANNING_ZONE",
    "VNE_TO_ZONE_TYPE", "ZONE_TYPE_TO_VNE",
    "DLBM_TO_GHYTBM", "DLBM_TO_GHYTBM_CONVERSIONS",
    "GHFLBM_TO_ZONE_TYPE", "GHFLBM_TO_TDYTFQDM", "GHFLBM_TO_TDYT_NAME",
    "SDDLBM_TO_YDYHFLDM",
    # Functions
    "get_zone_type_for_dlbm", "resolve_zone_type_for_dlbm", "get_dlbms_for_zone_type",
    "get_zone_type_for_planned_dlbm",
    "get_zone_type_for_ghytmc", "get_primary_zone",
    "dlbm_to_planning_zone", "get_primary_zone_for_planning_zone",
    "get_zone_type_for_ghflbm", "get_zone_type_for_ghytbm",
    "get_ghytmc_for_ghytbm",
    "get_zone_type_for_vne", "get_vne_for_zone_type",
    "convert_sddlbm_to_ydyhfldm", "get_vne_for_ghytbm",
    "get_tdytfqdm_for_ghflbm", "get_tdyt_name_for_ghflbm",
    "get_space_control_name", "get_space_control_code",
    "get_ghytbm_for_dlbm", "get_ghytbm_conversion_info",
    "normalize_landuse",
    "get_planning_zone_from_landuse",
]
