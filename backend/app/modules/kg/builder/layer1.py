"""Layer 1: static entity builders (from ContextBlock + typed morphology groups).

All functions are module-level, assigned to PlanningKG in base.py.
Zero shapely/geopandas dependency.
"""
from typing import Any, List

from rdflib import Literal, RDF
from rdflib.namespace import XSD

from app.utils.logger import get_logger
from ..ontology import PLN, EntityTypes, Relations

logger = get_logger(__name__)


def _add_village_entity(self, village_name: str) -> None:
    v = PLN.village
    self.g.add((v, RDF.type, EntityTypes.AdministrativeVillage))
    self.g.add((v, PLN.name, Literal(village_name or "unknown")))


def _add_village_meta_from_blocks(self, blocks) -> None:
    from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT
    for block in blocks:
        if getattr(block, "block_type", None) != CBT.VILLAGE_META:
            continue
        d = block.data
        v = PLN.village
        total = d.get("total_area_ha", 0)
        if total:
            self.g.add((v, PLN.totalArea_ha, Literal(total, datatype=XSD.double)))
        construction = d.get("construction_boundary_ha", 0)
        if construction:
            self.g.add((v, PLN.constructionArea_ha, Literal(construction, datatype=XSD.double)))
        center = d.get("center")
        if center and len(center) >= 2:
            self.g.add((v, PLN.lon, Literal(center[0], datatype=XSD.double)))
            self.g.add((v, PLN.lat, Literal(center[1], datatype=XSD.double)))


def _add_natural_villages_from_blocks(self, blocks) -> None:
    from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT
    for block in blocks:
        if getattr(block, "block_type", None) != CBT.NATURAL_VILLAGES:
            continue
        for v in block.data.get("villages", []):
            name = v.get("name", "")
            if not name:
                continue
            uri = PLN[f"village_ann_{name}"]
            self.g.add((uri, RDF.type, EntityTypes.NaturalSettlement))
            self.g.add((uri, PLN.name, Literal(name)))
            center = v.get("center", [0, 0])
            if len(center) >= 2:
                self.g.add((uri, PLN.lon, Literal(center[0], datatype=XSD.double)))
                self.g.add((uri, PLN.lat, Literal(center[1], datatype=XSD.double)))
            self.g.add((uri, Relations.located_in, PLN.village))
            for bsm in v.get("parcel_ids", []):
                for s in self.g.subjects(PLN.bsm, Literal(bsm)):
                    if (s, RDF.type, PLN.Parcel) in self.g:
                        self.g.add((s, Relations.located_in, uri))


def _add_facilities_from_blocks(self, blocks) -> None:
    from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT, FacilityAnchor
    count = 0
    for block in blocks:
        if getattr(block, "block_type", None) != CBT.FACILITIES:
            continue
        for unit in getattr(block, "units", []):
            if isinstance(unit, FacilityAnchor):
                name = unit.name or ""
                if not name:
                    continue
                uri = PLN[f"facility_unit_{name}_{count}"]
                self.g.add((uri, RDF.type, PLN.Facility))
                self.g.add((uri, PLN.name, Literal(name)))
                self.g.add((uri, PLN.facility_type, Literal(unit.facility_type or "公共服务")))
                if unit.center and len(unit.center) >= 2:
                    self.g.add((uri, PLN.lon, Literal(unit.center[0], datatype=XSD.double)))
                    self.g.add((uri, PLN.lat, Literal(unit.center[1], datatype=XSD.double)))
                self.g.add((uri, Relations.located_in, PLN.village))
                self.g.add((PLN.village, PLN.has_facility, uri))
                count += 1
        for fa in block.data.get("anchors", []):
            name = fa.get("name", "")
            if not name or any(getattr(u, "name", "") == name for u in getattr(block, "units", [])):
                continue
            uri = PLN[f"facility_block_{name}_{count}"]
            self.g.add((uri, RDF.type, PLN.Facility))
            self.g.add((uri, PLN.name, Literal(name)))
            self.g.add((uri, PLN.facility_type, Literal(fa.get("facility_type", "公共服务"))))
            center = fa.get("center", [0, 0])
            if len(center) >= 2:
                self.g.add((uri, PLN.lon, Literal(center[0], datatype=XSD.double)))
                self.g.add((uri, PLN.lat, Literal(center[1], datatype=XSD.double)))
            self.g.add((uri, Relations.located_in, PLN.village))
            self.g.add((PLN.village, PLN.has_facility, uri))
            count += 1
    if count:
        logger.info("Added %d facilities from ContextBlock", count)


