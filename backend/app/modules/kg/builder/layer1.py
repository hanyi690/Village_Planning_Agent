"""Layer 1: static entity builders (from bundle morphology groups).

All functions are module-level, assigned to PlanningKG in base.py.
Zero shapely/geopandas dependency.
"""
from typing import Any, List

from rdflib import Literal, RDF
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations, EntityIdPolicy

logger = get_logger(__name__)


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
            self.g.add((a, PLN.touches, b))
            self.g.add((b, PLN.touches, a))
            if t.shared_boundary_length_m:
                self.g.add((a, PLN.shared_boundary_length, Literal(t.shared_boundary_length_m, datatype=XSD.double)))
                self.g.add((b, PLN.shared_boundary_length, Literal(t.shared_boundary_length_m, datatype=XSD.double)))
            count += 1
    for n in relations.nearby:
        a = _parcel_uri_by_bsm_dlbm(self, n.bsm_a, n.dlbm_a)
        b = _parcel_uri_by_bsm_dlbm(self, n.bsm_b, n.dlbm_b)
        if a and b:
            self.g.add((a, PLN.nearby, b))
            if n.centroid_distance_m:
                self.g.add((a, PLN.centroid_distance, Literal(n.centroid_distance_m, datatype=XSD.double)))
            count += 1
    for c in relations.connected:
        a = _parcel_uri_by_bsm_dlbm(self, c.bsm_a, "")
        b = _parcel_uri_by_bsm_dlbm(self, c.bsm_b, "")
        if a and b:
            self.g.add((a, PLN.connected_via_road, b))
            if c.road_length_m:
                self.g.add((a, PLN.road_segment_length, Literal(c.road_length_m, datatype=XSD.double)))
            if c.road_bsm:
                self.g.add((a, PLN.via_road, Literal(c.road_bsm)))
            count += 1
    if count:
        logger.info("Added %d parcel relations", count)


def _parcel_uri_by_bsm_dlbm(self, bsm: str, dlbm: str):
    for s, _, _ in self.g.triples((None, PLN.bsm, Literal(bsm))):
        if (s, RDF.type, EntityTypes.Parcel) not in self.g:
            continue
        return s
    return None


def _add_parcels(self, parcels) -> None:
    from app.modules.schema.encodings.code_sets import resolve_zone_type_for_dlbm
    bsm_seq: dict = {}  # Track sequence per BSM for duplicate disambiguation
    for p in parcels:
        bsm = str(getattr(p, "bsm", "")).strip()
        dlbm = str(getattr(p, "dlbm", "")).strip()
        if not bsm:
            continue
        area = getattr(p, "area_sqm", 0) or 0
        seq = bsm_seq.get(bsm, 0)
        pu = EntityIdPolicy.uri_with_seq("parcel", bsm, seq)
        bsm_seq[bsm] = seq + 1
        self.g.add((pu, RDF.type, EntityTypes.Parcel))
        self.g.add((pu, PLN.bsm, Literal(bsm)))
        self.g.add((pu, PLN.dlbm, Literal(dlbm)))
        self.g.add((pu, PLN.area_sqm, Literal(area, datatype=XSD.double)))
        self.g.add((pu, PLN.area_ha, Literal(area / 10000, datatype=XSD.double)))

        # Raw bundle attributes — faithful storage, not derived
        dlmc = getattr(p, "name", "") or ""
        if dlmc:
            self.g.add((pu, PLN.dlmc, Literal(dlmc)))
        sddlbm = getattr(p, "sddlbm", "") or ""
        if sddlbm:
            self.g.add((pu, PLN.sddlbm, Literal(sddlbm)))
        ysdm = getattr(p, "ysdm", "") or ""
        if ysdm:
            self.g.add((pu, PLN.ysdm, Literal(ysdm)))
        dlbm_system = str(getattr(p, "dlbm_system", "") or "")
        if dlbm_system:
            self.g.add((pu, PLN.dlbm_system, Literal(dlbm_system)))

        # current_zone_type — derived from DLBM via lookup (factual categorization)
        zt = resolve_zone_type_for_dlbm(dlbm)
        self.g.add((pu, PLN.current_zone_type, Literal(zt)))

        # planning_zone / primary_zone — from Data layer ingest
        pz = getattr(p, "planning_zone", "") or ""
        if pz:
            self.g.add((pu, PLN.planning_zone, Literal(pz)))
        prz = getattr(p, "primary_zone", "") or ""
        if prz:
            self.g.add((pu, PLN.primary_zone, Literal(prz)))

        # Centroid
        try:
            geo = getattr(p, "geometry", None)
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

        self.g.add((pu, Relations.located_in, PLN.village))
        self._parcel_count += 1


