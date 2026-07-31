"""Layer 1 core: static entity builders (village, parcels, facilities, roads, water, control lines, etc).

All functions are module-level, operating on a PlanningKG instance passed as `kg`.
Zero shapely/geopandas dependency.
"""
from typing import Any, Dict, List

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

from .registry import kg_builder, BuildContext
from ..ontology import (
    PLN, PLN_NS, GEO, EntityTypes, Relations, EntityIdPolicy, SemanticPredicates,
    ProvenancePredicates, GeoPredicates,
    GEOMETRY_POLYGON, GEOMETRY_LINE, GEOMETRY_POINT, GEOMETRY_RASTER,
)
from .enrichment import (
    derive_semantic_label, derive_taxonomic_parent,
    derive_legal_constraint, get_allowed_operations,
    get_gis_layer_group_info, get_all_gis_layer_groups,
)
from .geo_helpers import add_centroid, add_bbox, add_geo_feature_type

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Predicate shortcuts
gis_type_ref = SemanticPredicates.gis_type_ref
geometry_kind = SemanticPredicates.geometry_kind
semantic_group = SemanticPredicates.semantic_group
has_semantic_label = SemanticPredicates.has_semantic_label
taxonomic_parent = SemanticPredicates.taxonomic_parent
legal_constraint = SemanticPredicates.legal_constraint
allowed_operations = SemanticPredicates.allowed_operations


def add_village_entity(kg, village_name: str) -> None:
    v = PLN.village
    kg.g.add((v, RDF.type, EntityTypes.AdministrativeVillage))
    kg.g.add((v, PLN.name, Literal(village_name or "unknown")))


def add_village_meta(kg, bundle) -> None:
    v = PLN.village
    meta = getattr(bundle, 'metadata', None)
    if meta is None:
        return
    bbox = getattr(meta, 'bbox_wgs84', None)
    if bbox is not None:
        try:
            t = bbox.as_tuple()
            add_bbox(kg.g, v, t[0], t[1], t[2], t[3])
        except Exception:
            pass


def add_bundle_metadata(kg, bundle) -> None:
    """Write Bundle metadata to KG semantic layer.

    Called after _build_village_entity to persist Bundle provenance info.
    This enables cross-session Bundle→KG闭环.
    """
    from ..memory import EntityAnnotation

    meta = getattr(bundle, 'metadata', None)
    if meta is None:
        return

    village_name = getattr(meta, 'village_name', '')
    center_lon = getattr(meta, 'center_lon', None)
    center_lat = getattr(meta, 'center_lat', None)
    total_area = getattr(meta, 'total_area_ha', 0)
    parcel_count = getattr(bundle, 'parcel_count', 0)

    desc_parts = []
    if village_name:
        desc_parts.append(f"村庄{village_name}")
    if center_lon and center_lat:
        desc_parts.append(f"中心坐标({center_lon:.4f},{center_lat:.4f})")
    if total_area:
        desc_parts.append(f"总面积{total_area:.2f}公顷")
    if parcel_count:
        desc_parts.append(f"共{parcel_count}个地块")

    if desc_parts:
        annotation = EntityAnnotation(
            entity_uri="pln:village",
            entity_type="AdministrativeVillage",
            description="，".join(desc_parts),
        )
        kg.memory.add_entity_annotation(annotation)
        logger.info("[layer1_core] Added bundle metadata to KG semantic layer")


def _parcel_centroid(geom: dict):
    try:
        gt = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if gt == "Polygon" and coords:
            ring = coords[0]
            if ring:
                n = len(ring)
                sx = sum(c[0] for c in ring)
                sy = sum(c[1] for c in ring)
                return (sx / n, sy / n)
        elif gt == "MultiPolygon" and coords:
            ring = coords[0][0] if coords[0] else []
            if ring:
                n = len(ring)
                sx = sum(c[0] for c in ring)
                sy = sum(c[1] for c in ring)
                return (sx / n, sy / n)
    except Exception:
        pass
    return None