def _add_spatial_relations_from_blocks(self, blocks) -> None:
    from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT
    _MAP = {"east_of": PLN.east_of, "west_of": PLN.west_of, "north_of": PLN.north_of,
            "south_of": PLN.south_of, "adjacent_to": PLN.adjacent_to, "contains": PLN.contains,
            "contained_by": PLN.contained_by, "near": PLN.near}
    count = 0
    for block in blocks:
        if getattr(block, "block_type", None) != CBT.SPATIAL_RELATIONS:
            continue
        for rel in block.data.get("relations", []):
            pln_rel = _MAP.get(rel.get("relation", ""))
            if not pln_rel:
                continue
            subj = _find_entity_by_name(self, rel.get("subject", ""))
            obj = _find_entity_by_name(self, rel.get("object", ""))
            if subj and obj:
                self.g.add((subj, pln_rel, obj))
                count += 1
    if count:
        logger.info("Added %d spatial relations from ContextBlock", count)


def _find_entity_by_name(self, name: str):
    for s, _, o in self.g.triples((None, PLN.name, None)):
        if str(o) == name:
            return s
    return None


def _add_zone_adjacency_from_blocks(self, blocks) -> None:
    from app.modules.schema.contracts.context_contracts import ContextBlockType as CBT
    count = 0
    for block in blocks:
        if getattr(block, "block_type", None) != CBT.ZONE_ADJACENCY:
            continue
        for zone, neighbors in block.data.get("adjacency", {}).items():
            zu = PLN[f"zone_{zone}"]
            if (zu, RDF.type, PLN.Zone) not in self.g:
                self.g.add((zu, RDF.type, PLN.Zone)).add((zu, PLN.name, Literal(zone)))
            for nb in neighbors:
                nu = PLN[f"zone_{nb}"]
                if (nu, RDF.type, PLN.Zone) not in self.g:
                    self.g.add((nu, RDF.type, PLN.Zone)).add((nu, PLN.name, Literal(nb)))
                self.g.add((zu, PLN.adjacent_to, nu))
                count += 1
    if count:
        logger.info("Added %d zone adjacency relations", count)


def _add_terrain_from_blocks(self, blocks) -> None:
    pass


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
            if t.shared_boundary_length_m:
                self.g.add((a, PLN.shared_boundary_length, Literal(t.shared_boundary_length_m, datatype=XSD.double)))
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
        if (s, RDF.type, PLN.Parcel) not in self.g:
            continue
        if not dlbm:
            return s
        for _, _, do in self.g.triples((s, PLN.dlbm, None)):
            if str(do) == dlbm:
                return s
    return None


def _add_parcels_typed(self, parcels: List[Any]) -> None:
    from app.modules.schema.encodings.code_sets import resolve_zone_type_for_dlbm
    for p in parcels:
        bsm = str(getattr(p, "bsm", "")).strip()
        dlbm = str(getattr(p, "dlbm", "")).strip()
        area = getattr(p, "area_sqm", 0) or 0
        if not bsm:
            continue
        key = f"{bsm}_{dlbm}_{int(area)}"
        pu = PLN[f"parcel_{key}"]
        self.g.add((pu, RDF.type, PLN.Parcel))
        self.g.add((pu, PLN.bsm, Literal(bsm)))
        self.g.add((pu, PLN.dlbm, Literal(dlbm)))
        self.g.add((pu, PLN.area_sqm, Literal(area, datatype=XSD.double)))
        self.g.add((pu, PLN.area_ha, Literal(area / 10000, datatype=XSD.double)))
        zt = resolve_zone_type_for_dlbm(dlbm)
        self.g.add((pu, PLN.current_zone_type, Literal(zt)))
        self.g.add((pu, Relations.located_in, PLN.village))
        try:
            from app.modules.schema import get_vne_for_zone_type
            vne = get_vne_for_zone_type(zt)
            if vne:
                self.g.add((pu, PLN.vne_code, Literal(vne)))
        except Exception:
            pass
        try:
            from app.modules.schema import dlbm_to_planning_zone
            pz = dlbm_to_planning_zone(dlbm)
            if pz:
                self.g.add((pu, PLN.planning_zone, Literal(pz)))
        except Exception:
            pass
        self._parcel_count += 1


