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
    """Derive a Chinese semantic label from DLBM (same-system code→name only).

    Wave A.1: cross-system zone_type fallback removed — BaseFacts only keep
    same-system facts (DLBM code → DLMC name). Returns "" if unknown.
    """
    if not dlbm:
        return ""
    try:
        from app.data.encodings.code_sets import DLBM_TO_DLMC
        return DLBM_TO_DLMC.get(str(dlbm).strip(), "")
    except Exception:
        return ""


def derive_taxonomic_parent(dlbm: str) -> str:
    """Wave A.1: removed. Cross-system DLBM→zone_type derivation is no longer
    performed in BaseFacts (现状地类只提供分类代码与名称). Returns ""."""
    return ""


def derive_legal_constraint(planning_zone: str) -> str:
    """Wave A.1: removed. Cross-system planning_zone→control_code derivation is
    no longer performed in BaseFacts. Returns ""."""
    return ""


def get_allowed_operations(ghytbm: str = "", planning_zone: str = "", control_code: str = "") -> List[str]:
    try:
        from app.data.encodings.dicts.loader import get_center
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
        from app.data.model.layer_registry import GIS_LAYER_REGISTRY
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


def add_gis_layer_groups(kg) -> None:
    from collections import Counter
    from rdflib import Literal, RDF, URIRef
    from ..ontology import PLN, EntityTypes, SemanticPredicates, GEOMETRY_POLYGON, GEOMETRY_LINE, GEOMETRY_POINT

    entity_type = EntityTypes.GisLayerSet
    sem_group = SemanticPredicates.semantic_group
    geom_kind = SemanticPredicates.geometry_kind
    has_label = SemanticPredicates.has_semantic_label
    contains_ent = SemanticPredicates.contains_entity
    gis_desc = SemanticPredicates.gis_description
    ent_count = SemanticPredicates.entity_count
    dom_label = SemanticPredicates.dominant_label

    group_count = 0
    for group_name in get_all_gis_layer_groups():
        members = []
        label_counter = Counter()

        for s, _, o in kg.g.triples((None, sem_group, Literal(group_name))):
            members.append(s)
            for _, _, label_obj in kg.g.triples((s, has_label, None)):
                label_counter[str(label_obj)] += 1

        if not members:
            continue

        group_info = get_gis_layer_group_info(group_name)
        group_geom_kind = group_info.get("geometry_kind", GEOMETRY_POLYGON)
        desc = group_info.get("description", group_name)

        if not group_info:
            for m in members:
                for _, _, gk in kg.g.triples((m, geom_kind, None)):
                    group_geom_kind = str(gk)
                    break
                break

        group_uri = PLN[f"GisLayerSet_{group_name}"]
        kg.g.add((group_uri, RDF.type, entity_type))
        kg.g.add((group_uri, sem_group, Literal(group_name)))
        kg.g.add((group_uri, geom_kind, Literal(group_geom_kind)))
        kg.g.add((group_uri, gis_desc, Literal(desc)))
        kg.g.add((group_uri, ent_count, Literal(len(members))))

        if label_counter:
            dom = label_counter.most_common(1)[0][0]
            kg.g.add((group_uri, dom_label, Literal(dom)))

        if label_counter:
            top3 = label_counter.most_common(3)
            dist_str = ", ".join(f"{lbl}({cnt})" for lbl, cnt in top3)
            enriched_desc = f"{desc} - {len(members)}个实体，主要: {dist_str}"
            kg.g.add((group_uri, PLN.gis_description_enriched, Literal(enriched_desc)))

        for m in members:
            kg.g.add((group_uri, contains_ent, m))

        group_count += 1
        logger.info("[GisLayerSet] %s: %d entities, dominant=%s",
                    group_name, len(members),
                    label_counter.most_common(1)[0][0] if label_counter else "N/A")

    if group_count:
        logger.info("Added %d GisLayerSet virtual entities", group_count)


def add_semantic_enrichment(kg) -> None:
    from rdflib import Literal, RDF
    from ..ontology import PLN, EntityTypes, SemanticPredicates

    legal_constraint = SemanticPredicates.legal_constraint

    count = 0
    for s, _, _ in kg.g.triples((None, RDF.type, EntityTypes.Zone)):
        name_lit = None
        for _, _, o in kg.g.triples((s, PLN.name, None)):
            name_lit = str(o)
            break
        if not name_lit:
            continue

        zone_constraint = ""
        if "有条件建设" in name_lit:
            zone_constraint = "conditional_construction"
        elif "禁止" in name_lit or "保护" in name_lit:
            zone_constraint = "forbid_construction"
        elif "限制" in name_lit:
            zone_constraint = "restrict_construction"
        elif "允许" in name_lit:
            zone_constraint = "allow_construction"

        if zone_constraint:
            kg.g.add((s, legal_constraint, Literal(zone_constraint)))
            count += 1

    if count:
        logger.info("Added %d zone-level legal_constraint triples", count)