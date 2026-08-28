from __future__ import annotations

from typing import Any

from app.contracts.ports.spatial_query import SpatialQueryPort
from app.contracts.ground.spatial_reference_contracts import (
    CandidateSet, SpatialReferenceSpec,
)


class KGSpatialQueryAdapter(SpatialQueryPort):
    def __init__(self, kg):
        self._kg = kg

    def resolve_candidates(self, run_id: str, spec: SpatialReferenceSpec) -> CandidateSet:
        try:
            from app.infrastructure.kg.queries.spatial_ref import resolve_candidates
            return resolve_candidates(self._kg, spec)
        except Exception:
            return CandidateSet()

    def query_by_bbox(self, run_id: str, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
        return _query_entities_intersecting_bbox(self._kg, bbox)

    def query_by_geometry(self, run_id: str, wkt: str) -> list[dict[str, Any]]:
        return _query_entities_by_wkt(self._kg, wkt)

    def compute_overlap(self, run_id: str, wkt_a: str, wkt_b: str) -> float:
        try:
            from shapely import wkt as shapely_wkt

            geometry_a = shapely_wkt.loads(wkt_a)
            geometry_b = shapely_wkt.loads(wkt_b)
            area_a = float(geometry_a.area)
            area_b = float(geometry_b.area)
            if area_a > 0.0 and area_b > 0.0:
                return float(geometry_a.intersection(geometry_b).area / min(area_a, area_b))
            return 1.0 if geometry_a.intersects(geometry_b) else 0.0
        except Exception:
            return 0.0

    def nearest_features(self, run_id: str, wkt: str, layer: str, k: int = 5) -> list[dict[str, Any]]:
        return _nearest_features(self._kg, wkt, layer, k)


def _query_entities_intersecting_bbox(kg, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    from rdflib import RDF, URIRef

    from app.infrastructure.kg.ontology import EntityTypes
    from app.infrastructure.kg.builder.geo_helpers import parse_wkt_bbox

    if bbox is None or len(bbox) != 4:
        return []
    minx, miny, maxx, maxy = (float(v) for v in bbox)
    results = []
    seen = set()
    entity_types = list(EntityTypes.spatial_l1())
    for entity_type in entity_types:
        for subj in kg.g.subjects(RDF.type, entity_type):
            if str(subj) in seen:
                continue
            seen.add(str(subj))
            info = _entity_geometry(kg, subj)
            if info is None:
                continue
            eb = parse_wkt_bbox(info["bbox"])
            if eb is None:
                continue
            if not (eb[2] < minx or eb[0] > maxx or eb[3] < miny or eb[1] > maxy):
                results.append(info)
    return results


def _query_entities_by_wkt(kg, wkt: str) -> list[dict[str, Any]]:
    from shapely import wkt as shapely_wkt
    from app.infrastructure.kg.builder.geo_helpers import parse_wkt_bbox

    bbox = parse_wkt_bbox(wkt)
    if bbox is None:
        return []
    candidates = _query_entities_intersecting_bbox(kg, tuple(bbox))
    try:
        query_geometry = shapely_wkt.loads(wkt)
    except Exception:
        return candidates
    result = []
    for info in candidates:
        try:
            geometry = shapely_wkt.loads(str(info.get("wkt") or ""))
            if geometry.intersects(query_geometry):
                result.append(info)
        except Exception:
            result.append(info)
    return result


def _nearest_features(kg, wkt: str, layer: str, k: int = 5) -> list[dict[str, Any]]:
    from app.infrastructure.kg.builder.geo_helpers import parse_wkt_point

    point = parse_wkt_point(wkt)
    if point is None:
        return []
    candidates = _layer_members(kg, layer)
    scored = []
    for info in candidates:
        centroid = _entity_centroid(kg, info.get("entity_ref"))
        if centroid is None:
            continue
        dist = (point[0] - centroid[0]) ** 2 + (point[1] - centroid[1]) ** 2
        scored.append((dist, info))
    scored.sort(key=lambda x: x[0])
    return [info for _, info in scored[:k]]


def _layer_members(kg, layer: str) -> list[dict[str, Any]]:
    from app.infrastructure.kg.ontology import PLN

    lg_uri = PLN[f"GisLayerSet_{layer}"]
    members = []
    for _, _, member in kg.g.triples((lg_uri, PLN.contains_entity, None)):
        info = _entity_geometry(kg, member)
        if info is not None:
            members.append(info)
    return members


def _entity_geometry(kg, entity_ref):
    from app.infrastructure.kg.ontology import GeoPredicates, PLN

    wkt = ""
    geometry_node = kg.g.value(entity_ref, GeoPredicates.hasGeometry)
    if geometry_node is not None:
        wkt_literal = kg.g.value(geometry_node, GeoPredicates.asWKT)
        if wkt_literal is not None:
            wkt = str(wkt_literal)
    bbox_geom = kg.g.value(entity_ref, GeoPredicates.hasBoundingBox)
    bbox = ""
    if bbox_geom is not None:
        wkt_lit = kg.g.value(bbox_geom, GeoPredicates.asWKT)
        if wkt_lit is not None:
            bbox = str(wkt_lit)
    bsm = ""
    for _, _, o in kg.g.triples((entity_ref, PLN.bsm, None)):
        bsm = str(o)
        break
    if not bbox and wkt:
        from app.infrastructure.kg.builder.geo_helpers import parse_wkt_bbox

        parsed = parse_wkt_bbox(wkt)
        bbox = f"POLYGON(({parsed[0]} {parsed[1]},{parsed[2]} {parsed[1]},{parsed[2]} {parsed[3]},{parsed[0]} {parsed[3]},{parsed[0]} {parsed[1]}))" if parsed else ""
    return {
        "entity_ref": str(entity_ref),
        "bbox": bbox,
        "bsm": bsm,
        "wkt": wkt,
    }


def _entity_centroid(kg, entity_ref):
    from rdflib import URIRef

    from app.infrastructure.kg.builder.geo_helpers import parse_wkt_point

    from app.infrastructure.kg.ontology import GeoPredicates

    geom = kg.g.value(URIRef(entity_ref), GeoPredicates.hasCentroid)
    if geom is None:
        return None
    wkt_lit = kg.g.value(geom, GeoPredicates.asWKT)
    if wkt_lit is None:
        return None
    return parse_wkt_point(str(wkt_lit))


def _geometry_area(wkt: str) -> float:
    try:
        from shapely import wkt as shapely_wkt

        geometry = shapely_wkt.loads(wkt)
    except Exception:
        return 0.0
    return float(geometry.area)
