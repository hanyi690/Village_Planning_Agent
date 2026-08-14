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


def feature_centroid(geometry) -> Optional[Tuple[float, float]]:
    """从 GeoJSON geometry dict 计算质心（无 shapely 依赖，确定性）。

    Point → 坐标；LineString → 线段中点；Polygon → 外环顶点平均。
    返回 (lon, lat) 或 None。
    """
    if not isinstance(geometry, dict):
        return None
    gtype = geometry.get("type", "")
    coords = geometry.get("coordinates")
    if not coords:
        return None

    def _avg(points) -> Optional[Tuple[float, float]]:
        pts = [(float(x), float(y)) for x, y in points if len(points) and isinstance(x, (int, float)) and isinstance(y, (int, float))]
        pts = [(float(x), float(y)) for x, y in points]
        if not pts:
            return None
        return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))

    try:
        if gtype in ("Point",):
            return (float(coords[0]), float(coords[1]))
        if gtype in ("LineString", "MultiPoint"):
            pts = coords if gtype == "LineString" else coords
            if len(pts) == 1:
                return (float(pts[0][0]), float(pts[0][1]))
            a, b = pts[0], pts[-1]
            return ((float(a[0]) + float(b[0])) / 2.0, (float(a[1]) + float(b[1])) / 2.0)
        if gtype == "Polygon":
            ring = coords[0] if coords else []
            return _avg(ring)
        if gtype == "MultiPolygon":
            rings = [r for poly in coords for r in (poly[0] if poly else [])]
            return _avg(rings)
        if gtype == "MultiLineString":
            return _avg([p for line in coords for p in line])
    except (TypeError, ValueError, IndexError):
        return None
    return None