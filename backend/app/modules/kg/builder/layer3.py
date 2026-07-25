"""Layer 3: PARSE intent (SpatialPlanningIntent -> RDF subgraph + semantic store).

All functions are module-level and assigned to PlanningKG in base.py.

Structural data (land_use_code, area_ratio, density, etc.) -> RDF triples.
Semantic data (natural_language_description, spatial_hint, reasoning_trace)
-> self._semantic_store (JSON attachment, persisted alongside RDF but not as triples).
"""
from typing import Any

from rdflib import Literal, RDF
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes

logger = get_logger(__name__)


def _add_structured_intent(self, intent: Any) -> None:
    """Build RDF subgraph + semantic store from SpatialPlanningIntent.

    Structural fields (land_use_code, area_ratio, etc.) are written as RDF triples.
    Semantic fields (natural_language_description, spatial_hint, reasoning_trace)
    are stored in self._semantic_store as JSON attachment, NOT as RDF triples.
    """
    from app.modules.schema.contracts.parse_contracts import (
        SpatialPlanningIntent, ZoneTarget, FacilityTarget, AxisTarget,
    )
    if not isinstance(intent, SpatialPlanningIntent):
        logger.warning("_add_structured_intent requires SpatialPlanningIntent, got %s", type(intent).__name__)
        return

    # ── Intent entity ──
    intent_uri = PLN[f"intent_{intent.village_name or 'unnamed'}"]
    self.g.add((intent_uri, RDF.type, EntityTypes.PlanIntent))
    self.g.add((PLN.village, PLN.has_intent, intent_uri))
    self._semantic_store[str(intent_uri)] = {
        "raw_text": intent.raw_text or "",
        "reasoning_trace": intent.reasoning_trace or "",
    }

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
        # Semantic store (not RDF)
        if zt.semantic:
            self._semantic_store[str(z_uri)] = {
                "natural_language_description": zt.semantic.natural_language_description or "",
                "spatial_hint": zt.semantic.spatial_hint or "",
                "reasoning_trace": zt.semantic.reasoning_trace or "",
            }
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
        if ft.semantic:
            self._semantic_store[str(f_uri)] = {
                "natural_language_description": ft.semantic.natural_language_description or "",
                "spatial_hint": ft.semantic.spatial_hint or "",
                "reasoning_trace": ft.semantic.reasoning_trace or "",
            }
        fc += 1

    # ── Development axes ──
    for ax in intent.development_axes:
        a_uri = PLN[f"axis_target_{ax.reference_feature or ac}"]
        self.g.add((a_uri, RDF.type, EntityTypes.AxisTarget))
        if ax.reference_feature:
            self.g.add((a_uri, PLN.reference_feature, Literal(ax.reference_feature)))
        self.g.add((PLN.village, PLN.has_axis, a_uri))
        if ax.semantic:
            self._semantic_store[str(a_uri)] = {
                "natural_language_description": ax.semantic.natural_language_description or "",
                "spatial_hint": ax.semantic.spatial_hint or "",
                "reasoning_trace": ax.semantic.reasoning_trace or "",
            }
        ac += 1

    # Note: SpatialConstraints are NOT part of SpatialPlanningIntent.
    # They are passed separately to build_from_blocks and handled by the caller.
    # See intent_adapter (legacy) for the merge pattern.

    logger.info(
        "Added structured intent: %d zones, %d facilities, %d axes",
        zc, fc, ac,
    )