"""GeoSPARQL WKT helper functions for building standard geometry literals.

Replaces custom pln:lon/pln:lat with geo:hasCentroid + geo:asWKT.
Replaces pln:bbox_minx/miny/maxx/maxy with geo:hasBoundingBox + geo:asWKT.
"""
import re
from typing import Optional, Tuple, List

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

from ..ontology import GEO, GeoPredicates


def format_wkt_point(lon: float, lat: float) -> str:
    return f"POINT({round(lon, 6)} {round(lat, 6)})"


def format_wkt_bbox(minx: float, miny: float, maxx: float, maxy: float) -> str:
    return (
        f"POLYGON(("
        f"{round(minx, 6)} {round(miny, 6)}, "
        f"{round(maxx, 6)} {round(miny, 6)}, "
        f"{round(maxx, 6)} {round(maxy, 6)}, "
        f"{round(minx, 6)} {round(maxy, 6)}, "
        f"{round(minx, 6)} {round(miny, 6)}"
        f"))"
    )


def parse_wkt_point(wkt_str: str) -> Optional[Tuple[float, float]]:
    if not wkt_str:
        return None
    match = re.match(r"POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", wkt_str.strip(), re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except (ValueError, TypeError):
        return None


def parse_wkt_bbox(wkt_str: str) -> Optional[List[float]]:
    if not wkt_str:
        return None
    match = re.findall(r"(-?[\d.]+)\s+(-?[\d.]+)", str(wkt_str))
    if len(match) < 4:
        return None
    try:
        coords = [(float(x), float(y)) for x, y in match]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        return [min(lons), min(lats), max(lons), max(lats)]
    except (ValueError, TypeError):
        return None


def add_centroid(graph: Graph, entity_uri: URIRef, lon: float, lat: float) -> None:
    geom = BNode()
    graph.add((entity_uri, GeoPredicates.hasCentroid, geom))
    graph.add((geom, GeoPredicates.asWKT, Literal(format_wkt_point(lon, lat), datatype=GeoPredicates.wktLiteral)))


def add_bbox(graph: Graph, entity_uri: URIRef, minx: float, miny: float, maxx: float, maxy: float) -> None:
    geom = BNode()
    graph.add((entity_uri, GeoPredicates.hasBoundingBox, geom))
    graph.add((geom, GeoPredicates.asWKT, Literal(format_wkt_bbox(minx, miny, maxx, maxy), datatype=GeoPredicates.wktLiteral)))


def add_geo_feature_type(graph: Graph, entity_uri: URIRef) -> None:
    graph.add((entity_uri, RDF.type, GEO.Feature))