def _add_water_bodies(self, water_bodies) -> None:
    count = 0
    for w in water_bodies:
        bsm = str(getattr(w, "bsm", "")).strip()
        ysdm = str(getattr(w, "ysdm", "")).strip()
        if bsm:
            uri = EntityIdPolicy.uri("water", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("water", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.WaterBody))
        name = getattr(w, "name", "") or f"水域_{bsm or count}"
        self.g.add((uri, PLN.name, Literal(name)))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    if count:
        logger.info("Added %d water bodies", count)


def _add_control_lines_from_typed(self, points_layer, polygons_layer) -> None:
    count = 0
    for p in getattr(points_layer, "hazard_points", []):
        bsm = str(getattr(p, "bsm", "")).strip()
        ysdm = str(getattr(p, "ysdm", "")).strip()
        name = getattr(p, "name", f"hazard_{count}")
        if bsm:
            uri = EntityIdPolicy.uri("hazard", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("hazard", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, PLN.ControlLine))
        self.g.add((uri, PLN.name, Literal(str(name))))
        self.g.add((uri, PLN.source, Literal("geological_hazard")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for item in getattr(polygons_layer, "hazard_control_lines", []):
        bsm = str(getattr(item, "bsm", "")).strip()
        ysdm = str(getattr(item, "ysdm", "")).strip()
        if bsm:
            uri = EntityIdPolicy.uri("hazard_line", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("hazard_line", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, PLN.ControlLine))
        self.g.add((uri, PLN.name, Literal(f"灾害防控线_{bsm or count}")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for item in getattr(polygons_layer, "flood_control_lines", []):
        bsm = str(getattr(item, "bsm", "")).strip()
        ysdm = str(getattr(item, "ysdm", "")).strip()
        if bsm:
            uri = EntityIdPolicy.uri("flood_line", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("flood_line", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, PLN.ControlLine))
        self.g.add((uri, PLN.name, Literal(f"洪涝控制线_{bsm or count}")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for item in getattr(polygons_layer, "construction_zone", []):
        bsm = str(getattr(item, "bsm", "")).strip()
        ysdm = str(getattr(item, "ysdm", "")).strip()
        if bsm:
            uri = EntityIdPolicy.uri("zone_conditional", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("zone_conditional", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Zone))
        self.g.add((uri, PLN.name, Literal("有条件建设区")))
        self.g.add((uri, PLN.restriction, Literal("限制建设")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    if count:
        logger.info("Added %d control lines", count)


def _add_planning_elements_from_typed(self, polygons_layer) -> None:
    count = 0
    for z in getattr(polygons_layer, "land_use_zones", []):
        bsm = str(getattr(z, "bsm", "")).strip()
        ysdm = str(getattr(z, "ysdm", "")).strip()
        code = getattr(z, "ysdm", getattr(z, "dlbm", ""))
        if bsm:
            uri = EntityIdPolicy.uri("tdyt", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("tdyt", ysdm or str(code), count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Zone))
        self.g.add((uri, PLN.name, Literal(f"TDYT_{code}")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for item in getattr(polygons_layer, "construction_ctrl_zones", []):
        bsm = str(getattr(item, "bsm", "")).strip()
        ysdm = str(getattr(item, "ysdm", "")).strip()
        if bsm:
            uri = EntityIdPolicy.uri("zone_jsydgzq", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("zone_jsydgzq", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Zone))
        self.g.add((uri, PLN.name, Literal("建设用地管制区")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for _ in getattr(polygons_layer, "planning_scope", []):
        self.g.add((PLN.village, PLN.has_planning_scope, Literal(True)))
        count += 1
    if count:
        logger.info("Added %d planning elements", count)


def add_annotations(self, annotations: list):
    from app.modules.schema.types.spatial_types import CurrentFacility
    fc, vc = 0, 0
    for ann in annotations:
        cat = getattr(ann, "category", "")
        if cat == "村名":
            text = getattr(ann, "text", "")
            bsm = str(getattr(ann, "bsm", "")).strip()
            ysdm = str(getattr(ann, "ysdm", "")).strip()
            if text and hasattr(ann, "geometry"):
                coords = ann.geometry.get("coordinates", [0, 0])
                if bsm:
                    uri = EntityIdPolicy.uri("village_ann", bsm)
                else:
                    uri = EntityIdPolicy.fallback_uri("village_ann", ysdm, vc)
                EntityIdPolicy.attach_bsm(self.g, uri, bsm)
                self.g.add((uri, RDF.type, EntityTypes.NaturalSettlement))
                self.g.add((uri, PLN.name, Literal(text)))
                self.g.add((uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
                self.g.add((uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
                self.g.add((uri, Relations.located_in, PLN.village))
                vc += 1
        elif cat == "现状设施点":
            facility = CurrentFacility.from_annotation_feature(
                {"properties": ann._raw, "geometry": ann.geometry}
            ) if hasattr(ann, "_raw") else None
            if facility is None:
                continue
            bsm = str(getattr(facility, "bsm", "")).strip()
            ysdm = str(getattr(facility, "ysdm", "")).strip()
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
            self.g.add((fac_uri, Relations.serves, Literal(getattr(facility, "category", "") or "public_service")))
            self.g.add((fac_uri, Relations.located_in, PLN.village))
            self.g.add((PLN.village, PLN.has_facility, fac_uri))
            fc += 1
    if fc or vc:
        logger.info("Annotations: %d facilities, %d villages", fc, vc)
    return self


def add_roads(self, roads: list):
    count = 0
    for road in roads:
        bsm = str(getattr(road, "bsm", "")).strip()
        ysdm = str(getattr(road, "ysdm", "")).strip()
        if bsm:
            uri = EntityIdPolicy.uri("road", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("road", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Road))
        self.g.add((uri, PLN.name, Literal(f"道路_{bsm or count}")))
        length = getattr(road, "shape_length", 0.0) or 0.0
        if length:
            self.g.add((uri, PLN.length, Literal(length, datatype=XSD.double)))
        self.g.add((uri, PLN.road_level, Literal(getattr(road, "road_level", "") or "村道")))
        self.g.add((uri, Relations.located_in, PLN.village))
        self.g.add((PLN.village, Relations.connects, uri))
        count += 1
    if count:
        logger.info("Added %d roads", count)
    return self


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


def _add_natural_villages_from_typed(self, parcels) -> None:
    """Create NaturalSettlement entities from parcel annotations.

    NaturalSettlement names are extracted from parcel annotations (village_ann_*).
    If no settlement annotations exist, creates a single village entity.
    """
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel

    # Collect settlement names from parcel annotations
    settlement_names = set()
    for p in parcels:
        if not isinstance(p, CurrentLandUseParcel):
            continue
        raw = getattr(p, '_raw', {}) or {}
        ann = raw.get('annotation', '') or ''
        if ann and ann.startswith('village_ann_'):
            settlement_names.add(ann.replace('village_ann_', '', 1))

    if not settlement_names:
        return

    seq = 0
    for name in sorted(settlement_names):
        uri = EntityIdPolicy.fallback_uri("village_ann", name, seq)
        self.g.add((uri, RDF.type, EntityTypes.NaturalSettlement))
        self.g.add((uri, PLN.name, Literal(name)))
        self.g.add((uri, Relations.located_in, PLN.village))
        # Link parcels to this settlement
        for p in parcels:
            if not isinstance(p, CurrentLandUseParcel):
                continue
            raw = getattr(p, '_raw', {}) or {}
            ann = raw.get('annotation', '') or ''
            if ann == f'village_ann_{name}':
                for s in self.g.subjects(PLN.bsm, Literal(getattr(p, 'bsm', ''))):
                    if (s, RDF.type, EntityTypes.Parcel) in self.g:
                        self.g.add((s, Relations.located_in, uri))
        seq += 1

    logger.info("Added %d natural settlements from typed parcels", len(settlement_names))


def _add_facilities_from_typed(self, facilities) -> None:
    """Create Facility entities from bundle.points.facilities_current."""
    from app.modules.schema.types.spatial_types import CurrentFacility
    count = 0
    for f in facilities:
        if not isinstance(f, CurrentFacility):
            continue
        name = getattr(f, 'facility_name', '') or f"facility_{count}"
        bsm = str(getattr(f, 'bsm', '')).strip()
        ysdm = str(getattr(f, 'ysdm', '')).strip()
        if bsm:
            uri = EntityIdPolicy.uri("facility", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("facility", ysdm, count)
        EntityIdPolicy.attach_bsm(self.g, uri, bsm)
        self.g.add((uri, RDF.type, EntityTypes.Facility))
        self.g.add((uri, PLN.name, Literal(name)))
        ftype = getattr(f, 'facility_type', '') or '公共服务'
        self.g.add((uri, PLN.facility_type, Literal(ftype)))
        geom = getattr(f, 'geometry', {}) or {}
        coords = geom.get('coordinates', [0, 0]) if isinstance(geom, dict) else [0, 0]
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            self.g.add((uri, PLN.lon, Literal(coords[0], datatype=XSD.double)))
            self.g.add((uri, PLN.lat, Literal(coords[1], datatype=XSD.double)))
        self.g.add((uri, Relations.located_in, PLN.village))
        self.g.add((PLN.village, PLN.has_facility, uri))
        count += 1
    if count:
        logger.info("Added %d facilities from typed parcels", count)