def _add_infrastructure_from_typed(self, parcels: List[Any]) -> None:
    rd = {"1000", "1001", "1002", "1003", "1004", "1005", "1006", "1040", "2126", "2200"}
    wd = {"1101", "1102", "1103", "1104", "1105", "1106", "1109", "1110", "1140", "1180", "3100"}
    fd = {"0800", "0801", "0802", "0803", "0806", "0810", "0900", "2122", "2125"}
    roads, waters, facilities = [], [], []
    for p in parcels:
        dlbm = str(getattr(p, "dlbm", "")).strip()
        bsm = str(getattr(p, "bsm", "")).strip()
        if not bsm:
            continue
        if dlbm in rd:
            roads.append(bsm)
        elif dlbm in wd:
            waters.append(bsm)
        elif dlbm in fd:
            facilities.append(bsm)
    for bsm in roads:
        u = PLN[f"road_{bsm}"]
        self.g.add((u, RDF.type, EntityTypes.Road))
        self.g.add((u, PLN.name, Literal(f"道路_{bsm}")))
        self.g.add((u, Relations.located_in, PLN.village))
        self.g.add((PLN.village, Relations.connects, u))
    for bsm in waters:
        u = PLN[f"water_{bsm}"]
        self.g.add((u, RDF.type, EntityTypes.WaterBody))
        self.g.add((u, PLN.name, Literal(f"水域_{bsm}")))
        self.g.add((u, Relations.located_in, PLN.village))
    for bsm in facilities:
        u = PLN[f"facility_{bsm}"]
        self.g.add((u, RDF.type, EntityTypes.Facility))
        self.g.add((u, PLN.name, Literal(f"设施_{bsm}")))
        self.g.add((u, Relations.located_in, PLN.village))
    total = len(roads) + len(waters) + len(facilities)
    if total:
        logger.info("Infrastructure: %d roads, %d water, %d facilities", len(roads), len(waters), len(facilities))