@kg_builder("landuse_current", entity_type="Parcel", layer=1, order=0)
def add_parcels(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    bsm_seq: dict = {}
    for p in features:
        bsm = str(p.bsm).strip()
        dlbm = str(p.dlbm).strip()
        if not bsm:
            continue
        area = p.area_sqm or 0
        seq = bsm_seq.get(bsm, 0)
        pu = EntityIdPolicy.uri_with_seq("parcel", bsm, seq)
        bsm_seq[bsm] = seq + 1
        kg.g.add((pu, RDF.type, EntityTypes.Parcel))
        kg.g.add((pu, PLN.bsm, Literal(bsm)))
        kg.g.add((pu, PLN.seq, Literal(seq, datatype=XSD.integer)))
        kg.g.add((pu, PLN.dlbm, Literal(dlbm)))
        kg.g.add((pu, PLN.area_ha, Literal(area / 10000, datatype=XSD.double)))

        dlmc = p.name or ""
        if dlmc:
            kg.g.add((pu, PLN.dlmc, Literal(dlmc)))
        sddlbm = p.sddlbm or ""
        if sddlbm:
            kg.g.add((pu, PLN.sddlbm, Literal(sddlbm)))
        ysdm = p.ysdm or ""
        if ysdm:
            kg.g.add((pu, PLN.ysdm, Literal(ysdm)))
        dlbm_system = str(p.dlbm_system or "")
        if dlbm_system:
            kg.g.add((pu, PLN.dlbm_system, Literal(dlbm_system)))

        zt = derive_taxonomic_parent(dlbm)

        pz = p.planning_zone or ""
        if pz:
            kg.g.add((pu, PLN.planning_zone, Literal(pz)))
        prz = p.primary_zone or ""
        if prz:
            kg.g.add((pu, PLN.primary_zone, Literal(prz)))

        kg.g.add((pu, gis_type_ref, Literal("landuse_current")))
        kg.g.add((pu, geometry_kind, Literal(GEOMETRY_POLYGON)))
        kg.g.add((pu, semantic_group, Literal("current_landuse")))
        label = derive_semantic_label(dlbm)
        if label:
            kg.g.add((pu, has_semantic_label, Literal(label)))

        if zt:
            kg.g.add((pu, taxonomic_parent, Literal(zt)))
        if pz:
            constraint = derive_legal_constraint(pz)
            if constraint:
                kg.g.add((pu, legal_constraint, Literal(constraint)))
        try:
            from app.modules.schema.encodings.code_sets import get_ghytbm_for_dlbm
            ghytbm = get_ghytbm_for_dlbm(dlbm)
        except Exception:
            ghytbm = ""
        ops = get_allowed_operations(ghytbm=ghytbm, planning_zone=pz)
        for op in ops:
            kg.g.add((pu, allowed_operations, Literal(op)))

        try:
            geo = p.geometry
            if geo and isinstance(geo, dict):
                gtype = geo.get("type", "")
                coords = geo.get("coordinates", None)
                if coords and gtype == "Polygon" and len(coords) > 0 and len(coords[0]) > 0:
                    ring = coords[0]
                    lon = sum(c[0] for c in ring) / len(ring)
                    lat = sum(c[1] for c in ring) / len(ring)
                    add_centroid(kg.g, pu, lon, lat)
                elif coords and gtype == "MultiPolygon" and len(coords) > 0 and len(coords[0]) > 0 and len(coords[0][0]) > 0:
                    ring = coords[0][0]
                    lon = sum(c[0] for c in ring) / len(ring)
                    lat = sum(c[1] for c in ring) / len(ring)
                    add_centroid(kg.g, pu, lon, lat)
        except Exception:
            pass

        add_geo_feature_type(kg.g, pu)

        kg.g.add((pu, Relations.sfWithin, PLN.village))
        kg._parcel_count += 1

        mapping_prov = p.mapping_provenance or {}
        for field_name, prov in mapping_prov.items():
            if not isinstance(prov, dict):
                continue
            decided_by = prov.get("decided_by", "")
            if decided_by:
                kg.g.add((pu, ProvenancePredicates.decided_by, Literal(decided_by)))
            confidence = prov.get("confidence", "")
            if confidence:
                kg.g.add((pu, ProvenancePredicates.decision_confidence, Literal(confidence)))
            system = prov.get("system", "")
            if system:
                kg.g.add((pu, ProvenancePredicates.decision_evidence, Literal(system)))
            warning = prov.get("warning", "")
            if warning:
                kg.g.add((pu, ProvenancePredicates.mapping_basis, Literal(warning)))

    return {"count": len(features), "entity_type": "Parcel"}


@kg_builder("water", entity_type="WaterBody", layer=1, order=30)
def add_water_bodies(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    water_overlap = ctx.provenance.get("water_overlap", {})
    covered_bsms = set()
    for bsm_list in water_overlap.values():
        for b in bsm_list:
            covered_bsms.add(b)

    def _add_water_dims(uri, is_line_geom: bool):
        kg.g.add((uri, gis_type_ref, Literal("water")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE if is_line_geom else GEOMETRY_POLYGON)))
        kg.g.add((uri, semantic_group, Literal("water")))
        kg.g.add((uri, has_semantic_label, Literal("水域")))

    count = 0
    for i, w in enumerate(features):
        bsm = str(w.bsm).strip()
        ysdm = str(w.ysdm).strip()
        wid = bsm or f"water_poly_{i}"

        covered = water_overlap.get(wid, []) or water_overlap.get(bsm, [])
        geom = w.geometry
        is_line = isinstance(geom, dict) and geom.get("type") in ("LineString", "MultiLineString")

        if is_line:
            uri = EntityIdPolicy.uri("water_line", bsm or str(i) or f"line_{i}")
            EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
            kg.g.add((uri, RDF.type, EntityTypes.WaterBody))
            name = w.water_name or f"溪流_{bsm or i}"
            kg.g.add((uri, PLN.name, Literal(name)))
            kg.g.add((uri, PLN.water_type, Literal("河流")))
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            _add_water_dims(uri, is_line_geom=True)
            add_geo_feature_type(kg.g, uri)
            count += 1
        elif covered:
            uri = EntityIdPolicy.uri("water", bsm or f"overlap_{i}")
            EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
            kg.g.add((uri, RDF.type, EntityTypes.WaterBody))
            name = w.water_name or f"水体_{bsm or i}"
            kg.g.add((uri, PLN.name, Literal(name)))
            kg.g.add((uri, PLN.water_type, Literal(w.water_type or "水域")))
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            for cbsm in covered:
                for s in kg.g.subjects(PLN.bsm, Literal(cbsm)):
                    if (s, RDF.type, EntityTypes.Parcel) in kg.g:
                        kg.g.add((uri, Relations.derived_from, s))
            _add_water_dims(uri, is_line_geom=False)
            add_geo_feature_type(kg.g, uri)
            count += 1
        else:
            uri = EntityIdPolicy.uri("water", bsm or f"indep_{i}")
            EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
            kg.g.add((uri, RDF.type, EntityTypes.WaterBody))
            name = w.water_name or f"水体_{bsm or i}"
            kg.g.add((uri, PLN.name, Literal(name)))
            kg.g.add((uri, PLN.water_type, Literal(w.water_type or "水域")))
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            _add_water_dims(uri, is_line_geom=False)
            add_geo_feature_type(kg.g, uri)
            count += 1

    if count:
        logger.info("Added %d water bodies (overlap: %d covered parcels)", count, len(covered_bsms))
    return {"count": count, "entity_type": "WaterBody"}


def add_control_lines_from_typed(kg, points_layer, polygons_layer) -> None:
    count = 0
    for p in points_layer.get("hazard_points") or []:
        bsm = str(p.bsm).strip()
        ysdm = str(p.ysdm).strip()
        name = p.name or f"hazard_{count}"
        if bsm:
            uri = EntityIdPolicy.uri("hazard", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("hazard", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.ControlLine))
        kg.g.add((uri, PLN.name, Literal(str(name))))
        kg.g.add((uri, PLN.source, Literal("geological_hazard")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("geological_hazard_points")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        kg.g.add((uri, semantic_group, Literal("hazard_point")))
        if name:
            kg.g.add((uri, has_semantic_label, Literal(str(name))))
        add_geo_feature_type(kg.g, uri)
        count += 1
    for item in polygons_layer.get("hazard_control_lines") or []:
        bsm = str(item.bsm).strip()
        ysdm = str(item.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("hazard_line", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("hazard_line", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.ControlLine))
        kg.g.add((uri, PLN.name, Literal(f"灾害防控线_{bsm or count}")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("hazard_control_line")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        kg.g.add((uri, semantic_group, Literal("hazard")))
        add_geo_feature_type(kg.g, uri)
        count += 1
    for item in polygons_layer.get("flood_control_lines") or []:
        bsm = str(item.bsm).strip()
        ysdm = str(item.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("flood_line", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("flood_line", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.ControlLine))
        kg.g.add((uri, PLN.name, Literal(f"洪涝控制线_{bsm or count}")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("flood_control_line")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        kg.g.add((uri, semantic_group, Literal("hazard")))
        add_geo_feature_type(kg.g, uri)
        count += 1
    if count:
        logger.info("Added %d control lines", count)


def add_planning_elements_from_typed(kg, polygons_layer) -> None:
    count = 0
    for z in polygons_layer.get("land_use_zones") or []:
        bsm = str(z.bsm).strip()
        ysdm = str(z.ysdm).strip()
        code = ysdm or z.dlbm
        if bsm:
            uri = EntityIdPolicy.uri("tdyt", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("tdyt", ysdm or str(code), count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Zone))
        kg.g.add((uri, PLN.name, Literal(f"TDYT_{code}")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("land_use_zone")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        kg.g.add((uri, semantic_group, Literal("protection")))
        add_geo_feature_type(kg.g, uri)
        count += 1
    for item in polygons_layer.get("construction_ctrl_zones") or []:
        bsm = str(item.bsm).strip()
        ysdm = str(item.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("zone_jsydgzq", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("zone_jsydgzq", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Zone))
        kg.g.add((uri, PLN.name, Literal("建设用地管制区")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((uri, gis_type_ref, Literal("space_control_zone")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POLYGON)))
        kg.g.add((uri, semantic_group, Literal("construction")))
        kg.g.add((uri, has_semantic_label, Literal("建设用地管制区")))
        add_geo_feature_type(kg.g, uri)
        count += 1
    for _ in polygons_layer.get("planning_scope") if hasattr(polygons_layer, "get") else []:
        kg.g.add((PLN.village, PLN.has_planning_scope, Literal(True)))
        count += 1
    if count:
        logger.info("Added %d planning elements", count)


def add_annotations(kg, annotations: list):
    from app.modules.schema.types.spatial_types import CurrentFacility
    fc, vc = 0, 0
    for ann in annotations:
        cat = ann.category
        if cat == "村名":
            text = ann.text
            bsm = str(ann.bsm).strip()
            ysdm = str(ann.ysdm).strip()
            if text and hasattr(ann, "geometry"):
                coords = ann.geometry.get("coordinates", [0, 0])
                if bsm:
                    uri = EntityIdPolicy.uri("village_ann", bsm)
                else:
                    uri = EntityIdPolicy.fallback_uri("village_ann", ysdm, vc)
                EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
                kg.g.add((uri, RDF.type, EntityTypes.PlaceRef))
                kg.g.add((uri, PLN.name, Literal(text)))
                add_centroid(kg.g, uri, coords[0], coords[1])
                add_geo_feature_type(kg.g, uri)
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
            EntityIdPolicy.attach_bsm(kg.g, fac_uri, bsm)
            kg.g.add((fac_uri, RDF.type, EntityTypes.Facility))
            kg.g.add((fac_uri, PLN.name, Literal(facility.facility_name or "unknown")))
            kg.g.add((fac_uri, PLN.facility_type, Literal(facility.facility_type or "公共服务")))
            if hasattr(facility, "geometry"):
                coords = facility.geometry.get("coordinates", [0, 0])
                add_centroid(kg.g, fac_uri, coords[0], coords[1])
            kg.g.add((fac_uri, Relations.serves, Literal(facility.category or "public_service")))
            kg.g.add((fac_uri, Relations.sfWithin, PLN.village))
            kg.g.add((PLN.village, PLN.has_facility, fac_uri))
            add_geo_feature_type(kg.g, fac_uri)
            fc += 1
    if fc or vc:
        logger.info("Annotations: %d facilities, %d villages", fc, vc)
    return kg


@kg_builder("current_road", entity_type="Road", layer=1, order=20)
def add_roads(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    count = 0
    for road in features:
        bsm = str(road.bsm).strip()
        ysdm = str(road.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("road", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("road", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Road))
        name = road.road_name or f"道路_{bsm or count}"
        kg.g.add((uri, PLN.name, Literal(name)))
        length = road.shape_length or 0.0
        if length:
            kg.g.add((uri, PLN.length, Literal(length, datatype=XSD.double)))
        kg.g.add((uri, PLN.road_level, Literal(road.road_level or "村道")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((PLN.village, Relations.connects, uri))
        kg.g.add((uri, gis_type_ref, Literal("road")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE)))
        kg.g.add((uri, semantic_group, Literal("transport")))
        add_geo_feature_type(kg.g, uri)
        count += 1
    if count:
        logger.info("Added %d roads", count)
    return {"count": count, "entity_type": "Road"}


def add_terrain(kg, terrain_analysis=None):
    if terrain_analysis is None:
        return kg
    try:
        slope = getattr(terrain_analysis, "slope_area_pct", {}) or {}
        for k, v in slope.items():
            key = k.replace(">", "gt").replace("-", "_")
            kg.g.add((PLN.village, PLN[f"slope_{key}_pct"], Literal(v, datatype=XSD.double)))
        suit = getattr(terrain_analysis, "suitability_area_pct", {}) or {}
        for k, v in suit.items():
            kg.g.add((PLN.village, PLN[f"suitability_{k}_pct"], Literal(v, datatype=XSD.double)))
        logger.info("Added terrain: %d slope, %d suitability", len(slope), len(suit))
    except Exception as e:
        logger.warning("Terrain failed: %s", e)
    return kg


def add_residential_clusters_from_typed(kg, parcels, annotations=None) -> None:
    import math

    existing_clusters = []
    for s in kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
        name_lit = None
        lon_lit = None
        lat_lit = None
        for p, o in kg.g.predicate_objects(s):
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

    residential_codes = {"2121", "2122", "2123", "0702", "0701"}
    residential = []
    from app.modules.schema.types.spatial_types import CurrentLandUseParcel
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

    threshold = 0.0015
    visited = [False] * len(residential)
    clusters = []

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
                for _, cx, cy in cluster:
                    dx = residential[j][1] - cx
                    dy = residential[j][2] - cy
                    if dx * dx + dy * dy < threshold * threshold:
                        cluster.append(residential[j])
                        visited[j] = True
                        changed = True
                        break
        clusters.append(cluster)

    significant = [c for c in clusters if len(c) >= 3]

    seq = 0
    for cluster in significant:
        mean_lon = sum(m[1] for m in cluster) / len(cluster)
        mean_lat = sum(m[2] for m in cluster) / len(cluster)

        is_near_existing = False
        for _, ex_lon, ex_lat in existing_clusters:
            dx = mean_lon - ex_lon
            dy = mean_lat - ex_lat
            if dx * dx + dy * dy < threshold * threshold:
                is_near_existing = True
                break
        if is_near_existing:
            seq += 1
            continue

        name = f"居民点{seq + 1}"
        uri = EntityIdPolicy.fallback_uri("settlement", name, seq)
        kg.g.add((uri, RDF.type, EntityTypes.ResidentialCluster))
        kg.g.add((uri, PLN.name, Literal(name)))
        add_centroid(kg.g, uri, mean_lon, mean_lat)
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        add_geo_feature_type(kg.g, uri)

        for bsm, _, _ in cluster:
            for s in kg.g.subjects(PLN.bsm, Literal(bsm)):
                if (s, RDF.type, EntityTypes.Parcel) in kg.g:
                    kg.g.add((s, Relations.sfWithin, uri))

        seq += 1

    logger.info(
        "Identified %d residential settlements from %d residential parcels (%d clusters total)",
        len(significant), len(residential), len(clusters),
    )


@kg_builder("current_facility", entity_type="Facility", layer=1, order=10)
def add_facilities_from_typed(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    from app.modules.schema.types.spatial_types import CurrentFacility
    count = 0
    for f in features:
        if not isinstance(f, CurrentFacility):
            continue
        name = f.facility_name or f"facility_{count}"
        bsm = str(f.bsm).strip()
        ysdm = str(f.ysdm).strip()
        if bsm:
            uri = EntityIdPolicy.uri("facility", bsm)
        else:
            uri = EntityIdPolicy.fallback_uri("facility", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        kg.g.add((uri, RDF.type, EntityTypes.Facility))
        kg.g.add((uri, PLN.name, Literal(name)))
        ftype = f.facility_type or '公共服务'
        kg.g.add((uri, PLN.facility_type, Literal(ftype)))
        geom = f.geometry or {}
        coords = geom.get('coordinates', [0, 0]) if isinstance(geom, dict) else [0, 0]
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            add_centroid(kg.g, uri, coords[0], coords[1])
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((PLN.village, PLN.has_facility, uri))
        kg.g.add((uri, gis_type_ref, Literal("current_facility")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        kg.g.add((uri, semantic_group, Literal("facility")))
        if name:
            kg.g.add((uri, has_semantic_label, Literal(name)))
        add_geo_feature_type(kg.g, uri)
        count += 1
    if count:
        logger.info("Added %d facilities from typed parcels", count)
    return {"count": count, "entity_type": "Facility"}


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


def add_facilities_from_annotations(kg, annotations) -> None:
    count = 0
    for i, ann in enumerate(annotations):
        cat = ann.category or ""
        if cat != "现状设施点":
            continue

        text = ann.text or ""
        geom = ann.geometry
        if not geom or not isinstance(geom, dict):
            continue
        coords = geom.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue

        name, ftype = _FACILITY_TEXT_MAP.get(text, (text or f"设施_{i}", "公共服务"))
        uri = EntityIdPolicy.fallback_uri("facility", text or str(i), i)
        kg.g.add((uri, RDF.type, EntityTypes.Facility))
        kg.g.add((uri, PLN.name, Literal(name)))
        kg.g.add((uri, PLN.facility_type, Literal(ftype)))
        add_centroid(kg.g, uri, coords[0], coords[1])
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((PLN.village, PLN.has_facility, uri))
        kg.g.add((uri, gis_type_ref, Literal("current_facility")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
        kg.g.add((uri, semantic_group, Literal("facility")))
        if name:
            kg.g.add((uri, has_semantic_label, Literal(name)))
        add_geo_feature_type(kg.g, uri)
        count += 1

    if count:
        logger.info("Added %d facilities from annotations", count)