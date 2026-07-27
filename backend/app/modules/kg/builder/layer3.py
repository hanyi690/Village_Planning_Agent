"""Layer 3: PARSE intent (SpatialPlanningIntent -> RDF subgraph + SemanticMemoryStore).

All functions are module-level and assigned to PlanningKG in base.py.

Intent virtual entities (ZoneTarget, FacilityTarget, AxisTarget, RoadTarget)
enter KG with rough geometry and spatial anchoring triples for spatial
grounding. Entity/relation annotations stored in self.memory.

Lifecycle: build_intent_layer creates L3 entities, clear_intent_layer removes them.
"""
from typing import Any

from rdflib import Literal, RDF
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, EntityIdPolicy
from ..memory import EntityAnnotation

logger = get_logger(__name__)

# L3 entity types for clear_intent_layer
_L3_TYPES = {
    EntityTypes.ZoneTarget, EntityTypes.FacilityTarget,
    EntityTypes.AxisTarget, EntityTypes.RoadTarget,
}


def _add_structured_intent(self, intent: Any) -> None:
    """Build RDF subgraph from SpatialPlanningIntent (legacy name, delegates to build_intent_layer)."""
    self.build_intent_layer(intent)


def _serialize_bbox(bbox) -> str:
    """Serialize bbox tuple to comma-separated string for RDF literal."""
    if bbox is None:
        return ""
    try:
        return ",".join(str(round(v, 6)) for v in bbox)
    except (TypeError, ValueError):
        return ""


