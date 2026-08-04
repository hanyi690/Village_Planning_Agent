"""Layer 1: static entity builders (from bundle morphology groups).

All functions are module-level, assigned to PlanningKG in base.py.
Zero shapely/geopandas dependency.

[v4.8] Adds three-dimension predicates (gis_type_ref/geometry_kind/semantic_group/
has_semantic_label) to each L1 entity, GisLayerSet virtual entities, and
semantic-enrichment triples (taxonomic_parent/legal_constraint/allowed_operations).
"""
from typing import Any, Dict, List

from rdflib import Literal, RDF, URIRef

from .registry import kg_builder, BuildContext
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import (
    PLN, PLN_NS, EntityTypes, Relations, EntityIdPolicy, SemanticPredicates,
    ProvenancePredicates,
    GEOMETRY_POLYGON, GEOMETRY_LINE, GEOMETRY_POINT, GEOMETRY_RASTER,
    GEO,
)
from .enrichment import (
    get_gis_layer_group_info, get_all_gis_layer_groups,
)

# Predicate shortcuts (from SemanticPredicates class)
gis_type_ref = SemanticPredicates.gis_type_ref
geometry_kind = SemanticPredicates.geometry_kind
semantic_group = SemanticPredicates.semantic_group
has_semantic_label = SemanticPredicates.has_semantic_label
contains_entity = SemanticPredicates.contains_entity
gis_description = SemanticPredicates.gis_description
entity_count = SemanticPredicates.entity_count
dominant_label = SemanticPredicates.dominant_label
taxonomic_parent = SemanticPredicates.taxonomic_parent
legal_constraint = SemanticPredicates.legal_constraint
allowed_operations = SemanticPredicates.allowed_operations

logger = get_logger(__name__)


# ── Semantic-layer derivation helpers (v4.8) ───────────────────────────


def _derive_semantic_label(dlbm: str) -> str:
    """Derive a Chinese semantic label from DLBM (same-system code→name only).

    Wave A.1: cross-system zone_type fallback removed.
    """
    if not dlbm:
        return ""
    try:
        from app.modules.schema.encodings.code_sets import DLBM_TO_DLMC
        return DLBM_TO_DLMC.get(str(dlbm).strip(), "")
    except Exception:
        return ""


def _derive_taxonomic_parent(dlbm: str) -> str:
    """Wave A.1: removed — cross-system DLBM→zone_type no longer in BaseFacts."""
    return ""


def _derive_legal_constraint(planning_zone: str) -> str:
    """Wave A.1: removed — cross-system planning_zone→control_code no longer
    in BaseFacts."""
    return ""


_CONTROL_CODE_TO_CONSTRAINT: Dict[str, str] = {
    "01": "allow_construction",
    "02": "restrict_construction",
    "03": "conditional_construction",
    "04": "forbid_construction",
    "05": "forbid_construction",   # 永久基本农田保护区
    "06": "forbid_construction",   # 生态保护红线区
}


def _get_allowed_operations(ghytbm: str = "", planning_zone: str = "", control_code: str = "") -> List[str]:
    """Look up allowed operations from allowed_operations.yaml.

    Priority: ghytbm (most specific) > control_code > planning_zone (coarsest).
    Returns a list of operation strings (subset of create/split/merge/modify/reclassify).
    """
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


def _add_village_entity(self, village_name: str) -> None:
    v = PLN.village
    self.g.add((v, RDF.type, EntityTypes.AdministrativeVillage))
    self.g.add((v, PLN.name, Literal(village_name or "unknown")))


def _add_parcel_relations(self, relations) -> None:
    from app.modules.spatial_ops.geometry import ParcelRelations
    if not relations or not isinstance(relations, ParcelRelations):
        return
    count = 0
    for t in relations.touches:
        a = _parcel_uri_by_bsm_dlbm(self, t.bsm_a, t.dlbm_a)
        b = _parcel_uri_by_bsm_dlbm(self, t.bsm_b, t.dlbm_b)
        if a and b:
            self.g.add((a, Relations.sfTouches, b))
            self.g.add((b, Relations.sfTouches, a))
            if t.shared_boundary_length_m:
                self.g.add((a, PLN.shared_boundary_length, Literal(t.shared_boundary_length_m, datatype=XSD.double)))
                self.g.add((b, PLN.shared_boundary_length, Literal(t.shared_boundary_length_m, datatype=XSD.double)))
            count += 1
    for n in relations.nearby:
        a = _parcel_uri_by_bsm_dlbm(self, n.bsm_a, n.dlbm_a)
        b = _parcel_uri_by_bsm_dlbm(self, n.bsm_b, n.dlbm_b)
        if a and b:
            self.g.add((a, Relations.nearby, b))
            if n.centroid_distance_m:
                self.g.add((a, PLN.centroid_distance, Literal(n.centroid_distance_m, datatype=XSD.double)))
            count += 1
    for c in relations.connected:
        a = _parcel_uri_by_bsm_dlbm(self, c.bsm_a, "")
        b = _parcel_uri_by_bsm_dlbm(self, c.bsm_b, "")
        if a and b:
            self.g.add((a, Relations.connected_via_road, b))
            if c.road_length_m:
                self.g.add((a, PLN.road_segment_length, Literal(c.road_length_m, datatype=XSD.double)))
            if c.road_bsm:
                self.g.add((a, PLN.via_road, Literal(c.road_bsm)))
            count += 1

    # Cross-layer: parcel↔road intersects (via PLN.intersects)
    for pbsm, rbsm in relations.parcel_road_intersects:
        pu = _parcel_uri_by_bsm_dlbm(self, pbsm, "")
        ru = _road_uri_by_bsm(self, rbsm)
        if pu and ru:
            self.g.add((ru, Relations.sfIntersects, pu))
            self.g.add((pu, Relations.sfIntersects, ru))
            count += 1

    # Cross-layer: parcel↔water touches (via PLN.touches)
    for pbsm, wid in relations.parcel_water_touches:
        pu = _parcel_uri_by_bsm_dlbm(self, pbsm, "")
        wu = _entity_uri_by_bsm(self, EntityTypes.WaterBody, wid)
        if not wu:
            # some water features use non-BSM ids; fall back to name match
            for s in self.g.subjects(RDF.type, EntityTypes.WaterBody):
                for _, _, o in self.g.triples((s, PLN.name, Literal(wid))):
                    wu = s
                    break
                if wu:
                    break
        if pu and wu:
            self.g.add((pu, Relations.sfTouches, wu))
            self.g.add((wu, Relations.sfTouches, pu))
            count += 1

    if count:
        logger.info("Added %d parcel relations (incl. cross-layer)", count)


