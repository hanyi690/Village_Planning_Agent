"""Semantic enrichment derivation logic (moved from ontology.py and layer1.py).

Pure functions for deriving semantic labels, taxonomic parents, legal constraints,
and allowed operations from encoding values. Also contains GIS layer group
metadata helpers.

This module contains NO TBox declarations - those stay in ontology.py.
"""
from typing import Any, Dict, List

from app.utils.logger import get_logger

logger = get_logger(__name__)


CONTROL_CODE_TO_CONSTRAINT: Dict[str, str] = {
    "01": "allow_construction",
    "02": "restrict_construction",
    "03": "conditional_construction",
    "04": "forbid_construction",
    "05": "forbid_construction",
    "06": "forbid_construction",
}


def derive_semantic_label(dlbm: str) -> str:
    if not dlbm:
        return ""
    try:
        from app.modules.schema.encodings.code_sets import DLBM_TO_DLMC, resolve_zone_type_for_dlbm
        name = DLBM_TO_DLMC.get(str(dlbm).strip(), "")
        if name:
            return name
        return resolve_zone_type_for_dlbm(dlbm)
    except Exception:
        return ""


def derive_taxonomic_parent(dlbm: str) -> str:
    if not dlbm:
        return ""
    try:
        from app.modules.schema.encodings.code_sets import resolve_zone_type_for_dlbm
        return resolve_zone_type_for_dlbm(dlbm)
    except Exception:
        return ""


def derive_legal_constraint(planning_zone: str) -> str:
    if not planning_zone:
        return ""
    try:
        from app.modules.schema.encodings.code_sets import PLANNING_ZONE_TO_CONTROL_CODE
        code = PLANNING_ZONE_TO_CONTROL_CODE.get(str(planning_zone).strip(), "")
        return CONTROL_CODE_TO_CONSTRAINT.get(code, "")
    except Exception:
        return ""


def get_allowed_operations(ghytbm: str = "", planning_zone: str = "", control_code: str = "") -> List[str]:
    try:
        from app.modules.schema.encodings.dicts.loader import get_center
        d = get_center().get("allowed_operations").raw
        if ghytbm:
            entry = d.get("by_ghytbm", {}).get(str(ghytbm).strip())
            if entry:
                return entry.get("operations", [])
        if control_code:
            entry = d.get("by_control_code", {}).get(str(control_code).strip())
            if entry:
                return entry.get("operations", [])
        if planning_zone:
            entry = d.get("by_planning_zone", {}).get(str(planning_zone).strip())
            if entry:
                return entry.get("operations", [])
    except Exception:
        pass
    return []


def get_gis_layer_group_info(group_name: str) -> dict:
    try:
        from app.modules.schema.types.layer_registry import GIS_LAYER_REGISTRY
        for gis_type, entry in GIS_LAYER_REGISTRY.items():
            if _gis_type_matches_group(gis_type, group_name):
                return {
                    "gis_type_ref": gis_type,
                    "geometry_kind": entry.geometry_kind,
                    "description": entry.description,
                }
    except Exception:
        pass
    return {}


def _gis_type_matches_group(gis_type: str, group_name: str) -> bool:
    _GROUP_TO_GIS_TYPE = {
        "current_landuse": "landuse_current",
        "transport": "road",
        "water": "water",
        "facility": "current_facility",
        "protection": "farmland_protection",
        "hazard": "hazard_control_line",
        "hazard_point": "geological_hazard_points",
        "construction": "construction_zone",
        "admin": "boundary",
        "building": "current_building",
        "terrain": "contour_line",
        "natural_resource": "soil_type",
    }
    return _GROUP_TO_GIS_TYPE.get(group_name) == gis_type


def get_all_gis_layer_groups() -> list:
    return [
        "current_landuse", "transport", "water", "facility",
        "protection", "hazard", "hazard_point", "construction",
        "admin", "building", "terrain", "natural_resource",
    ]


REGULATION_TYPES = {
    "永久基本农田保护": {"category": "farmland_protection"},
    "生态保护红线": {"category": "ecological_protection"},
    "村庄建设边界": {"category": "construction_control"},
    "历史文化保护": {"category": "heritage_protection"},
    "村庄安全防灾": {"category": "safety_assurance"},
    "建设空间管制": {"category": "construction_spatial_control"},
}