def _add_control_lines_from_typed(self, points_layer, polygons_layer) -> None:
    count = 0
    for p in getattr(points_layer, "hazard_points", []):
        name = getattr(p, "name", f"hazard_{count}")
        uri = PLN[f"hazard_{name}"]
        self.g.add((uri, RDF.type, PLN.ControlLine))
        self.g.add((uri, PLN.name, Literal(str(name))))
        self.g.add((uri, PLN.source, Literal("geological_hazard")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for _ in getattr(polygons_layer, "hazard_control_lines", []):
        uri = PLN[f"hazard_line_{count}"]
        self.g.add((uri, RDF.type, PLN.ControlLine))
        self.g.add((uri, PLN.name, Literal(f"灾害防控线_{count}")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for _ in getattr(polygons_layer, "flood_control_lines", []):
        uri = PLN[f"flood_line_{count}"]
        self.g.add((uri, RDF.type, PLN.ControlLine))
        self.g.add((uri, PLN.name, Literal(f"洪涝控制线_{count}")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for _ in getattr(polygons_layer, "construction_zone", []):
        uri = PLN[f"zone_conditional_{count}"]
        self.g.add((uri, RDF.type, PLN.Zone))
        self.g.add((uri, PLN.name, Literal("有条件建设区")))
        self.g.add((uri, PLN.restriction, Literal("限制建设")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    if count:
        logger.info("Added %d control lines", count)


def _add_planning_elements_from_typed(self, polygons_layer) -> None:
    count = 0
    for z in getattr(polygons_layer, "land_use_zones", []):
        code = getattr(z, "ysdm", getattr(z, "dlbm", f"tdyt_{count}"))
        uri = PLN[f"tdyt_{code}"]
        self.g.add((uri, RDF.type, PLN.Zone))
        self.g.add((uri, PLN.name, Literal(f"TDYT_{code}")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for _ in getattr(polygons_layer, "construction_ctrl_zones", []):
        uri = PLN[f"zone_jsydgzq_{count}"]
        self.g.add((uri, RDF.type, PLN.Zone))
        self.g.add((uri, PLN.name, Literal("建设用地管制区")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for _ in getattr(polygons_layer, "planning_scope", []):
        self.g.add((PLN.village, PLN.has_planning_scope, Literal(True)))
        count += 1
    if count:
        logger.info("Added %d planning elements", count)


def _add_natural_features_from_typed(self, polygons_layer, points_layer) -> None:
    count = 0
    for w in getattr(polygons_layer, "water_bodies", []):
        bsm = str(getattr(w, "bsm", f"water_{count}"))
        uri = PLN[f"water_{bsm}"]
        self.g.add((uri, RDF.type, EntityTypes.WaterBody))
        self.g.add((uri, PLN.name, Literal(f"水域_{bsm}")))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    for e in getattr(points_layer, "elevation_points", []):
        bsm = str(getattr(e, "bsm", f"elev_{count}"))
        uri = PLN[f"elevation_{bsm}"]
        self.g.add((uri, RDF.type, PLN.Parcel))
        self.g.add((uri, PLN.name, Literal(f"高程点_{bsm}")))
        elev = getattr(e, "elevation", 0) or 0
        self.g.add((uri, PLN.elevation, Literal(float(elev), datatype=XSD.double)))
        self.g.add((uri, Relations.located_in, PLN.village))
        count += 1
    if count:
        logger.info("Added %d natural features", count)


def _add_designated_as_from_typed(self, parcels: List[Any]) -> None:
    from app.modules.schema.encodings.code_sets import dlbm_to_planning_zone
    count = 0
    for p in parcels:
        bsm = str(getattr(p, "bsm", "")).strip()
        dlbm = str(getattr(p, "dlbm", "")).strip()
        area = getattr(p, "area_sqm", 0) or 0
        if not bsm:
            continue
        key = f"{bsm}_{dlbm}_{int(area)}"
        pu = PLN[f"parcel_{key}"]
        if (pu, RDF.type, PLN.Parcel) not in self.g:
            continue
        zn = dlbm_to_planning_zone(dlbm)
        zu = PLN[f"zone_{zn}"]
        if (zu, RDF.type, PLN.Zone) in self.g:
            self.g.add((pu, Relations.designated_as, zu))
            count += 1
    if count:
        logger.info("Added %d designated_as", count)


def _add_vne_categories(self):
    try:
        from app.modules.schema.encodings.dicts.loader import get_center
        center = get_center()
        vd = center.encoding("vne")
    except Exception as e:
        logger.debug("VNE skipped: %s", e)
        return
    count = 0
    classes = vd.raw.get("classes", [])
    codes = {str(c.get("code", "")) for c in classes}
    for entry in classes:
        code = str(entry.get("code", ""))
        if not code:
            continue
        cu = PLN[f"vne_{code}"]
        self.g.add((cu, RDF.type, EntityTypes.LandUseCategory))
        self.g.add((cu, PLN.code, Literal(code)))
        self.g.add((cu, PLN.name, Literal(entry.get("name", ""))))
        if entry.get("zone_type"):
            self.g.add((cu, PLN.zone_type, Literal(entry["zone_type"])))
        if len(code) >= 2 and code[:-1] in codes:
            pu = PLN[f"vne_{code[:-1]}"]
            self.g.add((cu, PLN.parent_category, pu))
            self.g.add((pu, PLN.has_subcategory, cu))
        if len(code) == 1:
            self.g.add((PLN.village, PLN.has_land_use_category, cu))
        count += 1
    logger.info("Added %d VNE categories", count)


def _add_three_zone_three_line(self):
    try:
        from app.modules.schema.encodings.dicts.rule_loader import get_rule_loader
        loader = get_rule_loader()
    except Exception as e:
        logger.debug("Three zone/line skipped: %s", e)
        return
    seen = set()
    for zone_name, primary_zone in loader.planning_zone_to_primary_zone().items():
        if primary_zone not in seen:
            tz = PLN[f"three_zone_{primary_zone}"]
            self.g.add((tz, RDF.type, EntityTypes.ThreeZone))
            self.g.add((tz, PLN.name, Literal(primary_zone)))
            zu = PLN[f"zone_{zone_name}"]
            if (zu, RDF.type, PLN.Zone) in self.g:
                self.g.add((tz, Relations.delineates, zu))
            seen.add(primary_zone)
    for ld in loader.three_line_types():
        tl = PLN[f"three_line_{ld.key}"]
        self.g.add((tl, RDF.type, EntityTypes.ThreeLine))
        self.g.add((tl, PLN.code, Literal(ld.key)))
        self.g.add((tl, PLN.name, Literal(ld.label)))
        if ld.color:
            self.g.add((tl, PLN.color, Literal(ld.color)))
        if ld.gdb_key:
            self.g.add((tl, PLN.gdb_key, Literal(ld.gdb_key)))
    logger.info("Added %d ThreeZone + %d ThreeLine", len(seen), len(loader.three_line_types()))


def add_annotations(self, annotations: list):
    from app.modules.schema.types.spatial_types import CurrentFacility
    fc, vc = 0, 0
    for ann in annotations:
        cat = getattr(ann, "category", "")
        if cat == "村名":
            text = getattr(ann, "text", "")
            if text and hasattr(ann, "geometry"):
                coords = ann.geometry.get("coordinates", [0, 0])
                uri = PLN[f"village_ann_{text}"]
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
            fac_uri = PLN[f"facility_ann_{facility.facility_name or 'unknown'}_{fc}"]
            self.g.add((fac_uri, RDF.type, PLN.Facility))
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
        bsm = getattr(road, "bsm", "") or f"road_{count}"
        uri = PLN[f"road_{bsm}"]
        self.g.add((uri, RDF.type, PLN.Road))
        self.g.add((uri, PLN.name, Literal(f"道路_{bsm}")))
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