def _parcel_uri_by_bsm_dlbm(self, bsm: str, dlbm: str):
    for s, _, _ in self.g.triples((None, PLN.bsm, Literal(bsm))):
        if (s, RDF.type, EntityTypes.Parcel) not in self.g:
            continue
        return s
    return None


def _road_uri_by_bsm(self, bsm: str):
    """Find Road URI by BSM or name (fallback)."""
    for s in self.g.subjects(RDF.type, EntityTypes.Road):
        for _, _, o in self.g.triples((s, PLN.bsm, Literal(bsm))):
            return s
    # fallback: match by name (roads without BSM use name as id)
    for s in self.g.subjects(RDF.type, EntityTypes.Road):
        for _, _, o in self.g.triples((s, PLN.name, Literal(bsm))):
            return s
    return None


def _entity_uri_by_bsm(self, entity_type, bsm: str):
    """Find entity URI of given type matching BSM."""
    for s in self.g.subjects(RDF.type, entity_type):
        for _, _, o in self.g.triples((s, PLN.bsm, Literal(bsm))):
            return s
    return None


def _add_parcels(self, parcels) -> None:
    bsm_seq: dict = {}  # Track sequence per BSM for duplicate disambiguation
    for p in parcels:
        bsm = str(p.bsm).strip()
        dlbm = str(p.dlbm).strip()
        if not bsm:
            continue
        area = p.area_sqm or 0
        seq = bsm_seq.get(bsm, 0)
        pu = EntityIdPolicy.uri_with_seq("parcel", bsm, seq)
        bsm_seq[bsm] = seq + 1
        self.g.add((pu, RDF.type, EntityTypes.Parcel))
        self.g.add((pu, PLN.bsm, Literal(bsm)))
        self.g.add((pu, PLN.seq, Literal(seq, datatype=XSD.integer)))
        self.g.add((pu, PLN.dlbm, Literal(dlbm)))
        self.g.add((pu, PLN.area_sqm, Literal(area, datatype=XSD.double)))
        self.g.add((pu, PLN.area_ha, Literal(area / 10000, datatype=XSD.double)))

        # Raw bundle attributes - faithful storage, not derived
        dlmc = getattr(p, "name", "") or ""
        if dlmc:
            self.g.add((pu, PLN.dlmc, Literal(dlmc)))
        sddlbm = p.sddlbm or ""
        if sddlbm:
            self.g.add((pu, PLN.sddlbm, Literal(sddlbm)))
        ysdm = p.ysdm or ""
        if ysdm:
            self.g.add((pu, PLN.ysdm, Literal(ysdm)))
        dlbm_system = str(p.dlbm_system or "")
        if dlbm_system:
            self.g.add((pu, PLN.dlbm_system, Literal(dlbm_system)))

        # planning_zone / primary_zone — user-provided facts from Data layer
        # (NOT derived from DLBM; Wave A.1 removed cross-system derivation)
        pz = p.planning_zone or ""
        if pz:
            self.g.add((pu, PLN.planning_zone, Literal(pz)))
        prz = p.primary_zone or ""
        if prz:
            self.g.add((pu, PLN.primary_zone, Literal(prz)))

        # ── v4.8: three-dimension predicates + semantic label ──
        self.g.add((pu, gis_type_ref, Literal("landuse_current")))
        self.g.add((pu, geometry_kind, Literal(GEOMETRY_POLYGON)))
        self.g.add((pu, semantic_group, Literal("current_landuse")))
        label = _derive_semantic_label(dlbm)
        if label:
            self.g.add((pu, has_semantic_label, Literal(label)))

        # Wave A.1: taxonomic_parent / legal_constraint / allowed_operations are
        # cross-system derivations (DLBM→zone_type, planning_zone→control_code,
        # DLBM→GHYTBM). BaseFacts no longer derives them from current DLBM —
        # they are produced by the later planning pipeline (PARSE/GROUND/etc).

        # Centroid
        try:
            geo = p.geometry
            if geo and isinstance(geo, dict):
                gtype = geo.get("type", "")
                coords = geo.get("coordinates", None)
                if coords and gtype == "Polygon" and len(coords) > 0 and len(coords[0]) > 0:
                    ring = coords[0]
                    lon = sum(c[0] for c in ring) / len(ring)
                    lat = sum(c[1] for c in ring) / len(ring)
                    self.g.add((pu, PLN.lon, Literal(lon, datatype=XSD.double)))
                    self.g.add((pu, PLN.lat, Literal(lat, datatype=XSD.double)))
                elif coords and gtype == "MultiPolygon" and len(coords) > 0 and len(coords[0]) > 0 and len(coords[0][0]) > 0:
                    ring = coords[0][0]
                    lon = sum(c[0] for c in ring) / len(ring)
                    lat = sum(c[1] for c in ring) / len(ring)
                    self.g.add((pu, PLN.lon, Literal(lon, datatype=XSD.double)))
                    self.g.add((pu, PLN.lat, Literal(lat, datatype=XSD.double)))
        except Exception:
            pass

        self.g.add((pu, Relations.sfWithin, PLN.village))
        self._parcel_count += 1
        # ── v4.9: Encoding decision provenance ──
        mapping_prov = p.mapping_provenance or {}
        for field_name, prov in mapping_prov.items():
            if not isinstance(prov, dict):
                continue
            decided_by = prov.get("decided_by", "")
            if decided_by:
                self.g.add((pu, ProvenancePredicates.decided_by, Literal(decided_by)))
            confidence = prov.get("confidence", "")
            if confidence:
                self.g.add((pu, ProvenancePredicates.decision_confidence, Literal(confidence)))
            system = prov.get("system", "")
            if system:
                self.g.add((pu, ProvenancePredicates.decision_evidence, Literal(system)))
            warning = prov.get("warning", "")
            if warning:
                self.g.add((pu, ProvenancePredicates.mapping_basis, Literal(warning)))


