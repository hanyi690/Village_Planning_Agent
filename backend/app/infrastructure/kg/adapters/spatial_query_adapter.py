from __future__ import annotations

from typing import Any

from app.contracts.ports.spatial_query import SpatialQueryPort
from app.contracts.spatial.spatial_reference_contracts import (
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
        area_a = _geometry_area(wkt_a)
        area_b = _geometry_area(wkt_b)
        if area_a <= 0.0 or area_b <= 0.0:
            return 0.0
        return min(area_a, area_b) / max(area_a, area_b)

    def nearest_features(self, run_id: str, wkt: str, layer: str, k: int = 5) -> list[dict[str, Any]]:
        return _nearest_features(self._kg, wkt, layer, k)


def _query_entities_intersecting_bbox(kg, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    from rdflib import RDF, URIRef

    from app.infrastructure.kg.ontology import EntityTypes, GeoPredicates, PLN
    from app.infrastructure.kg.builder.geo_helpers import parse_wkt_bbox

    if bbox is None or len(bbox) != 4:
        return []
    minx, miny, maxx, maxy = (float(v) for v in bbox)
    results = []
    for subj in kg.g.subjects(RDF.type, EntityTypes.Parcel):
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
    from app.infrastructure.kg.builder.geo_helpers import parse_wkt_bbox

    bbox = parse_wkt_bbox(wkt)
    if bbox is None:
        return []
    return _query_entities_intersecting_bbox(kg, tuple(bbox))


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
    return {"entity_ref": str(entity_ref), "bbox": bbox, "bsm": bsm}


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
    from app.infrastructure.kg.builder.geo_helpers import parse_wkt_bbox

    bbox = parse_wkt_bbox(wkt)
    if bbox is None:
        return 0.0
    return abs((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
