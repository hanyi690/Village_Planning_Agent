"""Layer 2: spatial relation builders (computed by the spatial layer, injected via parcel_relations).

All functions are module-level, operating on a PlanningKG instance passed as `kg`.

v5.0: Relation quantitative attributes moved to SemanticMemoryStore.
"""
from app.infrastructure.logging import get_logger
from ..ontology import PLN, PLN_NS, GEO, EntityTypes, Relations, SemanticPredicates, GeoPredicates
from ..memory import RelationAnnotation
from .geo_helpers import parse_wkt_point, add_centroid, add_geo_feature_type

from rdflib import Literal, RDF, URIRef
from rdflib.namespace import XSD

logger = get_logger(__name__)

# Import the cross_type computation helper
import math


def add_parcel_relations(kg, relations) -> None:
    """Add parcel-to-parcel spatial relations (touches, nearby, connected) to the RDF graph.
    
    Relation quantitative attributes (shared_boundary_length, centroid_distance,
    road_segment_length, via_road) are stored in SemanticMemoryStore instead of
    as RDF triples. This follows the v5.0 pattern: RDF graph stores pure relations,
    SemanticMemoryStore stores quantitative details.
    """
    from app.spatial.model.geometry import ParcelRelations
    if not relations or not isinstance(relations, ParcelRelations):
        return
    count = 0
    for t in relations.touches:
        a = _parcel_uri_by_bsm_dlbm(kg, t.bsm_a, t.dlbm_a)
        b = _parcel_uri_by_bsm_dlbm(kg, t.bsm_b, t.dlbm_b)
        if a and b:
            kg.g.add((a, Relations.sfTouches, b))
            kg.g.add((b, Relations.sfTouches, a))
            if t.shared_boundary_length_m:
                detail = {"shared_boundary_m": t.shared_boundary_length_m}
                kg.memory.add_relation_annotation(RelationAnnotation(
                    subject_uri=str(a), predicate=str(Relations.sfTouches),
                    object_uri=str(b), description="", derived_from="spatial_ops_computed",
                    quantitative_detail=detail,
                ))
            count += 1
    for n in relations.nearby:
        a = _parcel_uri_by_bsm_dlbm(kg, n.bsm_a, n.dlbm_a)
        b = _parcel_uri_by_bsm_dlbm(kg, n.bsm_b, n.dlbm_b)
        if a and b:
            kg.g.add((a, Relations.nearby, b))
            if n.centroid_distance_m:
                detail = {"centroid_distance_m": n.centroid_distance_m}
                kg.memory.add_relation_annotation(RelationAnnotation(
                    subject_uri=str(a), predicate=str(Relations.nearby),
                    object_uri=str(b), description="", derived_from="spatial_ops_computed",
                    quantitative_detail=detail,
                ))
            count += 1
    for c in relations.connected:
        a = _parcel_uri_by_bsm_dlbm(kg, c.bsm_a, "")
        b = _parcel_uri_by_bsm_dlbm(kg, c.bsm_b, "")
        if a and b:
            kg.g.add((a, Relations.connected_via_road, b))
            detail = {}
            if c.road_length_m:
                detail["road_segment_m"] = c.road_length_m
            if c.road_bsm:
                detail["via_road"] = c.road_bsm
            if detail:
                kg.memory.add_relation_annotation(RelationAnnotation(
                    subject_uri=str(a), predicate=str(Relations.connected_via_road),
                    object_uri=str(b), description="", derived_from="spatial_ops_computed",
                    quantitative_detail=detail,
                ))
            count += 1

    for pbsm, rbsm in relations.parcel_road_intersects:
        pu = _parcel_uri_by_bsm_dlbm(kg, pbsm, "")
        ru = _road_uri_by_bsm(kg, rbsm)
        if pu and ru:
            kg.g.add((ru, Relations.sfIntersects, pu))
            kg.g.add((pu, Relations.sfIntersects, ru))
            count += 1

    for pbsm, wid in relations.parcel_water_touches:
        pu = _parcel_uri_by_bsm_dlbm(kg, pbsm, "")
        wu = _entity_uri_by_bsm(kg, EntityTypes.WaterBody, wid)
        if not wu:
            for s in kg.g.subjects(RDF.type, EntityTypes.WaterBody):
                for _, _, o in kg.g.triples((s, PLN.name, Literal(wid))):
                    wu = s
                    break
                if wu:
                    break
        if pu and wu:
            kg.g.add((pu, Relations.sfTouches, wu))
            kg.g.add((wu, Relations.sfTouches, pu))
            count += 1

    if count:
        logger.info("Added %d parcel relations (incl. cross-layer)", count)


