"""Unified code→name lookup helper (v3.0).

This module handles ONLY forward, deterministic 1:1 code→name mappings
across all encoding systems defined in app.data.encodings.code_sets.

Key principles:
- Forward direction only (code → name)
- 1:1 deterministic mapping (no fuzzy, no multi-result)
- NEVER chains code→code mappings (e.g., dlbm→ghytbm→ghytmc)
- Helper for INTERNAL Python callers only — not exposed as an LLM tool.
  The legacy GIS LLM lookup tools were removed; code→name resolution now
  lives in this module only.

For name→code (reverse, fuzzy, multi-result) with code→code chains,
that is a different concern and is not handled here.
"""
from __future__ import annotations

from typing import Dict, Optional

from . import code_sets as cs


# ── 14 套 encoding 系统的 name_by_code 表 ──
# These are deterministic 1:1 forward mappings only.


def _invert(items: list) -> Dict[str, str]:
    """For system where code == name (just the list of codes is enough)."""
    return {x: x for x in items}


def _invert_unique(items: list) -> Dict[str, str]:
    return {x: x for x in set(items)}


def _ensure_5_tier_dict(cs_module) -> Dict[str, str]:
    """zone_types_appendix5 names dict (same-system zone_type name list)."""
    return _invert_unique(list(cs.ZONE_TYPES))


def _ensure_5_tier_dict_gbt(cs_module) -> Dict[str, str]:
    """zone_types_gbt50137 names dict."""
    return {
        "R": "居住用地", "A": "公共管理与公共服务用地", "B": "商业服务业设施用地",
        "M": "工业用地", "W": "物流仓储用地", "S": "道路与交通设施用地",
        "U": "公用设施用地", "G": "绿地与广场用地", "D": "特殊用地",
    }


def _ensure_town_dict(cs_module) -> Dict[str, str]:
    """zone_types_town names dict."""
    return {
        "居住用地": "居住用地",
        "公共设施用地": "公共设施用地",
        "生产设施用地": "生产设施用地",
        "仓储用地": "仓储用地",
        "对外交通用地": "对外交通用地",
        "道路广场用地": "道路广场用地",
        "工程设施用地": "工程设施用地",
        "绿地": "绿地",
        "水域和其他用地": "水域和其他用地",
    }


def _ensure_village_dict(cs_module) -> Dict[str, str]:
    """zone_types_village names dict."""
    return {
        "农业用地": "农业用地",
        "村庄建设用地": "村庄建设用地",
        "生态用地": "生态用地",
    }


NAME_BY_CODE: Dict[str, Dict[str, str]] = {
    "dlbm": cs.DLBM_TO_DLMC,
    "ghytbm": cs.GHYTBM_TO_GHYTMC,
    "vne_code": cs.VNE_CODE_TO_NAME,
    "ghflbm": cs.GHFLBM_MEANING,
    "space_control": cs.SPACE_CONTROL_ZONE_CODES,
    "zone_type_appendix5": _ensure_5_tier_dict(cs),
    "zone_type_gbt50137": _ensure_5_tier_dict_gbt(cs),
    "zone_type_town": _ensure_town_dict(cs),
    "zone_type_village": _ensure_village_dict(cs),
    "planning_zone": _invert(cs.PLANNING_ZONES),
    "primary_zone": _invert(cs.PRIMARY_ZONES),
    "three_categories": _invert(["农用地", "建设用地", "未利用地"]),
}


# ── Entity type → Chinese ──
# Moved from semantic.py _ENTITY_TYPE_CN
ENTITY_TYPE_CN: Dict[str, str] = {
    "Parcel": "地块",
    "Road": "道路",
    "ResidentialCluster": "居民点",
    "AdministrativeVillage": "行政村",
    "Village": "村庄",
    "Facility": "设施",
    "WaterBody": "水体",
    "Building": "建筑物",
    "ThreeZone": "三区",
    "ThreeLine": "三线管控区",
    "ControlLine": "控制线",
    "Zone": "分区",
    "Geofence": "地理围栏",
    "ConstructionBoundary": "建设边界",
    "ProtectionZone": "保护范围",
    "ZoneTarget": "分区目标",
    "FacilityTarget": "设施目标",
    "AxisTarget": "轴带目标",
    "RoadTarget": "道路目标",
    "PlannedParcel": "规划地块",
    "PlannedZone": "规划分区",
    "PlannedFacility": "规划设施",
    "PlannedRoad": "规划道路",
    "PlannedAxis": "规划轴带",
}


# ── Relation predicate → Chinese ──
# Moved from semantic.py _RELATION_PRED_CN
RELATION_PRED_CN: Dict[str, str] = {
    "sfTouches": "相邻",
    "touches": "相邻",
    "nearby": "邻近",
    "connected_via_road": "道路连接",
    "sfWithin": "位于",
    "within_zone": "位于",
    "located_in": "位于",
    "sfIntersects": "相交",
    "intersects": "相交",
    "sfContains": "包含",
    "contains": "包含",
    "designated_as": "被划定为",
    "derived_from": "源自",
    "serves": "服务于",
    "connects": "连接",
    "delineates": "界定了",
    "has_road": "有道路",
    "relates_to_anchor": "关联锚点",
    "has_zone": "有分区",
    "has_facility": "有设施",
    "has_axis": "有发展轴带",
    "has_planning_scope": "有规划范围",
}


def lookup_code_name(code_type: str, code_value: str) -> str:
    """Forward code→name lookup. Returns Chinese name or '' if not found.

    Args:
        code_type: One of:
            - 'dlbm', 'ghytbm', 'vne_code', 'ghflbm', 'space_control'
            - 'zone_type_appendix5', 'zone_type_gbt50137', 'zone_type_town', 'zone_type_village'
            - 'planning_zone', 'primary_zone', 'three_categories'
            - 'entity_type' (RDF rdf:type)
            - 'relation_pred' (RDF predicate)
        code_value: The code to look up (string).

    Returns:
        Chinese name string, or '' if not found.

    NEVER chains code→code (e.g., dlbm→ghytbm→ghytmc). If you need a related
    code in a different encoding system, query the KG via SPARQL — a different
    concern.
    """
    if not code_value:
        return ""
    code = str(code_value).strip()
    table = NAME_BY_CODE.get(code_type)
    if table:
        return table.get(code, "")
    if code_type == "entity_type":
        return ENTITY_TYPE_CN.get(code, code)
    if code_type == "relation_pred":
        return RELATION_PRED_CN.get(code, code)
    return ""


__all__ = [
    "NAME_BY_CODE",
    "ENTITY_TYPE_CN",
    "RELATION_PRED_CN",
    "lookup_code_name",
]