@kg_builder("water", entity_type="WaterBody")
def _add_water_bodies(self, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    water_overlap = ctx.provenance.get("water_overlap", {})
    covered_bsms = set()
    for bsm_list in water_overlap.values():
        for b in bsm_list:
            covered_bsms.add(b)

    def _add_water_dims(uri, is_line_geom: bool):
        """Attach three-dimension predicates to a WaterBody entity."""
        self.g.add((uri, gis_type_ref, Literal("water")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE if is_line_geom else GEOMETRY_POLYGON)))
        self.g.add((uri, semantic_group, Literal("water")))
        self.g.add((uri, has_semantic_label, Literal("水域")))

    count = 0
    for i, w in enumerate(features):
        bsm = str(w.bsm).strip()
        ysdm = str(w.ysdm).strip()
        wid = bsm or f"water_poly_{i}"

        # Check if this water feature completely covers a 3100 parcel
        covered = water_overlap.get(wid, []) or water_overlap.get(bsm, [])
        geom = w.geometry
        is_line = isinstance(geom, dict) and geom.get("type") in ("LineString", "MultiLineString")

        if is_line:
            # Line water features: no dedup, use water_line_ prefix
            uri = EntityIdPolicy.uri("water_line", bsm or str(i) or f"line_{i}")
            EntityIdPolicy.attach_bsm(self.g, uri, bsm)
            self.g.add((uri, RDF.type, EntityTypes.WaterBody))
            name = getattr(w, "water_name", "") or f"溪流_{bsm or i}"
            self.g.add((uri, PLN.name, Literal(name)))
            self.g.add((uri, PLN.water_type, Literal("河流")))
            self.g.add((uri, Relations.sfWithin, PLN.village))
            _add_water_dims(uri, is_line_geom=True)
            count += 1
        elif covered:
            # Water polygon completely covers existing 3100 parcel(s)
            # Create WaterBody entity, link to covered parcels via derived_from
            uri = EntityIdPolicy.uri("water", bsm or f"overlap_{i}")
            EntityIdPolicy.attach_bsm(self.g, uri, bsm)
            self.g.add((uri, RDF.type, EntityTypes.WaterBody))
            name = getattr(w, "water_name", "") or f"水体_{bsm or i}"
            self.g.add((uri, PLN.name, Literal(name)))
            self.g.add((uri, PLN.water_type, Literal(getattr(w, "water_type", "") or "水域")))
            self.g.add((uri, Relations.sfWithin, PLN.village))
            for cbsm in covered:
                for s in self.g.subjects(PLN.bsm, Literal(cbsm)):
                    if (s, RDF.type, EntityTypes.Parcel) in self.g:
                        self.g.add((uri, Relations.derived_from, s))
            _add_water_dims(uri, is_line_geom=False)
            count += 1
        else:
            # Independent water polygon (no overlap with 3100 parcels)
            uri = EntityIdPolicy.uri("water", bsm or f"indep_{i}")
            EntityIdPolicy.attach_bsm(self.g, uri, bsm)
            self.g.add((uri, RDF.type, EntityTypes.WaterBody))
            name = getattr(w, "water_name", "") or f"水体_{bsm or i}"
            self.g.add((uri, PLN.name, Literal(name)))
            self.g.add((uri, PLN.water_type, Literal(getattr(w, "water_type", "") or "水域")))
            self.g.add((uri, Relations.sfWithin, PLN.village))
            _add_water_dims(uri, is_line_geom=False)
            count += 1

    if count:
        logger.info("Added %d water bodies (overlap: %d covered parcels)", count, len(covered_bsms))
    return {"count": count, "entity_type": "WaterBody"}