def add_cross_type_relations(kg, cross_type_relations) -> None:
    """Add cross-type spatial relations (facility-in-parcel, road-intersects-parcel, etc)."""
    if cross_type_relations is None:
        cross_type_relations = compute_cross_type_heuristic(kg)

    count = 0
    skipped = 0

    def _entity_in_graph(uri):
        try:
            for _ in kg.g.triples((uri, None, None)):
                return True
            return False
        except Exception:
            return False

    for subj_str, obj_str in cross_type_relations.get("located_in", []):
        subj = _to_uri_safe(subj_str)
        obj = _to_uri_safe(obj_str)
        if subj and obj and _entity_in_graph(subj) and _entity_in_graph(obj):
            kg.g.add((subj, Relations.sfWithin, obj))
            count += 1
        else:
            skipped += 1

    for item in cross_type_relations.get("intersects", []):
        subj_str, obj_str = item[0], item[1]
        overlap_pct = item[2] if len(item) > 2 else None
        subj = _to_uri_safe(subj_str)
        obj = _to_uri_safe(obj_str)
        if subj and obj and _entity_in_graph(subj) and _entity_in_graph(obj):
            kg.g.add((subj, Relations.sfIntersects, obj))
            if overlap_pct:
                kg.memory.add_relation_annotation(RelationAnnotation(
                    subject_uri=str(subj), predicate=str(Relations.sfIntersects),
                    object_uri=str(obj), description="", derived_from="spatial_ops_computed",
                    quantitative_detail={"overlap_pct": float(overlap_pct)},
                ))
            count += 1
        else:
            skipped += 1

    for subj_str, obj_str in cross_type_relations.get("contains", []):
        subj = _to_uri_safe(subj_str)
        obj = _to_uri_safe(obj_str)
        if subj and obj and _entity_in_graph(subj) and _entity_in_graph(obj):
            kg.g.add((subj, Relations.sfContains, obj))
            count += 1
        else:
            skipped += 1

    # Additional bundle-backed topology predicates share the same KG relation
    # store.  The tuple's optional third value is a metric (metres for ``near``
    # and percentage for ``overlaps``); geometry itself is never copied into
    # the RDF graph or invented by this layer.
    generic_relations = {
        "same_coordinate": Relations.same_coordinate,
        "co_located": Relations.co_located,
        "near": Relations.near,
        "touches": Relations.sfTouches,
        "overlaps": Relations.overlaps,
    }
    symmetric = set(generic_relations) - {"overlaps"}
    relation_meta = cross_type_relations.get("_meta", {}) or {}
    for key, predicate in generic_relations.items():
        for item in cross_type_relations.get(key, []) or []:
            if len(item) < 2:
                continue
            subj = _to_uri_safe(item[0])
            obj = _to_uri_safe(item[1])
            if not (subj and obj and _entity_in_graph(subj) and _entity_in_graph(obj)):
                skipped += 1
                continue
            kg.g.add((subj, predicate, obj))
            metric = item[2] if len(item) > 2 else None
            detail = dict(relation_meta.get(key, {}) or {})
            if metric is not None:
                detail["metric"] = float(metric)
                detail["metric_unit"] = "m" if key == "near" else "percent"
            detail.setdefault("method", "bundle_geometry_strtree")
            detail.setdefault("crs", "EPSG:3857")
            detail.setdefault("tolerance", 0.01 if key == "same_coordinate" else 0.0)
            kg.memory.add_relation_annotation(RelationAnnotation(
                subject_uri=str(subj),
                predicate=str(predicate),
                object_uri=str(obj),
                description="",
                derived_from="spatial_ops_computed",
                quantitative_detail=detail,
            ))
            if key in symmetric:
                kg.g.add((obj, predicate, subj))
            count += 1

    if count:
        logger.info("Added %d cross-type spatial relations (skipped %d)", count, skipped)


def compute_cross_type_heuristic(kg) -> dict:
    """Heuristic cross-type relation computation using centroid proximity (no shapely).

    Updated for v5.0: reads centroids from geo:hasCentroid/geo:asWKT instead of pln:lon/pln:lat.
    """
    located_in_relations = []
    parcel_centroids = []
    for s in kg.g.subjects(RDF.type, EntityTypes.Parcel):
        geom = kg.g.value(s, GeoPredicates.hasCentroid)
        if geom:
            wkt = kg.g.value(geom, GeoPredicates.asWKT)
            if wkt:
                pt = parse_wkt_point(str(wkt))
                if pt:
                    parcel_centroids.append((s, pt[0], pt[1]))

    for pt in kg.g.subjects(RDF.type, EntityTypes.Facility):
        geom = kg.g.value(pt, GeoPredicates.hasCentroid)
        if not geom:
            continue
        wkt = kg.g.value(geom, GeoPredicates.asWKT)
        if not wkt:
            continue
        fpt = parse_wkt_point(str(wkt))
        if fpt is None or not parcel_centroids:
            continue
        pt_lon, pt_lat = fpt
        best_uri = None
        best_dist = float("inf")
        for puri, clon, clat in parcel_centroids:
            d = (pt_lon - clon) ** 2 + (pt_lat - clat) ** 2
            if d < best_dist:
                best_dist = d
                best_uri = puri
        if best_uri is not None and best_dist < 0.005:
            located_in_relations.append((str(pt), str(best_uri)))

    return {"located_in": located_in_relations, "intersects": [], "contains": []}


def _parcel_uri_by_bsm_dlbm(kg, bsm: str, dlbm: str):
    for s, _, _ in kg.g.triples((None, PLN.bsm, Literal(bsm))):
        if (s, RDF.type, EntityTypes.Parcel) not in kg.g:
            continue
        return s
    return None


def _road_uri_by_bsm(kg, bsm: str):
    for s in kg.g.subjects(RDF.type, EntityTypes.Road):
        for _, _, o in kg.g.triples((s, PLN.bsm, Literal(bsm))):
            return s
    for s in kg.g.subjects(RDF.type, EntityTypes.Road):
        for _, _, o in kg.g.triples((s, PLN.name, Literal(bsm))):
            return s
    return None


def _entity_uri_by_bsm(kg, entity_type, bsm: str):
    for s in kg.g.subjects(RDF.type, entity_type):
        for _, _, o in kg.g.triples((s, PLN.bsm, Literal(bsm))):
            return s
    return None


def _to_uri_safe(uri_str: str):
    if not uri_str:
        return None
    if uri_str.startswith("http"):
        return URIRef(uri_str)
    if uri_str.startswith("pln:"):
        return URIRef(PLN_NS + uri_str[4:])
    return URIRef(PLN_NS + uri_str)