def build_intent_layer(self, intent: Any) -> None:
    """Build L3 intent virtual entities from SpatialPlanningIntent.

    ZoneTarget, FacilityTarget, AxisTarget, RoadTarget enter KG with
    spatial anchoring triples (candidate_bsm, excluded_bsm, candidate_bbox,
    spatial_hint, description). Semantic annotations in SemanticMemoryStore.
    """
    from app.modules.schema.contracts.parse_contracts import (
        SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget, RoadTarget,
    )
    if not isinstance(intent, SpatialPlanningIntent):
        logger.warning("build_intent_layer requires SpatialPlanningIntent, got %s", type(intent).__name__)
        return

    zc = fc = ac = rc = 0

    # ── Zone targets ──
    for zt in intent.zone_targets:
        target_id = zt.zone_id or zt.land_use or f"idx{zc}"
        z_uri = EntityIdPolicy.uri("zone_target", target_id)
        self.g.add((z_uri, RDF.type, EntityTypes.ZoneTarget))
        self.g.add((z_uri, PLN.target_id, Literal(target_id)))
        self.g.add((z_uri, PLN.land_use_code, Literal(zt.land_use)))
        self.g.add((z_uri, PLN.target_area_ha, Literal(zt.area_ratio, datatype=XSD.double)))
        if zt.planning_zone:
            self.g.add((z_uri, PLN.planning_zone, Literal(zt.planning_zone)))
        if zt.dlbm:
            self.g.add((z_uri, PLN.dlbm, Literal(zt.dlbm)))
        if zt.vne_code:
            self.g.add((z_uri, PLN.vne_code, Literal(zt.vne_code)))
        self.g.add((z_uri, PLN.density, Literal(zt.density)))
        self.g.add((PLN.village, PLN.has_zone, z_uri))
        # Spatial anchoring triples
        for bsm in zt.candidate_bsms:
            self.g.add((z_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        for bsm in zt.excluded_bsms:
            self.g.add((z_uri, PLN.excluded_bsm, PLN[f"parcel_{bsm}"]))
        bbox_str = _serialize_bbox(zt.candidate_bbox)
        if bbox_str:
            self.g.add((z_uri, PLN.candidate_bbox, Literal(bbox_str)))
        hint = zt.semantic.spatial_hint
        if hint:
            self.g.add((z_uri, PLN.spatial_hint, Literal(hint)))
        desc = zt.semantic.natural_language_description
        if desc:
            self.g.add((z_uri, PLN.description, Literal(desc)))
        # Semantic memory annotation
        mem_desc = f"规划目标: 将 {zt.area_ratio*100:.0f}% 的土地用于 {zt.land_use}"
        if zt.dlbm:
            mem_desc += f" (地类编码: {zt.dlbm})"
        self.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(z_uri),
            entity_type="ZoneTarget",
            description=mem_desc,
            source_text_refs=[intent.raw_text] if intent.raw_text else [],
        ))
        zc += 1

    # ── Facility targets ──
    for ft in intent.facilities:
        target_id = ft.type or f"idx{fc}"
        f_uri = EntityIdPolicy.uri("facility_target", target_id)
        self.g.add((f_uri, RDF.type, EntityTypes.FacilityTarget))
        self.g.add((f_uri, PLN.target_id, Literal(target_id)))
        self.g.add((f_uri, PLN.facility_type, Literal(ft.type)))
        self.g.add((f_uri, PLN.status, Literal(ft.status)))
        if ft.location_hint:
            self.g.add((f_uri, PLN.location_hint, Literal(ft.location_hint)))
        if ft.service_radius:
            self.g.add((f_uri, PLN.service_radius, Literal(ft.service_radius, datatype=XSD.integer)))
        if ft.direction:
            self.g.add((f_uri, PLN.direction, Literal(ft.direction)))
        # Spatial anchoring triples
        for bsm in ft.candidate_bsms:
            self.g.add((f_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        if ft.anchor_point:
            self.g.add((f_uri, PLN.anchor_point, Literal(f"{ft.anchor_point[0]},{ft.anchor_point[1]}")))
        hint = ft.semantic.spatial_hint
        if hint:
            self.g.add((f_uri, PLN.spatial_hint, Literal(hint)))
        self.g.add((PLN.village, PLN.has_facility, f_uri))
        # Semantic memory annotation
        svc = f"服务半径{ft.service_radius}m" if ft.service_radius else ""
        loc = f"位于{ft.location_hint}" if ft.location_hint else ""
        self.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(f_uri),
            entity_type="FacilityTarget",
            description=f"规划设施: {ft.type} ({ft.status}) {svc} {loc}".strip(),
            source_text_refs=[intent.raw_text] if intent.raw_text else [],
        ))
        fc += 1

    # ── Development axes ──
    for ax in intent.development_axes:
        target_id = ax.reference_feature or f"idx{ac}"
        a_uri = EntityIdPolicy.uri("axis_target", target_id)
        self.g.add((a_uri, RDF.type, EntityTypes.AxisTarget))
        self.g.add((a_uri, PLN.target_id, Literal(target_id)))
        if ax.reference_feature:
            self.g.add((a_uri, PLN.reference_feature, Literal(ax.reference_feature)))
        if ax.direction:
            self.g.add((a_uri, PLN.direction, Literal(ax.direction)))
        if ax.axis_type:
            self.g.add((a_uri, PLN.axis_type, Literal(ax.axis_type)))
        if ax.label:
            self.g.add((a_uri, PLN.label, Literal(ax.label)))
        # Spatial anchoring triples
        if ax.start_anchor:
            self.g.add((a_uri, PLN.anchor_point, Literal(f"{ax.start_anchor[0]},{ax.start_anchor[1]}")))
        if ax.end_anchor:
            self.g.add((a_uri, PLN.end_point, Literal(f"{ax.end_anchor[0]},{ax.end_anchor[1]}")))
        for bsm in ax.corridor_bsms:
            self.g.add((a_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        self.g.add((PLN.village, PLN.has_axis, a_uri))
        # Semantic memory annotation
        self.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(a_uri),
            entity_type="AxisTarget",
            description=f"发展轴线: 沿{ax.reference_feature}方向",
            source_text_refs=[intent.raw_text] if intent.raw_text else [],
        ))
        ac += 1

    # ── Road targets (NEW — fills road sub-task gap) ──
    for rt in intent.road_targets:
        target_id = rt.road_level or f"idx{rc}"
        r_uri = EntityIdPolicy.uri("road_target", target_id)
        self.g.add((r_uri, RDF.type, EntityTypes.RoadTarget))
        self.g.add((r_uri, PLN.target_id, Literal(target_id)))
        if rt.road_level:
            self.g.add((r_uri, PLN.road_level, Literal(rt.road_level)))
        if rt.width_m > 0:
            self.g.add((r_uri, PLN.width_m, Literal(rt.width_m, datatype=XSD.double)))
        for conn in rt.connects:
            self.g.add((r_uri, PLN.connects, Literal(conn)))
        # Spatial anchoring triples
        if rt.start_anchor:
            self.g.add((r_uri, PLN.anchor_point, Literal(f"{rt.start_anchor[0]},{rt.start_anchor[1]}")))
        if rt.end_anchor:
            self.g.add((r_uri, PLN.end_point, Literal(f"{rt.end_anchor[0]},{rt.end_anchor[1]}")))
        for bsm in rt.path_bsms:
            self.g.add((r_uri, PLN.candidate_bsm, PLN[f"parcel_{bsm}"]))
        hint = rt.semantic.spatial_hint
        if hint:
            self.g.add((r_uri, PLN.spatial_hint, Literal(hint)))
        self.g.add((PLN.village, PLN.has_road, r_uri))
        # Semantic memory annotation
        self.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(r_uri),
            entity_type="RoadTarget",
            description=f"规划道路: {rt.road_level} 宽{rt.width_m}m",
            source_text_refs=[intent.raw_text] if intent.raw_text else [],
        ))
        rc += 1

    # Raw planning text on village entity
    if intent.raw_text:
        self.g.add((PLN.village, PLN.raw_planning_text, Literal(intent.raw_text)))

    logger.info(
        "build_intent_layer: %d zones, %d facilities, %d axes, %d roads",
        zc, fc, ac, rc,
    )


def clear_intent_layer(self) -> None:
    """Remove all L3 intent virtual entities from the RDF graph.

    Called at end of planning session to clean up volatile L3 triples.
    """
    count = 0
    for t in _L3_TYPES:
        for s in list(self.g.subjects(RDF.type, t)):
            for p, o in self.g.predicate_objects(s):
                self.g.remove((s, p, o))
                count += 1
    if count:
        logger.info("clear_intent_layer: removed %d L3 triples", count)
