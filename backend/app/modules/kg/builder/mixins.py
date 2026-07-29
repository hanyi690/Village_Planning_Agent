"""Mixin classes for PlanningKG — replaces monkey-patching in base.py.

Each mixin bundles methods from a single layer, providing clean
inheritance for PlanningKG. Layer-specific implementations remain
in their respective layer*.py files.

Usage:
    class PlanningKG(Layer1Mixin, Layer2Mixin, Layer3Mixin,
                     Layer4Mixin, QueryMixin):
        ...
"""
from .registry import BuildContext
from .layer1 import (
    _add_village_entity,
    _add_parcel_relations, _parcel_uri_by_bsm_dlbm,
    _add_parcels, _add_water_bodies,
    _add_control_lines_from_typed, _add_planning_elements_from_typed,
    add_annotations, add_roads, add_terrain,
    _add_village_meta_from_bundle,
    _add_residential_clusters_from_typed, _add_facilities_from_typed,
    _add_facilities_from_annotations,
    _add_gis_layer_groups, _add_semantic_enrichment,
    _add_protection_polygons, _add_buildings,
    _add_terrain_entities, _add_boundaries,
    _add_natural_resource_zones, _add_cross_type_relations,
    _compute_cross_type_heuristic,
    )
from .layer3 import build_intent_layer, clear_intent_layer
from .layer4 import (
    _apply_planned_state,
    PlannedState, PlannedParcelEntry, PlannedZoneEntry,
    PlannedFacilityEntry, PlannedRoadEntry, PlannedAxisEntry,
    get_planned_parcels_in_zone,
    check_constraint_violations, compare_versions,
    get_effective_land_use, get_effective_area_ha,
    get_plan_changes,
)
from ..queries.sparql import (
    query, get_adjacency_map,
    get_parcel_count, get_triple_count, serialize, to_turtle, from_turtle,
    get_parcels_within_distance_of_entity, get_adjacent_parcels_with_length,
    get_connected_parcels, get_parcels_by_bsm_list, validate_intent, _is_in_protected_zone,
    get_constraint_coverage,
)


class Layer1Mixin:
    _add_village_entity = _add_village_entity
    _add_parcel_relations = _add_parcel_relations
    _parcel_uri_by_bsm_dlbm = _parcel_uri_by_bsm_dlbm
    _add_parcels = _add_parcels
    _add_water_bodies = _add_water_bodies
    _add_control_lines_from_typed = _add_control_lines_from_typed
    _add_planning_elements_from_typed = _add_planning_elements_from_typed
    add_annotations = add_annotations
    add_roads = add_roads
    add_terrain = add_terrain
    _add_village_meta_from_bundle = _add_village_meta_from_bundle
    _add_residential_clusters_from_typed = _add_residential_clusters_from_typed
    _add_facilities_from_typed = _add_facilities_from_typed
    _add_facilities_from_annotations = _add_facilities_from_annotations
    # v4.8: GIS layer sets + semantic enrichment
    _add_gis_layer_groups = _add_gis_layer_groups
    _add_semantic_enrichment = _add_semantic_enrichment
    # v4.8.1: additional bundle geometry groups + cross-type relations
    _add_protection_polygons = _add_protection_polygons
    _add_buildings = _add_buildings
    _add_terrain_entities = _add_terrain_entities
    _add_boundaries = _add_boundaries
    _add_natural_resource_zones = _add_natural_resource_zones
    _add_cross_type_relations = _add_cross_type_relations
    _compute_cross_type_heuristic = _compute_cross_type_heuristic


class Layer2Mixin:
    pass


class Layer3Mixin:
    build_intent_layer = build_intent_layer
    clear_intent_layer = clear_intent_layer


class Layer4Mixin:
    _apply_planned_state = _apply_planned_state
    get_effective_land_use = get_effective_land_use
    get_effective_area_ha = get_effective_area_ha
    get_plan_changes = get_plan_changes
    get_planned_parcels_in_zone = get_planned_parcels_in_zone
    check_constraint_violations = check_constraint_violations
    compare_versions = compare_versions


class QueryMixin:
    query = query
    get_adjacency_map = get_adjacency_map
    get_parcel_count = get_parcel_count
    get_triple_count = get_triple_count
    serialize = serialize
    to_turtle = to_turtle
    from_turtle = classmethod(from_turtle)
    get_parcels_within_distance_of_entity = get_parcels_within_distance_of_entity
    get_adjacent_parcels_with_length = get_adjacent_parcels_with_length
    get_connected_parcels = get_connected_parcels
    get_parcels_by_bsm_list = get_parcels_by_bsm_list
    validate_intent = validate_intent
    _is_in_protected_zone = _is_in_protected_zone
    get_constraint_coverage = get_constraint_coverage


__all__ = [
    "Layer1Mixin", "Layer2Mixin", "Layer3Mixin", "Layer4Mixin", "QueryMixin",
    "BuildContext",
]