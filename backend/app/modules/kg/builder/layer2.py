"""Layer 2: constraint rules and indicators.

All functions are module-level and assigned to PlanningKG in base.py.
"""
from typing import Any, Dict, List, Optional

from rdflib import Literal, RDF
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations

logger = get_logger(__name__)


def _add_landuse_dist_from_blocks(self, blocks) -> Dict[str, float]:
    """Extract zone areas from LANDUSE_DIST ContextBlock. Returns {zone_type: area_ha}."""
    from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT
    for block in blocks:
        if getattr(block, "block_type", None) != CBT.LANDUSE_DIST:
            continue
        zone_areas = {}
        for entry in block.data.get("entries", []):
            zt = entry.get("zone_type", "")
            ah = entry.get("area_ha", 0)
            if zt and ah:
                zone_areas[zt] = zone_areas.get(zt, 0) + ah
        v = PLN.village
        constr = sum(e["area_ha"] for e in block.data.get("entries", [])
                     if e.get("zone_type") in ("居住用地", "产业用地", "公共服务"))
        if constr:
            self.g.add((v, PLN.constructionCap_ha, Literal(round(constr, 2), datatype=XSD.double)))
        farmland = sum(e["area_ha"] for e in block.data.get("entries", [])
                       if e.get("zone_type") in ("农业用地", "农田"))
        if farmland:
            self.g.add((v, PLN.farmlandMin_ha, Literal(round(farmland, 2), datatype=XSD.double)))
        return zone_areas
    return {}


def _add_constraints_from_blocks(self, blocks) -> None:
    """Build ProtectedZone + Constraint entities from CONSTRAINTS ContextBlock."""
    from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT
    count = 0
    for block in blocks:
        if getattr(block, "block_type", None) != CBT.CONSTRAINTS:
            continue
        for zone in block.data.get("zones", []):
            zone_type = zone.get("type", "")
            if not zone_type:
                continue
            category = {"永久基本农田": "farmland_protection",
                        "生态保护红线": "ecological_protection",
                        "历史文化保护": "heritage_protection",
                        "耕地保护目标": "cultivated_land_target",
                        "灾害防控": "hazard_control",
                        "洪涝防控": "flood_control",
                        "自然保护区": "nature_reserve"}.get(zone_type, zone_type)
            area_ha = zone.get("area_ha", 0)
            zone_uri = PLN[f"protection_{category}"]
            self.g.add((zone_uri, RDF.type, PLN.ThreeLine))
            self.g.add((zone_uri, PLN.name, Literal(zone_type)))
            if area_ha:
                self.g.add((zone_uri, PLN.area_target_ha, Literal(area_ha, datatype=XSD.double)))
            self.g.add((zone_uri, Relations.protects, PLN.village))
            self.g.add((PLN.village, PLN.has_zone, zone_uri))
            c_uri = PLN[f"constraint_{category}"]
            self.g.add((c_uri, RDF.type, PLN.Constraint))
            self.g.add((c_uri, PLN.constraint_id, Literal(f"{category}_protection")))
            self.g.add((c_uri, PLN.field, Literal(f"{category}_area_ha")))
            self.g.add((c_uri, PLN.operator, Literal(">=")))
            if area_ha:
                self.g.add((c_uri, PLN.value, Literal(area_ha, datatype=XSD.double)))
            self.g.add((c_uri, PLN.source, Literal("context_block")))
            self.g.add((PLN.village, PLN.has_constraint, c_uri))
            count += 1
    if count:
        logger.info("[PlanningKG] Added %d constraint zones from ContextBlock", count)