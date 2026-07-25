"""Layer 3: PARSE intent (PlanIntent -> RDF subgraph).

All functions are module-level and assigned to PlanningKG in base.py.
"""
from typing import Any

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations

logger = get_logger(__name__)


def _add_structured_intent(self, intent: Any) -> None:
    """Build RDF subgraph from PlanIntent. Uses isinstance dispatch on targets."""
    from app.modules.schema.contracts.context_contracts import (
        PlanIntent, ZoneTarget, FacilityTarget, RoadTarget,
    )
    if not isinstance(intent, PlanIntent):
        logger.warning("_add_structured_intent requires PlanIntent, got %s", type(intent).__name__)
        return
    zc = fc = ac = 0
    for target in intent.targets:
        if isinstance(target, ZoneTarget):
            z_uri = PLN[f"zone_target_{target.land_use_code}"]
            self.g.add((z_uri, RDF.type, EntityTypes.ZoneTarget))
            self.g.add((z_uri, PLN.land_use_code, Literal(target.land_use_code)))
            self.g.add((z_uri, PLN.target_area_ha, Literal(target.target_area_ha, datatype=XSD.double)))
            if target.min_area_ha:
                self.g.add((z_uri, PLN.min_area_ha, Literal(target.min_area_ha, datatype=XSD.double)))
            if target.max_area_ha and target.max_area_ha < float("inf"):
                self.g.add((z_uri, PLN.max_area_ha, Literal(target.max_area_ha, datatype=XSD.double)))
            for lc in target.constraints:
                _add_location_constraint(self, z_uri, lc)
            self.g.add((PLN.village, PLN.has_zone, z_uri))
            zc += 1
        elif isinstance(target, FacilityTarget):
            f_uri = PLN[f"facility_target_{target.name}"]
            self.g.add((f_uri, RDF.type, EntityTypes.FacilityTarget))
            self.g.add((f_uri, PLN.name, Literal(target.name)))
            self.g.add((f_uri, PLN.facility_type, Literal(target.facility_type)))
            if target.min_area_sqm:
                self.g.add((f_uri, PLN.min_area_sqm, Literal(target.min_area_sqm, datatype=XSD.double)))
            if target.priority:
                self.g.add((f_uri, PLN.priority, Literal(target.priority, datatype=XSD.integer)))
            for lc in target.constraints:
                _add_location_constraint(self, f_uri, lc)
            self.g.add((PLN.village, PLN.has_facility, f_uri))
            fc += 1
        elif isinstance(target, RoadTarget):
            r_uri = PLN[f"road_target_{target.name}"]
            self.g.add((r_uri, RDF.type, EntityTypes.AxisTarget))
            self.g.add((r_uri, PLN.name, Literal(target.name)))
            self.g.add((r_uri, PLN.road_level, Literal(target.road_level)))
            if target.start_entity_uri:
                self.g.add((r_uri, PLN.start_entity, URIRef(target.start_entity_uri)))
            if target.end_entity_uri:
                self.g.add((r_uri, PLN.end_entity, URIRef(target.end_entity_uri)))
            if target.width_m:
                self.g.add((r_uri, PLN.buffer_width_m, Literal(target.width_m, datatype=XSD.double)))
            self.g.add((PLN.village, PLN.has_axis, r_uri))
            ac += 1
    for hc in intent.hard_constraints:
        c_uri = PLN[f"hard_constraint_{hash(hc.rule) & 0xFFFF}"]
        self.g.add((c_uri, RDF.type, PLN.Constraint))
        self.g.add((c_uri, PLN.constraint_id, Literal(str(c_uri))))
        self.g.add((c_uri, PLN.description, Literal(hc.rule)))
        self.g.add((c_uri, PLN.source, Literal(hc.source or "intent")))
        self.g.add((PLN.village, PLN.has_constraint, c_uri))
    logger.info("Added structured intent: %d zones, %d facilities, %d axes", zc, fc, ac)


def _add_location_constraint(self, source_uri, lc) -> None:
    """Add a LocationConstraint triple linking source entity to constraint target."""
    if not lc.entity_uri:
        return
    self.g.add((source_uri, PLN.location_constraint, URIRef(lc.entity_uri)))
    if lc.max_distance_m:
        self.g.add((source_uri, PLN.max_distance_m, Literal(lc.max_distance_m, datatype=XSD.double)))
