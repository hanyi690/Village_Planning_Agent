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
from .geo_helpers import add_bbox, add_centroid, add_geo_feature_type, add_source_geometry

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Predicate shortcuts
gis_type_ref = SemanticPredicates.gis_type_ref
geometry_kind = SemanticPredicates.geometry_kind
semantic_group = SemanticPredicates.semantic_group
has_semantic_label = SemanticPredicates.has_semantic_label
taxonomic_parent = SemanticPredicates.taxonomic_parent
legal_constraint = SemanticPredicates.legal_constraint
allowed_operations = SemanticPredicates.allowed_operations


def _source_feature_provenance(feature: Any) -> dict[str, Any]:
    raw = getattr(feature, "_raw", {}) or {}
    source_feature_id = str(raw.get("source_feature_id") or "").strip()
    if not source_feature_id:
        return {}
    return {
        "source_feature_id": source_feature_id,
        "source_uri": str(raw.get("source_uri") or "").strip(),
        "source_content_digest": str(raw.get("source_content_digest") or "").strip(),
        "source_feature_index": raw.get("source_feature_index"),
        "source_geometry_digest": str(raw.get("source_geometry_digest") or "").strip(),
    }


def _attach_source_feature_provenance(graph: Any, uri: URIRef, feature: Any) -> None:
    provenance = _source_feature_provenance(feature)
    if not provenance:
        return
    graph.add((uri, PLN.source_feature_id, Literal(provenance["source_feature_id"])))
    for key in (
        "source_uri",
        "source_content_digest",
        "source_geometry_digest",
    ):
        value = provenance.get(key)
        if value:
            graph.add((uri, PLN[key], Literal(value)))
    index = provenance.get("source_feature_index")
    if isinstance(index, int):
        graph.add((uri, PLN.source_feature_index, Literal(index, datatype=XSD.integer)))


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

        dlmc = getattr(p, "name", "") or ""
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

        # Wave A.1: taxonomic_parent / legal_constraint / allowed_operations are
        # cross-system derivations no longer performed in BaseFacts.

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


def _persist_feature_centroids(kg, features, entity_type) -> int:
    """按 bsm 把 bundle feature 质心持久化到 KG 实体（geo:hasCentroid）。

    原始几何留在 bundle（几何权威）；KG 存质心供拓扑推理（预计算拓扑模式）。
    """
    from app.infrastructure.kg.builder.geo_helpers import (
        add_centroid,
        feature_centroid,
    )

    written = 0
    for feature in features:
        bsm = str(getattr(feature, "bsm", "") or "").strip()
        if not bsm:
            continue
        centroid = feature_centroid(getattr(feature, "geometry", None))
        if centroid is None:
            continue
        for s in kg.g.subjects(PLN.bsm, Literal(bsm)):
            if (s, RDF.type, entity_type) in kg.g:
                add_centroid(kg.g, s, centroid[0], centroid[1])
                written += 1
                break
    return written

def _unique_water_name(w, bsm, i) -> str:
    """水体唯一名：真实名非泛化时保留，否则 水体_{bsm}（否则索引按"水域"合并）。"""
    raw = str(getattr(w, "water_name", "") or "").strip()
    generic = raw in ("", "水域", "水体", "河流", "坑塘", "水")
    if not generic:
        return raw
    return f"水体_{bsm or i}"

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
            name = getattr(w, "water_name", "") or f"溪流_{bsm or i}"
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
            name = _unique_water_name(w, bsm, i)
            kg.g.add((uri, PLN.name, Literal(name)))
            kg.g.add((uri, PLN.water_type, Literal(getattr(w, "water_type", "") or "水域")))
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
            name = _unique_water_name(w, bsm, i)
            kg.g.add((uri, PLN.name, Literal(name)))
            kg.g.add((uri, PLN.water_type, Literal(getattr(w, "water_type", "") or "水域")))
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            _add_water_dims(uri, is_line_geom=False)
            add_geo_feature_type(kg.g, uri)
            count += 1

    _persist_feature_centroids(kg, features, EntityTypes.WaterBody)
    if count:
        logger.info("Added %d water bodies (overlap: %d covered parcels)", count, len(covered_bsms))
    return {"count": count, "entity_type": "WaterBody"}


