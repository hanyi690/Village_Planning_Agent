"""PlanningKG — 规划知识图谱构建器 (v4.4)

Skeleton class with build_from_blocks orchestrator + helper functions.
Layer-specific methods are imported from layer1.py, layer2.py, layer3.py, layer4.py, queries.py.

Usage:
    kg = PlanningKG()
    kg.build_from_blocks(blocks, bundle, parcel_relations, intent)
    result = kg.query("SELECT ?c WHERE { ?c a pln:Constraint }")
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from rdflib import Graph, Literal, RDF, URIRef
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, GEO, EntityTypes, Relations, FACILITY_TYPES, REGULATION_TYPES

from .layer1 import (
    _add_village_entity, _add_village_meta_from_blocks,
    _add_natural_villages_from_blocks, _add_facilities_from_blocks,
    _add_spatial_relations_from_blocks, _find_entity_by_name,
    _add_zone_adjacency_from_blocks, _add_terrain_from_blocks,
    _add_parcel_relations, _parcel_uri_by_bsm_dlbm,
    _add_parcels_typed, _add_infrastructure_from_typed,
    _add_control_lines_from_typed, _add_planning_elements_from_typed,
    _add_natural_features_from_typed, _add_designated_as_from_typed,
    _add_vne_categories, _add_three_zone_three_line,
    add_annotations, add_roads, add_terrain,
)
from .layer2 import _add_landuse_dist_from_blocks, _add_constraints_from_blocks
from .layer3 import _add_structured_intent, _add_location_constraint
from .layer4 import (
    _apply_plan_block, get_planned_parcels_in_zone,
    check_constraint_violations, compare_versions,
    get_effective_land_use, get_effective_area_ha,
    get_plan_changes, get_split_parcels, get_merge_parcels,
)
from .queries import (
    query, get_constraints, get_adjacency_map,
    get_parcel_count, get_triple_count, serialize, to_turtle, from_turtle,
    get_parcels_within_distance_of_entity, get_adjacent_parcels_with_length,
    get_connected_parcels, validate_intent, _is_in_protected_zone,
)

logger = get_logger(__name__)


# ── YAML-driven pattern loading (unchanged from v4.3) ──

def _load_constraint_patterns_from_yaml() -> List[Dict[str, Any]]:
    try:
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        loader = get_rule_loader()
        patterns = []
        f2o = {
            "construction_area_ha": ("construction_cap", "<="),
            "farmland_area_ha": ("farmland_min", ">="),
            "basic_farmland_area_ha": ("permanent_farmland_min", ">="),
            "ecological_redline_ha": ("ecological_redline_min", ">="),
            "public_service_area_ha": ("public_service", ">="),
            "infrastructure_area_ha": ("infrastructure", ">="),
            "homestead_per_household_sqm": ("homestead_per_household", "<="),
            "construction_per_capita_sqm": ("construction_per_capita", "<="),
        }
        f2mk = {
            "farmland_area_ha": "耕地保有量_公顷",
            "basic_farmland_area_ha": "永久基本农田_公顷",
            "construction_area_ha": "建设用地规模_公顷",
        }
        for ind in loader.planning_targets():
            cid_op = f2o.get(ind.field)
            if cid_op is None:
                continue
            constraint_id, operator = cid_op
            patterns.append({"metric_key": f2mk.get(ind.field, ""), "constraint_id": constraint_id,
                             "field": ind.field, "operator": operator,
                             "description": ind.description or ind.name})
        extra = [
            {"metric_key": "森林覆盖率_百分比", "constraint_id": "forest_coverage_min",
             "field": "forest_coverage_pct", "operator": ">=", "description": "森林覆盖率下限"},
            {"metric_key": "新增建设用地_公顷", "constraint_id": "construction_expansion",
             "field": "new_construction_ha", "operator": "=", "description": "新增建设用地规模"},
            {"metric_key": "林地保有量_公顷", "constraint_id": "forest_land_min",
             "field": "forest_land_ha", "operator": ">=", "description": "林地保有量下限"},
        ]
        patterns.extend(extra)
        return patterns
    except Exception as e:
        logger.warning("[KG] Failed to load constraint patterns from YAML: %s", e)
        return _FALLBACK_CONSTRAINT_PATTERNS


def _load_zone_patterns_from_yaml() -> Dict[str, Dict[str, Any]]:
    try:
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        loader = get_rule_loader()
        zone_patterns = {}
        g2z = {
            "农业用地": {"color": "#FFE4B5", "restrictions": ["禁止非农化", "禁止非粮化"]},
            "建设用地": {"color": "#FF6347", "restrictions": ["建设用地规模受控"]},
            "生态用地": {"color": "#2E8B57", "restrictions": ["禁止工业开发", "禁止城镇化"]},
        }
        for cat in loader.land_use_categories():
            major = cat.major_group
            if major in g2z and cat.name not in zone_patterns:
                zone_patterns[cat.name] = g2z[major].copy()
        _standard = {
            "农田保护区": {"color": "#FFE4B5", "restrictions": ["禁止非农化", "禁止非粮化"]},
            "村庄建设区": {"color": "#FF6347", "restrictions": ["建设用地规模受控"]},
            "生态保护区": {"color": "#2E8B57", "restrictions": ["禁止工业开发", "禁止城镇化"]},
            "一般农业区": {"color": "#98FB98", "restrictions": ["限制大规模非农建设"]},
        }
        for name, info in _standard.items():
            if name not in zone_patterns:
                zone_patterns[name] = info
        return zone_patterns
    except Exception as e:
        logger.warning("[KG] Failed to load zone patterns: %s", e)
        return _FALLBACK_ZONE_TYPE_PATTERNS


_FALLBACK_CONSTRAINT_PATTERNS = [
    {"metric_key": "建设用地规模_公顷", "constraint_id": "construction_cap", "field": "construction_area_ha", "operator": "<="},
    {"metric_key": "耕地保有量_公顷", "constraint_id": "farmland_min", "field": "farmland_area_ha", "operator": ">="},
    {"metric_key": "永久基本农田_公顷", "constraint_id": "permanent_farmland_min", "field": "permanent_farmland_ha", "operator": ">="},
    {"metric_key": "生态保护红线面积", "constraint_id": "ecological_redline_min", "field": "ecological_redline_ha", "operator": ">="},
    {"metric_key": "森林覆盖率_百分比", "constraint_id": "forest_coverage_min", "field": "forest_coverage_pct", "operator": ">="},
    {"metric_key": "新增建设用地_公顷", "constraint_id": "construction_expansion", "field": "new_construction_ha", "operator": "="},
    {"metric_key": "林地保有量_公顷", "constraint_id": "forest_land_min", "field": "forest_land_ha", "operator": ">="},
]

_FALLBACK_ZONE_TYPE_PATTERNS = {
    "农田保护区": {"color": "#FFE4B5", "restrictions": ["禁止非农化", "禁止非粮化"]},
    "村庄建设区": {"color": "#FF6347", "restrictions": ["建设用地规模受控"]},
    "生态保护区": {"color": "#2E8B57", "restrictions": ["禁止工业开发", "禁止城镇化"]},
    "一般农业区": {"color": "#98FB98", "restrictions": ["限制大规模非农建设"]},
}

CONSTRAINT_PATTERNS = _load_constraint_patterns_from_yaml()
ZONE_TYPE_PATTERNS = _load_zone_patterns_from_yaml()

INDICATOR_PATTERNS = [
    ("规划期末人口", "population", "人"),
    ("人均建设用地", "per_capita_construction_sqm", "m²/人"),
    ("村集体年收入", "village_income_yuan", "元"),
    ("带动就业", "employment_persons", "人"),
    ("常住人口", "resident_population", "人"),
]


@dataclass
class KGInputParcels:
    """Container for typed parcels consumed by KG builder.

    Callers should populate `parcels` directly from the Data layer
    (e.g., via DataCatalog.load_village_bundle or ingest_current_landuse).
    KG must not import from app.modules.data (architecture: Schema <- Data
    <- SpatialOps <- KG <- Agent; KG has no upward deps).
    """
    parcels: List[Any] = field(default_factory=list)


SEMANTIC_CONSTRAINT_MAP = {
    "max_construction_ha": {"constraint_id": "construction_cap", "field": "construction_area_ha", "operator": "<="},
    "min_farmland_protection_ha": {"constraint_id": "farmland_min", "field": "farmland_area_ha", "operator": ">="},
    "min_ecological_redline_ha": {"constraint_id": "ecological_redline_min", "field": "ecological_redline_ha", "operator": ">="},
    "planned_construction_ha": {"constraint_id": "construction_planned", "field": "construction_area_ha", "operator": "="},
    "planned_farmland_ha": {"constraint_id": "farmland_planned", "field": "farmland_area_ha", "operator": "="},
}


class PlanningKG:
    """规划知识图谱: 基于 RDFLib 的轻量级图存储。

    [v4.4] build_from_blocks 单入口，四层架构 + SpatialCognitiveUnit 形态层级。
    空间关系由 spatial_ops 外部计算后注入，KG 内部零几何计算库。
    """

    def __init__(self, village_name: str = ""):
        self.g = Graph()
        self.g.bind("pln", PLN)
        self.g.bind("geo", GEO)
        self.village_name = village_name
        self._parcel_count = 0

    # ── Main entry point ──

    def build_from_blocks(self, blocks=None, bundle=None, parcel_relations=None,
                          intent=None, plan_block=None):
        self.g = Graph()
        self.g.bind("pln", PLN)
        self.g.bind("geo", GEO)
        self._parcel_count = 0

        # Layer 1: static (zero shapely/geopandas)
        self._add_village_entity(bundle.village_name)
        self._add_village_meta_from_blocks(blocks)
        self._add_parcels_typed(bundle.polygons.landuse_current)
        self._add_parcel_relations(parcel_relations)
        self._add_infrastructure_from_typed(bundle.polygons.landuse_current)
        self.add_roads(bundle.lines.roads_current)
        self._add_constraints_from_blocks(blocks)
        self._add_control_lines_from_typed(bundle.points, bundle.polygons)
        self._add_planning_elements_from_typed(bundle.polygons)
        self._add_natural_features_from_typed(bundle.polygons, bundle.points)
        self._add_vne_categories()
        self._add_three_zone_three_line()
        self._add_natural_villages_from_blocks(blocks)
        self._add_facilities_from_blocks(blocks)
        self._add_spatial_relations_from_blocks(blocks)
        self._add_zone_adjacency_from_blocks(blocks)
        self._add_terrain_from_blocks(blocks)

        # Layer 2+3: intent -> RDF subgraph
        if intent is not None:
            self._add_structured_intent(intent)
            zone_areas = self._add_landuse_dist_from_blocks(blocks)
            if zone_areas:
                for zt, ah in zone_areas.items():
                    zu = PLN[f"zone_gis_{zt}"]
                    self.g.add((zu, RDF.type, PLN.Zone))
                    self.g.add((zu, PLN.name, Literal(zt)))
                    self.g.add((zu, PLN.area_target_ha, Literal(ah, datatype=XSD.double)))
                    self.g.add((PLN.village, PLN.has_zone, zu))

        # Layer 3: designated_as
        self._add_designated_as_from_typed(bundle.polygons.landuse_current)

        # Layer 4: planning state
        if plan_block is not None:
            self._apply_plan_block(plan_block)

        logger.info("[PlanningKG] Built from blocks: %d parcels, %d triples",
                    self._parcel_count, len(self.g))
        return self

    # ── Clone / cache ──

    def clone_static_layer(self):
        new_kg = PlanningKG(village_name=self.village_name)
        new_kg.g = Graph()
        new_kg.g.bind("pln", PLN)
        new_kg.g.bind("geo", GEO)
        l1_types = {
            EntityTypes.AdministrativeVillage, PLN.Parcel, EntityTypes.LandUseCategory,
            EntityTypes.ThreeZone, EntityTypes.ThreeLine, EntityTypes.Road,
            EntityTypes.WaterBody, EntityTypes.Facility, PLN.Constraint,
            PLN.ControlLine, EntityTypes.NaturalSettlement, PLN.Zone,
        }
        for s, p, o in self.g.triples((None, None, None)):
            is_l1 = any((s, RDF.type, t) in self.g for t in l1_types)
            if is_l1 or p in (PLN.adjacent_to, PLN.touches, PLN.nearby) or s == PLN.village:
                new_kg.g.add((s, p, o))
        new_kg._parcel_count = self._parcel_count
        return new_kg

    def print_summary(self):
        cs = self.get_constraints()
        print(f"\n=== Planning KG Summary ===")
        print(f"  Parcels: {self._parcel_count}")
        print(f"  Constraints: {len(cs)}")
        print(f"  Total triples: {len(self.g)}")
        for c in cs:
            print(f"    {c.get('id','?')}: {c.get('field','?')} {c.get('op','?')} {c.get('value','?')} (from: {c.get('source','?')})")


# Assign layer methods to PlanningKG class
# Layer 1
PlanningKG._add_village_entity = _add_village_entity
PlanningKG._add_village_meta_from_blocks = _add_village_meta_from_blocks
PlanningKG._add_natural_villages_from_blocks = _add_natural_villages_from_blocks
PlanningKG._add_facilities_from_blocks = _add_facilities_from_blocks
PlanningKG._add_spatial_relations_from_blocks = _add_spatial_relations_from_blocks
PlanningKG._find_entity_by_name = _find_entity_by_name
PlanningKG._add_zone_adjacency_from_blocks = _add_zone_adjacency_from_blocks
PlanningKG._add_terrain_from_blocks = _add_terrain_from_blocks
PlanningKG._add_parcel_relations = _add_parcel_relations
PlanningKG._parcel_uri_by_bsm_dlbm = _parcel_uri_by_bsm_dlbm
PlanningKG._add_parcels_typed = _add_parcels_typed
PlanningKG._add_infrastructure_from_typed = _add_infrastructure_from_typed
PlanningKG._add_control_lines_from_typed = _add_control_lines_from_typed
PlanningKG._add_planning_elements_from_typed = _add_planning_elements_from_typed
PlanningKG._add_natural_features_from_typed = _add_natural_features_from_typed
PlanningKG._add_designated_as_from_typed = _add_designated_as_from_typed
PlanningKG._add_vne_categories = _add_vne_categories
PlanningKG._add_three_zone_three_line = _add_three_zone_three_line
PlanningKG.add_annotations = add_annotations
PlanningKG.add_roads = add_roads
PlanningKG.add_terrain = add_terrain

# Layer 2
PlanningKG._add_landuse_dist_from_blocks = _add_landuse_dist_from_blocks
PlanningKG._add_constraints_from_blocks = _add_constraints_from_blocks

# Layer 3
PlanningKG._add_structured_intent = _add_structured_intent
PlanningKG._add_location_constraint = _add_location_constraint

# Layer 4
PlanningKG._apply_plan_block = _apply_plan_block
PlanningKG.get_effective_land_use = get_effective_land_use
PlanningKG.get_effective_area_ha = get_effective_area_ha
PlanningKG.get_plan_changes = get_plan_changes
PlanningKG.get_split_parcels = get_split_parcels
PlanningKG.get_merge_parcels = get_merge_parcels
PlanningKG.get_planned_parcels_in_zone = get_planned_parcels_in_zone
PlanningKG.check_constraint_violations = check_constraint_violations
PlanningKG.compare_versions = compare_versions

# Queries
PlanningKG.query = query
PlanningKG.get_constraints = get_constraints
PlanningKG.get_adjacency_map = get_adjacency_map
PlanningKG.get_parcel_count = get_parcel_count
PlanningKG.get_triple_count = get_triple_count
PlanningKG.serialize = serialize
PlanningKG.to_turtle = to_turtle
PlanningKG.from_turtle = classmethod(from_turtle)
PlanningKG.get_parcels_within_distance_of_entity = get_parcels_within_distance_of_entity
PlanningKG.get_adjacent_parcels_with_length = get_adjacent_parcels_with_length
PlanningKG.get_connected_parcels = get_connected_parcels
PlanningKG.validate_intent = validate_intent
PlanningKG._is_in_protected_zone = _is_in_protected_zone