def _add_control_lines_from_typed(self, points_layer, polygons_layer) -> None:
    count = 0
    for p in points_layer.get("hazard_points") or []:
        bsm = str(p.bsm).strip()
        ysdm = str(p.ysdm).strip()
        name = getattr(p, "name", "") or f"hazard_{count}"
        if bsm:
            uri = EntityIdPolicy.uri("hazard", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("hazard", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.ControlLine))
        self.g.add((uri, PLN.name, Literal(str(name))))
        self.g.add((uri, PLN.source, Literal("geological_hazard")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        # ── v4.8.1: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("geological_hazard_points")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        self.g.add((uri, semantic_group, Literal("hazard_point")))
        if name:
            self.g.add((uri, has_semantic_label, Literal(str(name))))
        count += 1
    for item in polygons_layer.get("hazard_control_lines") or []:
        bsm = str(item.bsm).strip()
        ysdm = str(item.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("hazard_line", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("hazard_line", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.ControlLine))
        self.g.add((uri, PLN.name, Literal(f"灾害防控线_{bsm or count}")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        # ── v4.8: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("hazard_control_line")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        self.g.add((uri, semantic_group, Literal("hazard")))
        count += 1
    for item in polygons_layer.get("flood_control_lines") or []:
        bsm = str(item.bsm).strip()
        ysdm = str(item.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("flood_line", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("flood_line", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.ControlLine))
        self.g.add((uri, PLN.name, Literal(f"洪涝控制线_{bsm or count}")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        # ── v4.8: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("flood_control_line")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        self.g.add((uri, semantic_group, Literal("hazard")))
        count += 1
    # NOTE: construction_zone moved to L4 (PlannedZone) - see ingest_planned_state_from_geojson()
    if count:
        logger.info("Added %d control lines", count)


def _add_planning_elements_from_typed(self, polygons_layer) -> None:
    count = 0
    for z in polygons_layer.get("land_use_zones") or []:
        bsm = str(z.bsm).strip()
        ysdm = str(z.ysdm).strip()
        code = ysdm or getattr(z, "dlbm", "")  # getattr intentional: dlbm not on LandUseZone
        if bsm:
            uri = EntityIdPolicy.uri("tdyt", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("tdyt", ysdm or str(code), count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Zone))
        self.g.add((uri, PLN.name, Literal(f"TDYT_{code}")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        # ── v4.8: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("land_use_zone")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        self.g.add((uri, semantic_group, Literal("protection")))
        count += 1
    for item in polygons_layer.get("construction_ctrl_zones") or []:
        bsm = str(item.bsm).strip()
        ysdm = str(item.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("zone_jsydgzq", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("zone_jsydgzq", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Zone))
        self.g.add((uri, PLN.name, Literal("建设用地管制区")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        # ── v4.8.1: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("space_control_zone")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        self.g.add((uri, semantic_group, Literal("construction")))
        self.g.add((uri, has_semantic_label, Literal("建设用地管制区")))
        count += 1
    for _ in polygons_layer.get("planning_scope") if hasattr(polygons_layer, "get") else []:
        self.g.add((PLN.village, PLN.has_planning_scope, Literal(True)))
        count += 1
    if count:
        logger.info("Added %d planning elements", count)


def add_annotations(self, annotations: list):
    from app.modules.schema.types.spatial_types import CurrentFacility
    fc, vc = 0, 0
    for ann in annotations:
        cat = getattr(ann, "category", "") or ""
        if cat == "村名":
            text = getattr(ann, "text", "") or ""
            bsm = str(ann.bsm).strip()
            ysdm = str(ann.ysdm).strip()
            if text and hasattr(ann, "geometry"):
                coords = ann.geometry.get("coordinates", [0, 0])
                if bsm:
                    uri = EntityIdPolicy.uri("village_ann", bsm)
                else:
                    uri = EntityIdPolicy.fallback_uri("village_ann", ysdm, vc)
                EntityIdPolicy.attach_bsm(self.g, uri, bsm)
                self.g.add((uri, RDF.type, EntityTypes.PlaceRef))
                self.g.add((uri, PLN.name, Literal(text)))
                self.g.add((uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
                self.g.add((uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
                vc += 1
        elif cat == "现状设施点":
            extra = ann.model_extra or {}
            facility = CurrentFacility.from_annotation_feature(
                {"properties": extra, "geometry": ann.geometry}
            ) if ann.model_extra else None
            if facility is None:
                continue
            bsm = str(facility.bsm).strip()
            ysdm = str(facility.ysdm).strip()
            if bsm:
                fac_uri = EntityIdPolicy.uri("facility", bsm)
            else:
                fac_uri = EntityIdPolicy.fallback_uri("facility", ysdm, fc)
            EntityIdPolicy.attach_bsm(self.g, fac_uri, bsm)
            self.g.add((fac_uri, RDF.type, EntityTypes.Facility))
            self.g.add((fac_uri, PLN.name, Literal(facility.facility_name or "unknown")))
            self.g.add((fac_uri, PLN.facility_type, Literal(facility.facility_type or "公共服务")))
            if hasattr(facility, "geometry"):
                coords = facility.geometry.get("coordinates", [0, 0])
                self.g.add((fac_uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
                self.g.add((fac_uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
            self.g.add((fac_uri, Relations.serves, Literal(facility.category or "public_service")))
            self.g.add((fac_uri, Relations.sfWithin, PLN.village))
            self.g.add((PLN.village, PLN.has_facility, fac_uri))
            fc += 1
    if fc or vc:
        logger.info("Annotations: %d facilities, %d villages", fc, vc)
    return self


@kg_builder("current_road", entity_type="Road")
def add_roads(self, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    count = 0
    for road in features:
        bsm = str(road.bsm).strip()
        ysdm = str(road.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("road", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("road", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Road))
        name = getattr(road, "road_name", "") or f"道路_{bsm or count}"
        self.g.add((uri, PLN.name, Literal(name)))
        length = getattr(road, "shape_length", "") or 0.0
        if length:
            self.g.add((uri, PLN.length, Literal(length, datatype=XSD.double)))
        self.g.add((uri, PLN.road_level, Literal(getattr(road, "road_level", "") or "村道")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((PLN.village, Relations.connects, uri))
        # ── v4.8: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("road")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE)))
        self.g.add((uri, semantic_group, Literal("transport")))
        count += 1
    if count:
        logger.info("Added %d roads", count)
    return {"count": count, "entity_type": "Road"}


def add_terrain(self, terrain_analysis=None):
    if terrain_analysis is None:
        return self
    try:
        slope = getattr(terrain_analysis, "slope_area_pct", {}) or {}
        for k, v in slope.items():
            key = k.replace(">", "gt").replace("-", "_")
            self.g.add((PLN.village, PLN[f"slope_{key}_pct"], Literal(v, datatype=XSD.double)))
        suit = getattr(terrain_analysis, "suitability_area_pct", {}) or {}
        for k, v in suit.items():
            self.g.add((PLN.village, PLN[f"suitability_{k}_pct"], Literal(v, datatype=XSD.double)))
        logger.info("Added terrain: %d slope, %d suitability", len(slope), len(suit))
    except Exception as e:
        logger.warning("Terrain failed: %s", e)
    return self


def _add_village_meta_from_bundle(self, bundle) -> None:
    """Add village metadata from bundle.metadata (replaces _add_village_meta_from_blocks)."""
    v = PLN.village
    meta = getattr(bundle, 'metadata', None)
    if meta is None:
        return
    bbox = getattr(meta, 'bbox_wgs84', None)
    if bbox is not None:
        try:
            t = bbox.as_tuple()
            self.g.add((v, PLN.bbox_minx, Literal(t[0], datatype=XSD.double)))
            self.g.add((v, PLN.bbox_miny, Literal(t[1], datatype=XSD.double)))
            self.g.add((v, PLN.bbox_maxx, Literal(t[2], datatype=XSD.double)))
            self.g.add((v, PLN.bbox_maxy, Literal(t[3], datatype=XSD.double)))
        except Exception:
            pass


def _add_residential_clusters_from_typed(self, parcels, annotations=None) -> None:
    """Identify residential settlement clusters (居民点) from parcel data.

    In village planning, 居民点 = naturally formed residential clusters
    within the administrative village. These are derived by clustering
    residential parcels (DLBM starting with 07/21), NOT from annotation labels.

    Annotation points with category='村名' are neighboring village names
    for map orientation, not internal settlements.

    Clustering: parcels within 100m centroid distance are grouped.
    Each cluster becomes a ResidentialCluster with centroid = mean of member centroids.

    Annotation-based clusters (from add_annotations() with category='村名')
    take priority: if a cluster's centroid is within 150m of an existing
    annotation-based cluster, it is skipped.
    """
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel
    import math

    # Collect existing annotation-based cluster centroids for dedup
    existing_clusters = []
    for s in self.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
        name_lit = None
        lon_lit = None
        lat_lit = None
        for p, o in self.g.predicate_objects(s):
            pred = str(p).rsplit("/", 1)[-1] if "#" not in str(p) else str(p).split("#")[-1]
            if pred == "name":
                name_lit = str(o)
            elif pred == "lon":
                try:
                    lon_lit = float(o)
                except Exception:
                    pass
            elif pred == "lat":
                try:
                    lat_lit = float(o)
                except Exception:
                    pass
        if lon_lit is not None and lat_lit is not None:
            existing_clusters.append((name_lit or "", lon_lit, lat_lit))

    # Collect residential parcels (宅基地 2121, 公共服务 2122, 基础设施 2123)
    residential_codes = {"2121", "2122", "2123", "0702", "0701"}
    residential = []  # [(bsm, centroid_x, centroid_y), ...]
    for p in parcels:
        if not isinstance(p, CurrentLandUseParcel):
            continue
        dlbm = p.dlbm or ""
        if dlbm not in residential_codes:
            continue
        p_geom = p.geometry
        p_bsm = p.bsm
        if not p_geom or not p_bsm:
            continue
        c = _parcel_centroid(p_geom)
        if c:
            residential.append((p_bsm, c[0], c[1]))

    if not residential:
        logger.debug("No residential parcels found for settlement clustering")
        return

    # Simple distance-based clustering (100m ≈ 0.001 deg)
    threshold = 0.0015  # ~150m
    visited = [False] * len(residential)
    clusters = []  # [[(bsm, lon, lat), ...], ...]

    for i in range(len(residential)):
        if visited[i]:
            continue
        cluster = [residential[i]]
        visited[i] = True
        changed = True
        while changed:
            changed = False
            for j in range(len(residential)):
                if visited[j]:
                    continue
                # Check distance to any member of current cluster
                for _, cx, cy in cluster:
                    dx = residential[j][1] - cx
                    dy = residential[j][2] - cy
                    if dx * dx + dy * dy < threshold * threshold:
                        cluster.append(residential[j])
                        visited[j] = True
                        changed = True
                        break
        clusters.append(cluster)

    # Only keep clusters with >= 3 parcels (significant settlements)
    significant = [c for c in clusters if len(c) >= 3]

    seq = 0
    for cluster in significant:
        # Centroid = mean of member centroids
        mean_lon = sum(m[1] for m in cluster) / len(cluster)
        mean_lat = sum(m[2] for m in cluster) / len(cluster)

        # Skip if this cluster's centroid is near an existing annotation-based cluster
        is_near_existing = False
        for _, ex_lon, ex_lat in existing_clusters:
            dx = mean_lon - ex_lon
            dy = mean_lat - ex_lat
            if dx * dx + dy * dy < threshold * threshold:
                is_near_existing = True
                break
        if is_near_existing:
            seq += 1  # still increment seq to keep naming consistent
            continue

        name = f"居民点{seq + 1}"
        uri = EntityIdPolicy.fallback_uri("settlement", name, seq)
        self.g.add((uri, RDF.type, EntityTypes.ResidentialCluster))
        self.g.add((uri, PLN.name, Literal(name)))
        self.g.add((uri, PLN.lon, Literal(mean_lon)))
        self.g.add((uri, PLN.lat, Literal(mean_lat)))
        self.g.add((uri, Relations.sfWithin, PLN.village))

        # Link member parcels
        for bsm, _, _ in cluster:
            for s in self.g.subjects(PLN.bsm, Literal(bsm)):
                if (s, RDF.type, EntityTypes.Parcel) in self.g:
                    self.g.add((s, Relations.sfWithin, uri))

        seq += 1

    logger.info(
        "Identified %d residential settlements from %d residential parcels (%d clusters total)",
        len(significant), len(residential), len(clusters),
    )


def _parcel_centroid(geom: dict):
    """Quick centroid extraction from GeoJSON geometry (no shapely)."""
    try:
        gt = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if gt == "Polygon" and coords:
            ring = coords[0]  # outer ring
            if ring:
                n = len(ring)
                sx = sum(c[0] for c in ring)
                sy = sum(c[1] for c in ring)
                return (sx / n, sy / n)
        elif gt == "MultiPolygon" and coords:
            # Use first polygon's centroid
            ring = coords[0][0] if coords[0] else []
            if ring:
                n = len(ring)
                sx = sum(c[0] for c in ring)
                sy = sum(c[1] for c in ring)
                return (sx / n, sy / n)
    except Exception:
        pass
    return None


def _add_facilities_from_typed(self, facilities) -> None:
    """Create Facility entities from bundle.points.facilities_current."""
    from app.modules.schema.types.spatial_types import CurrentFacility
    count = 0
    for f in facilities:
        if not isinstance(f, CurrentFacility):
            continue
        name = getattr(f, "facility_name", "") or f"facility_{count}"
        bsm = str(f.bsm).strip()
        ysdm = str(f.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("facility", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("facility", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Facility))
        self.g.add((uri, PLN.name, Literal(name)))
        ftype = getattr(f, "facility_type", "") or '公共服务'
        self.g.add((uri, PLN.facility_type, Literal(ftype)))
        geom = f.geometry or {}
        coords = geom.get('coordinates', [0, 0]) if isinstance(geom, dict) else [0, 0]
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            self.g.add((uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
            self.g.add((uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((PLN.village, PLN.has_facility, uri))
        # ── v4.8: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("current_facility")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        self.g.add((uri, semantic_group, Literal("facility")))
        if name:
            self.g.add((uri, has_semantic_label, Literal(name)))
        count += 1
    if count:
        logger.info("Added %d facilities from typed parcels", count)


# 单字简称 -> 设施类型映射
_FACILITY_TEXT_MAP = {
    "篮": ("篮球场", "公共服务"),
    "污": ("污水处理设施", "基础设施"),
    "电": ("电力设施", "基础设施"),
    "垃": ("垃圾收集点", "基础设施"),
    "祠": ("祠堂", "公共服务"),
    "卫": ("卫生站", "公共服务"),
    "站": ("公交站", "基础设施"),
    "广": ("广场", "公共服务"),
    "健": ("健身设施", "公共服务"),
    "停": ("停车场", "基础设施"),
    "水": ("供水设施", "基础设施"),
    "小": ("小型设施", "公共服务"),
}


def _add_facilities_from_annotations(self, annotations) -> None:
    """Create Facility entities from annotation points with category=现状设施点.

    注记层里 category='现状设施点' 的点是设施的空间位置标注，
    应作为空间实体入 KG（而非仅作表达要素）。
    """
    count = 0
    for i, ann in enumerate(annotations):
        cat = getattr(ann, "category", "") or ""
        if cat != "现状设施点":
            continue

        text = getattr(ann, "text", "") or ""
        geom = ann.geometry
        if not geom or not isinstance(geom, dict):
            continue
        coords = geom.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue

        name, ftype = _FACILITY_TEXT_MAP.get(text, (text or f"设施_{i}", "公共服务"))
        uri = EntityIdPolicy.fallback_uri("facility", text or str(i), i)
        self.g.add((uri, RDF.type, EntityTypes.Facility))
        self.g.add((uri, PLN.name, Literal(name)))
        self.g.add((uri, PLN.facility_type, Literal(ftype)))
        self.g.add((uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
        self.g.add((uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((PLN.village, PLN.has_facility, uri))
        # ── v4.8: three-dimension predicates ──
        self.g.add((uri, gis_type_ref, Literal("current_facility")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        self.g.add((uri, semantic_group, Literal("facility")))
        if name:
            self.g.add((uri, has_semantic_label, Literal(name)))
        count += 1

    if count:
        logger.info("Added %d facilities from annotations", count)


# ============================================================
# v4.8.1 - Additional bundle geometry groups
# ============================================================


def _add_protection_polygons(self, polygons_layer) -> None:
    """Create Zone entities from protection polygons (farmland/ecological/historical/etc).

    These are constraint polygons that overlap parcels - critical for
    parcel-overlaps-protection-zone cross-type relations.
    """
    count = 0

    protection_groups = [
        ("farmland_protection", "永久基本农田", "farmland_protection", "forbid_construction"),
        ("ecological_redline", "生态保护红线", "ecological_protection", "forbid_construction"),
        ("historical_protection", "历史文化保护线", "historical_protection", "forbid_construction"),
        ("cultivated_land_target", "耕地保护目标", "cultivated_land_target", "restrict_construction"),
        ("urban_dev_boundary", "城镇开发边界", "urban_dev_boundary", "restrict_construction"),
        ("village_dev_boundary", "村庄建设边界", "village_dev_boundary", "allow_construction"),
        ("nature_reserves", "自然保护区", "nature_reserve", "forbid_construction"),
    ]

    for attr_name, label, ltype, constraint in protection_groups:
        for item in polygons_layer.get(attr_name) or []:
            bsm = str(item.bsm).strip()
            ysdm = str(item.ysdm).strip()
            if bsm:
                uri = EntityIdPolicy.uri(attr_name, bsm)
            else:
                uri = EntityIdPolicy.fallback_uri(attr_name, ysdm, count)
            EntityIdPolicy.attach_bsm(self.g, uri, bsm)
            self.g.add((uri, RDF.type, EntityTypes.Zone))
            self.g.add((uri, PLN.name, Literal(f"{label}_{bsm or count}")))
            self.g.add((uri, Relations.sfWithin, PLN.village))
            # Three-dimension predicates
            self.g.add((uri, gis_type_ref, Literal(ltype)))
            self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
            self.g.add((uri, semantic_group, Literal("protection")))
            self.g.add((uri, has_semantic_label, Literal(label)))
            # Semantic layer
            self.g.add((uri, legal_constraint, Literal(constraint)))
            self.g.add((uri, allowed_operations, Literal("verify_only")))
            count += 1

    if count:
        logger.info("Added %d protection polygons", count)


@kg_builder("dem", entity_type="RasterDataset")
def _add_dem_raster(self, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    """Create a RasterDataset entity for the DEM raster (bundle.rasters.dem).

    `features` is a single-element list `[dem_raster]` (RasterLayerGroup.dem
    is a scalar, but the registry wraps group values via _get_bundle_features
    which yields list items). Each raster carries path/crs/bounds/resolution.
    """
    count = 0
    for i, dem in enumerate(features):
        if dem is None:
            continue
        uri = EntityIdPolicy.uri("dem", f"dem_{i}")
        self.g.add((uri, RDF.type, EntityTypes.RasterDataset))
        self.g.add((uri, PLN.name, Literal("数字高程模型")))
        self.g.add((uri, gis_type_ref, Literal("dem")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_RASTER)))
        self.g.add((uri, semantic_group, Literal("terrain")))
        self.g.add((uri, has_semantic_label, Literal("DEM数字高程模型")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        path = getattr(dem, "path", "") or ""
        if path:
            self.g.add((uri, PLN.path, Literal(path)))
        crs = getattr(dem, "crs", "") or ""
        if crs:
            self.g.add((uri, PLN.crs, Literal(str(crs))))
        res = getattr(dem, "resolution", 0.0)
        if res:
            self.g.add((uri, PLN.resolution, Literal(float(res), datatype=XSD.double)))
        bounds = getattr(dem, "bounds", None)
        if bounds and isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            self.g.add((uri, PLN.bbox_minx, Literal(float(bounds[0]), datatype=XSD.double)))
            self.g.add((uri, PLN.bbox_miny, Literal(float(bounds[1]), datatype=XSD.double)))
            self.g.add((uri, PLN.bbox_maxx, Literal(float(bounds[2]), datatype=XSD.double)))
            self.g.add((uri, PLN.bbox_maxy, Literal(float(bounds[3]), datatype=XSD.double)))
        w = getattr(dem, "width", 0)
        h = getattr(dem, "height", 0)
        if w:
            self.g.add((uri, PLN.width, Literal(int(w), datatype=XSD.integer)))
        if h:
            self.g.add((uri, PLN.height, Literal(int(h), datatype=XSD.integer)))
        count += 1
    if count:
        logger.info("Added %d DEM raster entities", count)
    return {"count": count, "entity_type": "RasterDataset"}


@kg_builder("current_building", entity_type="Building")
def _add_buildings(self, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    """Create Facility entities from bundle.points.buildings."""
    count = 0
    for i, b in enumerate(features):
        bsm = str(b.bsm).strip()
        ysdm = str(b.ysdm).strip()
        name = f"建筑_{bsm or i}"
        if bsm:
            uri = EntityIdPolicy.uri("building", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("building", ysdm, i)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Facility))
        self.g.add((uri, PLN.name, Literal(name)))
        self.g.add((uri, PLN.facility_type, Literal("建筑")))
        geom = b.geometry or {}
        coords = geom.get("coordinates", [0, 0]) if isinstance(geom, dict) else [0, 0]
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            self.g.add((uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
            self.g.add((uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        # Three-dimension predicates
        self.g.add((uri, gis_type_ref, Literal("current_building")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        self.g.add((uri, semantic_group, Literal("building")))
        self.g.add((uri, has_semantic_label, Literal(name)))
        count += 1
    if count:
        logger.info("Added %d buildings", count)
    return {"count": count, "entity_type": "Building"}


def _add_terrain_entities(self, lines_layer, points_layer) -> None:
    """Create entities from contour lines and elevation points."""
    count = 0
    # Contour lines
    for i, c in enumerate(lines_layer.get("contour_lines") if hasattr(lines_layer, "get") else []):
        bsm = str(c.bsm).strip()
        ysdm = str(c.ysdm).strip()
        elev = c.elevation or ""
        if bsm:
            uri = EntityIdPolicy.uri("contour", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("contour", ysdm, i)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Road))  # morphologically a line
        self.g.add((uri, PLN.name, Literal(f"等高线_{elev or bsm or i}")))
        if elev:
            self.g.add((uri, PLN.elevation, Literal(str(elev))))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((uri, gis_type_ref, Literal("contour_line")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE)))
        self.g.add((uri, semantic_group, Literal("terrain")))
        self.g.add((uri, has_semantic_label, Literal(f"等高线{elev}m")))
        count += 1

    # Elevation points
    for i, ep in enumerate(points_layer.get("elevation_points") or []):
        bsm = str(ep.bsm).strip()
        ysdm = str(ep.ysdm).strip()
        elev = ep.elevation or getattr(ep, "height", "") or ""  # getattr intentional: height not on ElevationPoint
        geom = ep.geometry or {}
        coords = geom.get("coordinates", [0, 0]) if isinstance(geom, dict) else [0, 0]
        if bsm:
            uri = EntityIdPolicy.uri("elevpt", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("elevpt", ysdm, i)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Facility))  # morphologically a point
        self.g.add((uri, PLN.name, Literal(f"高程点_{elev or i}")))
        if elev:
            self.g.add((uri, PLN.elevation, Literal(str(elev))))
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            self.g.add((uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
            self.g.add((uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((uri, gis_type_ref, Literal("elevation_point")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        self.g.add((uri, semantic_group, Literal("terrain")))
        self.g.add((uri, has_semantic_label, Literal(f"高程{elev}m")))
        count += 1

    if count:
        logger.info("Added %d terrain entities (contours + elevation points)", count)


def _add_boundaries(self, polygons_layer, lines_layer) -> None:
    """Create boundary entities from admin_areas, planning_scope, admin_boundaries."""
    count = 0
    # Admin areas (polygon)
    for i, a in enumerate(polygons_layer.get("admin_areas") if hasattr(polygons_layer, "get") else []):
        bsm = str(a.bsm).strip()
        ysdm = str(a.ysdm).strip()
        name = f"行政区_{bsm or i}"
        if bsm:
            uri = EntityIdPolicy.uri("admin", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("admin", ysdm, i)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.AdministrativeVillage))
        self.g.add((uri, PLN.name, Literal(name)))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((uri, gis_type_ref, Literal("admin_area")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        self.g.add((uri, semantic_group, Literal("admin")))
        self.g.add((uri, has_semantic_label, Literal(name)))
        count += 1

    # Planning scope (polygon) - emit as entity, not just flag
    for i, ps in enumerate(polygons_layer.get("planning_scope") if hasattr(polygons_layer, "get") else []):
        bsm = str(ps.bsm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("scope", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("scope", "scope", i)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Zone))
        self.g.add((uri, PLN.name, Literal("规划范围")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((uri, gis_type_ref, Literal("planning_scope")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        self.g.add((uri, semantic_group, Literal("admin")))
        self.g.add((uri, has_semantic_label, Literal("规划范围")))
        self.g.add((PLN.village, PLN.has_planning_scope, Literal(True)))
        count += 1

    # Admin boundary lines
    for i, bl in enumerate(lines_layer.get("admin_boundaries") or []):
        bsm = str(bl.bsm).strip()
        ysdm = str(bl.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("adminline", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("adminline", ysdm, i)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Road))  # morphologically a line
        self.g.add((uri, PLN.name, Literal(f"行政界线_{bsm or i}")))
        self.g.add((uri, Relations.sfWithin, PLN.village))
        self.g.add((uri, gis_type_ref, Literal("admin_boundary_line")))
        self.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE)))
        self.g.add((uri, semantic_group, Literal("admin")))
        self.g.add((uri, has_semantic_label, Literal("行政界线")))
        count += 1

    if count:
        logger.info("Added %d boundary entities", count)


def _add_natural_resource_zones(self, polygons_layer) -> None:
    """Create Zone entities from natural resource polygons (soil/watershed/hydrogeology)."""
    count = 0
    nr_groups = [
        ("soil_types", "土壤类型", "soil_type"),
        ("soil_erosions", "土壤侵蚀", "soil_erosion"),
        ("watersheds", "流域", "watershed"),
        ("hydrogeology_zones", "水文地质分区", "hydrogeology_zone"),
    ]
    for attr_name, label, ltype in nr_groups:
        for i, item in enumerate(polygons_layer.get(attr_name) or []):
            bsm = str(item.bsm).strip()
            ysdm = str(item.ysdm).strip()
            if bsm:
                uri = EntityIdPolicy.uri(attr_name, bsm)
            else:
                uri = EntityIdPolicy.fallback_uri(attr_name, ysdm, i)
            EntityIdPolicy.attach_bsm(self.g, uri, bsm)
            self.g.add((uri, RDF.type, EntityTypes.Zone))
            self.g.add((uri, PLN.name, Literal(f"{label}_{bsm or i}")))
            self.g.add((uri, Relations.sfWithin, PLN.village))
            self.g.add((uri, gis_type_ref, Literal(ltype)))
            self.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
            self.g.add((uri, semantic_group, Literal("natural_resource")))
            self.g.add((uri, has_semantic_label, Literal(label)))
            count += 1
    if count:
        logger.info("Added %d natural resource zones", count)


def _add_cross_type_relations(self, cross_type_relations=None) -> None:
    """Add cross-type spatial relations (facility-in-parcel, road-intersects-parcel, parcel-intersects-protection).

    Uses v4.8.1 merged predicates:
      - located_in: point/line entity within a polygon (facility-in-parcel, building-in-parcel)
      - intersects: line-crosses-polygon or polygon-overlaps-polygon (road-intersects-parcel, parcel-intersects-protection)
      - contains: polygon bounds another (boundary-contains-parcel)

    These are pre-computed by spatial_ops (which has shapely/geopandas) and passed in.
    KG does zero geometry computation - it only materializes the provided relations as triples.

    Args:
        cross_type_relations: optional dict with keys:
            - "located_in": List of (subject_uri_str, object_uri_str) - point/line within polygon
            - "intersects": List of (subject_uri_str, object_uri_str, overlap_pct) - line-crosses or polygon-overlaps
            - "contains": List of (subject_uri_str, object_uri_str) - polygon bounds another
            If None, uses internal centroid-based heuristic (less accurate, no shapely).
    """
    if cross_type_relations is None:
        cross_type_relations = self._compute_cross_type_heuristic()

    count = 0
    skipped = 0

    def _entity_in_graph(uri):
        """Check if a URI appears as subject in any triple."""
        try:
            for _ in self.g.triples((uri, None, None)):
                return True
            return False
        except Exception:
            return False

    # located_in: facility/building/elevation within parcel
    for subj_str, obj_str in cross_type_relations.get("located_in", []):
        subj = _to_uri_safe(subj_str)
        obj = _to_uri_safe(obj_str)
        if subj and obj and _entity_in_graph(subj) and _entity_in_graph(obj):
            self.g.add((subj, Relations.sfWithin, obj))
            count += 1
        else:
            skipped += 1

    # intersects: road-crosses-parcel, parcel-overlaps-protection
    for item in cross_type_relations.get("intersects", []):
        subj_str, obj_str = item[0], item[1]
        overlap_pct = item[2] if len(item) > 2 else None
        subj = _to_uri_safe(subj_str)
        obj = _to_uri_safe(obj_str)
        if subj and obj and _entity_in_graph(subj) and _entity_in_graph(obj):
            self.g.add((subj, Relations.sfIntersects, obj))
            if overlap_pct:
                self.g.add((subj, SemanticPredicates.overlap_pct, Literal(float(overlap_pct), datatype=XSD.double)))
            count += 1
        else:
            skipped += 1

    # contains: boundary-contains-parcel
    for subj_str, obj_str in cross_type_relations.get("contains", []):
        subj = _to_uri_safe(subj_str)
        obj = _to_uri_safe(obj_str)
        if subj and obj and _entity_in_graph(subj) and _entity_in_graph(obj):
            self.g.add((subj, Relations.sfContains, obj))
            count += 1
        else:
            skipped += 1

    if count:
        logger.info("Added %d cross-type spatial relations (skipped %d)", count, skipped)


def _compute_cross_type_heuristic(self) -> dict:
    """Heuristic cross-type relation computation using centroid proximity (no shapely).

    This is a fallback when spatial_ops hasn't pre-computed relations. It uses
    parcel centroid (lon/lat) vs facility/building point coordinates for 'located_in'.
    For 'intersects' and 'contains', it requires external computation (returns empty).

    Returns:
        dict with "located_in", "intersects", "contains" lists.
    """
    located_in_relations = []

    # Collect parcel centroids
    parcel_centroids = []  # [(uri, lon, lat)]
    for s in self.g.subjects(RDF.type, EntityTypes.Parcel):
        lon = lat = None
        for _, _, o in self.g.triples((s, PLN.lon, None)):
            try:
                lon = float(o)
            except (ValueError, TypeError):
                pass
        for _, _, o in self.g.triples((s, PLN.lat, None)):
            try:
                lat = float(o)
            except (ValueError, TypeError):
                pass
        if lon is not None and lat is not None:
            parcel_centroids.append((s, lon, lat))

    # For each facility/building, find nearest parcel centroid as 'located_in' candidate
    for pt in self.g.subjects(RDF.type, EntityTypes.Facility):
        pt_lon = pt_lat = None
        for _, _, o in self.g.triples((pt, PLN.lon, None)):
            try:
                pt_lon = float(o)
            except (ValueError, TypeError):
                pass
        for _, _, o in self.g.triples((pt, PLN.lat, None)):
            try:
                pt_lat = float(o)
            except (ValueError, TypeError):
                pass
        if pt_lon is None or pt_lat is None or not parcel_centroids:
            continue
        # Find nearest parcel by centroid distance
        best_uri = None
        best_dist = float("inf")
        for puri, clon, clat in parcel_centroids:
            d = (pt_lon - clon) ** 2 + (pt_lat - clat) ** 2
            if d < best_dist:
                best_dist = d
                best_uri = puri
        if best_uri is not None and best_dist < 0.005:  # ~500m threshold
            located_in_relations.append((str(pt), str(best_uri)))

    return {"located_in": located_in_relations, "intersects": [], "contains": []}


def _to_uri_safe(uri_str: str):
    """Safely convert a string to URIRef, returning None if invalid."""
    if not uri_str:
        return None
    if uri_str.startswith("http"):
        return URIRef(uri_str)
    if uri_str.startswith("pln:"):
        return URIRef(PLN_NS + uri_str[4:])
    return URIRef(PLN_NS + uri_str)


# PLN_NS for _to_uri_safe (imported from ontology)


# ============================================================
# v4.8 - Layer group virtual entities + semantic layer
# ============================================================


def _add_gis_layer_groups(self) -> None:
    """Build GisLayerSet virtual entities aggregating L1 entities by semantic_group.

    For each semantic_group (from get_all_gis_layer_groups()) that has entities
    in the graph, creates a pln:GisLayerSet_{group} node with:
      - pln:semantic_group, pln:geometry_kind, pln:gis_description
      - pln:entity_count
      - pln:dominant_label (most frequent has_semantic_label)
      - pln:contains_entity (links to all member entities)

    Layer metadata (gis_type_ref, geometry_kind, description) is read
    dynamically from gis_layer_registry.yaml via get_gis_layer_group_info().
    """
    from collections import Counter

    group_count = 0
    for group_name in get_all_gis_layer_groups():
        members = []
        label_counter: Counter = Counter()

        for s, _, o in self.g.triples((None, semantic_group, Literal(group_name))):
            members.append(s)
            for _, _, label_obj in self.g.triples((s, has_semantic_label, None)):
                label_counter[str(label_obj)] += 1

        if not members:
            continue

        group_info = get_gis_layer_group_info(group_name)
        geom_kind = group_info.get("geometry_kind", GEOMETRY_POLYGON)
        desc = group_info.get("description", group_name)

        if not group_info:
            for m in members:
                for _, _, gk in self.g.triples((m, geometry_kind, None)):
                    geom_kind = str(gk)
                    break
                break

        group_uri = PLN[f"GisLayerSet_{group_name}"]
        self.g.add((group_uri, RDF.type, EntityTypes.GisLayerSet))
        self.g.add((group_uri, semantic_group, Literal(group_name)))
        self.g.add((group_uri, geometry_kind, Literal(geom_kind)))
        self.g.add((group_uri, gis_description, Literal(desc)))
        self.g.add((group_uri, entity_count, Literal(len(members), datatype=XSD.integer)))

        if label_counter:
            dom_label = label_counter.most_common(1)[0][0]
            self.g.add((group_uri, dominant_label, Literal(dom_label)))

        if label_counter:
            top3 = label_counter.most_common(3)
            dist_str = ", ".join(f"{lbl}({cnt})" for lbl, cnt in top3)
            enriched_desc = f"{desc} - {len(members)}个实体，主要: {dist_str}"
            self.g.add((group_uri, PLN.gis_description_enriched, Literal(enriched_desc)))

        for m in members:
            self.g.add((group_uri, contains_entity, m))

        group_count += 1
        logger.info("[GisLayerSet] %s: %d entities, dominant=%s",
                    group_name, len(members),
                    label_counter.most_common(1)[0][0] if label_counter else "N/A")

    if group_count:
        logger.info("Added %d GisLayerSet virtual entities", group_count)


def _add_semantic_enrichment(self) -> None:
    """Add entity-type-level semantic-enrichment triples.

    For each unique (entity_type, has_semantic_label) combination, writes:
      - pln:taxonomic_parent (classification hierarchy, already on parcels)
      - pln:legal_constraint (legal restriction from planning_zone)
      - pln:allowed_operations (permitted operations from allowed_operations.yaml)

    For non-parcel entity types (Road, WaterBody, Facility, Zone), writes
    type-level semantics as GisLayerSet annotations if applicable.

    Note: Parcel-level semantic triples are already written in _add_parcels().
    This function handles Zone-level (planning_zone -> control_code -> constraint)
    semantic enrichment that wasn't covered per-parcel.
    """
    # Enrich Zone entities with legal_constraint based on their planning context
    # (Zones like "有条件建设区" have implicit constraints)
    count = 0
    for s, _, _ in self.g.triples((None, RDF.type, EntityTypes.Zone)):
        name_lit = None
        for _, _, o in self.g.triples((s, PLN.name, None)):
            name_lit = str(o)
            break
        if not name_lit:
            continue

        # Map zone names to constraints
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
            self.g.add((s, legal_constraint, Literal(zone_constraint)))
            count += 1

    if count:
        logger.info("Added %d zone-level legal_constraint triples", count)


