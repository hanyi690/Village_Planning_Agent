"""Layer 3: PARSE intent (SpatialPlanningIntent -> RDF subgraph + SemanticMemoryStore).

All functions are module-level and assigned to PlanningKG in base.py.

Intent virtual entities (ZoneTarget, FacilityTarget, AxisTarget, RoadTarget)
enter KG with rough geometry for spatial relation computation.
Entity/relation annotations stored in self.memory (SemanticMemoryStore).

Lifecycle: build_intent_layer creates L3 entities, clear_intent_layer removes them.
"""
from typing import Any

from rdflib import Literal, RDF
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes
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


def build_intent_layer(self, intent: Any) -> None:
    """Build L3 intent virtual entities from SpatialPlanningIntent.

    ZoneTarget, FacilityTarget, AxisTarget enter KG with rough geometry.
    Semantic annotations stored in self.memory (SemanticMemoryStore).
    """
    from app.modules.schema.contracts.parse_contracts import (
        SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget,
    )
    if not isinstance(intent, SpatialPlanningIntent):
        logger.warning("build_intent_layer requires SpatialPlanningIntent, got %s", type(intent).__name__)
        return

    zc = fc = ac = 0

    # ── Zone targets ──
    for zt in intent.zone_targets:
        z_uri = PLN[f"zone_target_{zt.land_use or zt.zone_id or zc}"]
        self.g.add((z_uri, RDF.type, EntityTypes.ZoneTarget))
        self.g.add((z_uri, PLN.land_use_code, Literal(zt.land_use)))
        self.g.add((z_uri, PLN.target_area_ha, Literal(zt.area_ratio, datatype=XSD.double)))
        if zt.dlbm:
            self.g.add((z_uri, PLN.dlbm, Literal(zt.dlbm)))
        if zt.vne_code:
            self.g.add((z_uri, PLN.vne_code, Literal(zt.vne_code)))
        self.g.add((z_uri, PLN.density, Literal(zt.density)))
        self.g.add((PLN.village, PLN.has_zone, z_uri))
        # Semantic memory annotation
        desc = f"规划目标: 将 {zt.area_ratio*100:.0f}% 的土地用于 {zt.land_use}"
        if zt.dlbm:
            desc += f" (地类编码: {zt.dlbm})"
        self.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(z_uri),
            entity_type="ZoneTarget",
            description=desc,
            source_text_refs=[intent.raw_text] if intent.raw_text else [],
        ))
        zc += 1

    # ── Facility targets ──
    for ft in intent.facilities:
        f_uri = PLN[f"facility_target_{ft.type or fc}"]
        self.g.add((f_uri, RDF.type, EntityTypes.FacilityTarget))
        self.g.add((f_uri, PLN.facility_type, Literal(ft.type)))
        self.g.add((f_uri, PLN.status, Literal(ft.status)))
        if ft.location_hint:
            self.g.add((f_uri, PLN.location_hint, Literal(ft.location_hint)))
        if ft.service_radius:
            self.g.add((f_uri, PLN.service_radius, Literal(ft.service_radius, datatype=XSD.integer)))
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
        a_uri = PLN[f"axis_target_{ax.reference_feature or ac}"]
        self.g.add((a_uri, RDF.type, EntityTypes.AxisTarget))
        if ax.reference_feature:
            self.g.add((a_uri, PLN.reference_feature, Literal(ax.reference_feature)))
        self.g.add((PLN.village, PLN.has_axis, a_uri))
        # Semantic memory annotation
        self.memory.add_entity_annotation(EntityAnnotation(
            entity_uri=str(a_uri),
            entity_type="AxisTarget",
            description=f"发展轴线: 沿{ax.reference_feature}方向",
            source_text_refs=[intent.raw_text] if intent.raw_text else [],
        ))
        ac += 1

    logger.info(
        "build_intent_layer: %d zones, %d facilities, %d axes",
        zc, fc, ac,
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