def add_control_lines_from_typed(kg, points_layer, polygons_layer) -> None:
    count = 0
    for p in points_layer.get("hazard_points") or []:
        bsm = str(p.bsm).strip()
        ysdm = str(p.ysdm).strip()
        name = getattr(p, "name", "") or f"hazard_{count}"
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
    from app.data.model.spatial_types import CurrentFacility
    fc, vc = 0, 0
    for ann in annotations:
        lt = str(getattr(ann, "layer_type", "") or "")  # getattr intentional: heterogeneous annotation objects
        cat = getattr(ann, "category", "") or ""
        raw = getattr(ann, "_raw", {}) or {}
        raw_cat = str(raw.get("category", "") or cat or "")
        is_village = cat == "村名" or raw_cat == "村名" or lt == "external_natural_village"
        is_facility = cat == "现状设施点" or raw_cat == "现状设施点" or lt in ("external_village_committee", "external_facility")
        if is_village:
            text = getattr(ann, "text", "") or str(raw.get("name_norm", "") or "").strip()
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
        elif is_facility:
            extra = ann.model_extra or {}
            facility = CurrentFacility.from_annotation_feature(
                {"properties": extra, "geometry": ann.geometry}
            ) if ann.model_extra else None
            if facility is None:
                name = getattr(ann, "text", "") or str(raw.get("name_norm", "") or "").strip()
                facility = CurrentFacility(
                    geometry=ann.geometry,
                    bsm=str(ann.bsm).strip(),
                    facility_type="公共服务",
                    facility_name=name or "unknown",
                    scale="",
                    service_radius=0.0,
                    category="public_service",
                )
            # The annotation adapter may construct a typed facility from
            # ``model_extra`` without carrying the canonical bundle identity.
            # Bundle BSM is authoritative and must be restored before the KG
            # URI/provenance is created; otherwise a real facility is left
            # with only a source-feature URI and cannot answer a BSM query.
            if not str(getattr(facility, "bsm", "") or "").strip():
                facility.bsm = str(getattr(ann, "bsm", "") or "").strip()
            bsm = str(facility.bsm).strip()
            ysdm = str(facility.ysdm).strip()
            source_feature_id = _source_feature_provenance(ann).get("source_feature_id")
            if bsm:
                fac_uri = EntityIdPolicy.uri("facility", bsm)
            elif source_feature_id:
                fac_uri = URIRef(source_feature_id)
            else:
                fac_uri = EntityIdPolicy.fallback_uri("facility", ysdm, fc)
            EntityIdPolicy.attach_bsm(kg.g, fac_uri, bsm)
            _attach_source_feature_provenance(kg.g, fac_uri, ann)
            kg.g.add((fac_uri, RDF.type, EntityTypes.Facility))
            kg.g.add((fac_uri, PLN.name, Literal(facility.facility_name or "unknown")))
            kg.g.add((fac_uri, PLN.facility_type, Literal(facility.facility_type or "公共服务")))
            if hasattr(facility, "geometry"):
                coords = facility.geometry.get("coordinates", [0, 0])
                add_centroid(kg.g, fac_uri, coords[0], coords[1])
                add_source_geometry(
                    kg.g,
                    fac_uri,
                    facility.geometry,
                    allowed_types=("Point",),
                )
            kg.g.add((fac_uri, PLN.service_category, Literal(facility.category or "public_service")))
            kg.g.add((fac_uri, Relations.sfWithin, PLN.village))
            kg.g.add((PLN.village, PLN.has_facility, fac_uri))
            add_geo_feature_type(kg.g, fac_uri)
            fc += 1
        elif lt == "external_road_label":
            name = getattr(ann, "text", "") or str(raw.get("name", "") or raw.get("name_norm", "") or "").strip()
            bsm = str(ann.bsm).strip()
            ysdm = str(ann.ysdm).strip()
            uri = EntityIdPolicy.fallback_uri("external_road", ysdm, vc)
            EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
            # A named road POI is a point reference, not a current road
            # geometry.  Keep it spatially queryable without promoting it to
            # the executable Road business type.
            kg.g.add((uri, RDF.type, EntityTypes.PlaceRef))
            kg.g.add((uri, PLN.name, Literal(name or f"道路_{bsm or vc}")))
            coords = ann.geometry.get("coordinates", [0, 0])
            add_centroid(kg.g, uri, coords[0], coords[1])
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            kg.g.add((uri, gis_type_ref, Literal("external_road_name")))
            kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
            kg.g.add((uri, semantic_group, Literal("transport_reference")))
            kg.g.add((uri, has_semantic_label, Literal("道路名称注记")))
            add_geo_feature_type(kg.g, uri)
            vc += 1
        elif lt == "external_water_label":
            name = getattr(ann, "text", "") or str(raw.get("name", "") or raw.get("name_norm", "") or "").strip()
            bsm = str(ann.bsm).strip()
            ysdm = str(ann.ysdm).strip()
            uri = EntityIdPolicy.fallback_uri("external_water", ysdm, fc)
            EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
            # A named water POI is likewise a point reference.  It does not
            # prove that a water polygon or water line exists in the bundle.
            kg.g.add((uri, RDF.type, EntityTypes.PlaceRef))
            kg.g.add((uri, PLN.name, Literal(name or f"水体_{bsm or fc}")))
            coords = ann.geometry.get("coordinates", [0, 0])
            add_centroid(kg.g, uri, coords[0], coords[1])
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            kg.g.add((uri, gis_type_ref, Literal("external_water_name")))
            kg.g.add((uri, geometry_kind, Literal(GEOMETRY_POINT)))
            kg.g.add((uri, semantic_group, Literal("water_reference")))
            kg.g.add((uri, has_semantic_label, Literal("水体名称注记")))
            add_geo_feature_type(kg.g, uri)
            fc += 1
    if fc or vc:
        logger.info("Annotations: %d facilities, %d villages", fc, vc)
    return kg


@kg_builder("current_road", entity_type="Road", layer=1, order=20)
def add_roads(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    count = 0
    skipped_invalid_geometry = 0
    skipped_wrong_layer = 0
    for road in features:
        if str(gtype_ref).strip() != "current_road":
            skipped_wrong_layer += 1
            continue
        geometry = getattr(road, "geometry", None)
        geometry_type = geometry.get("type") if isinstance(geometry, dict) else ""
        if geometry_type not in ("LineString", "MultiLineString"):
            skipped_invalid_geometry += 1
            continue
        bsm = str(road.bsm).strip()
        ysdm = str(road.ysdm).strip()
        source_feature_id = _source_feature_provenance(road).get("source_feature_id")
        if bsm:
            uri = EntityIdPolicy.uri("road", bsm)
        elif source_feature_id:
            uri = URIRef(source_feature_id)
        else:
            uri = EntityIdPolicy.fallback_uri("road", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        _attach_source_feature_provenance(kg.g, uri, road)
        kg.g.add((uri, RDF.type, EntityTypes.Road))
        name = getattr(road, "road_name", "") or f"道路_{bsm or count}"
        kg.g.add((uri, PLN.name, Literal(name)))
        length = getattr(road, "shape_length", "") or 0.0
        if length:
            kg.g.add((uri, PLN.length, Literal(length, datatype=XSD.double)))
        kg.g.add((uri, PLN.road_level, Literal(getattr(road, "road_level", "") or "村道")))
        kg.g.add((uri, Relations.sfWithin, PLN.village))
        kg.g.add((PLN.village, Relations.connects, uri))
        kg.g.add((uri, gis_type_ref, Literal("road")))
        kg.g.add((uri, geometry_kind, Literal(GEOMETRY_LINE)))
        kg.g.add((uri, semantic_group, Literal("transport")))
        add_source_geometry(
            kg.g,
            uri,
            getattr(road, "geometry", None),
            allowed_types=("LineString", "MultiLineString"),
        )
        add_geo_feature_type(kg.g, uri)
        count += 1
    _persist_feature_centroids(kg, features, EntityTypes.Road)
    if count:
        logger.info("Added %d roads", count)
    if skipped_invalid_geometry or skipped_wrong_layer:
        logger.warning(
            "Skipped non-road source features: invalid_geometry=%d wrong_layer=%d",
            skipped_invalid_geometry,
            skipped_wrong_layer,
        )
    return {
        "count": count,
        "entity_type": "Road",
        "skipped_invalid_geometry": skipped_invalid_geometry,
        "skipped_wrong_layer": skipped_wrong_layer,
    }


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


@kg_builder("current_facility", entity_type="Facility", layer=1, order=10)
def add_facilities_from_typed(kg, features, *, gtype_ref: str, entry, ctx: BuildContext) -> dict:
    from app.data.model.spatial_types import CurrentFacility
    count = 0
    for f in features:
        if not isinstance(f, CurrentFacility):
            continue
        name = getattr(f, "facility_name", "") or f"facility_{count}"
        bsm = str(f.bsm).strip()
        ysdm = str(f.ysdm).strip()
        source_feature_id = _source_feature_provenance(f).get("source_feature_id")
        if bsm:
            uri = EntityIdPolicy.uri("facility", bsm)
        elif source_feature_id:
            uri = URIRef(source_feature_id)
        else:
            uri = EntityIdPolicy.fallback_uri("facility", ysdm, count)
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        _attach_source_feature_provenance(kg.g, uri, f)
        kg.g.add((uri, RDF.type, EntityTypes.Facility))
        kg.g.add((uri, PLN.name, Literal(name)))
        ftype = getattr(f, "facility_type", "") or '公共服务'
        kg.g.add((uri, PLN.facility_type, Literal(ftype)))
        geom = f.geometry or {}
        coords = geom.get('coordinates', [0, 0]) if isinstance(geom, dict) else [0, 0]
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            add_centroid(kg.g, uri, coords[0], coords[1])
        add_source_geometry(
            kg.g,
            uri,
            geom,
            allowed_types=("Point",),
        )
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


def add_facilities_from_annotations(kg, annotations) -> None:
    count = 0
    for i, ann in enumerate(annotations):
        # annotation 来自多数据源（本地 geojson / Tianditu WFS），属性集不齐 —
        # category/text 用防御式访问（Pydantic extra 未存该字段时避免 AttributeError）
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

        # Keep the source label verbatim.  A one-character annotation is not
        # a canonical facility meaning; an accepted L1/KG semantic overlay
        # may refine it later without mutating this source node.
        name = text or f"设施_{i}"
        ftype = "未分类设施"
        bsm = str(getattr(ann, "bsm", "") or "").strip()
        ysdm = str(getattr(ann, "ysdm", "") or "").strip()
        source_feature_id = _source_feature_provenance(ann).get("source_feature_id")
        if bsm:
            uri = EntityIdPolicy.uri("facility", bsm)
        elif source_feature_id:
            uri = URIRef(source_feature_id)
        else:
            uri = EntityIdPolicy.fallback_uri("facility", ysdm or text or str(i), i)
        kg.g.add((uri, RDF.type, EntityTypes.Facility))
        EntityIdPolicy.attach_bsm(kg.g, uri, bsm)
        _attach_source_feature_provenance(kg.g, uri, ann)
        kg.g.add((uri, PLN.name, Literal(name)))
        kg.g.add((uri, PLN.facility_type, Literal(ftype)))
        add_centroid(kg.g, uri, coords[0], coords[1])
        add_source_geometry(
            kg.g,
            uri,
            geom,
            allowed_types=("Point",),
        )
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
