"""设施/水体/道路 ↔ 最近村簇 拓扑（serves/nearby）。

空间推理地基（设计 §4.1 + SAWGraph 预计算拓扑）：让“社前村的祠堂”能通过 KG
预计算关系定位到该村簇内的设施点。只写 KG 关系边；几何留在 bundle，KG 存质心。
"""
from __future__ import annotations

import math
from typing import Any, List, Optional, Tuple

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
_MAX_DISTANCE_DEG = 0.02  # ~2km 村簇归属半径


def _centroid(kg: Any, uri: Any) -> Optional[Tuple[float, float]]:
    """geo:hasCentroid/hasGeometry → asWKT POINT；回退 pln:lon/lat。"""
    try:
        from rdflib import URIRef

        from app.infrastructure.kg.ontology import GeoPredicates, PLN
        from app.spatial.grounding.coordinate_identity import point_xy

        subj = URIRef(uri)
        for predicate in (GeoPredicates.hasCentroid, GeoPredicates.hasGeometry):
            node = kg.g.value(subj, predicate)
            if node is None:
                continue
            wkt = kg.g.value(node, GeoPredicates.asWKT)
            xy = point_xy(str(wkt))
            if xy is not None:
                return xy
        lon = kg.g.value(subj, PLN.lon)
        lat = kg.g.value(subj, PLN.lat)
        if lon is not None and lat is not None:
            return (float(lon), float(lat))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[entity-cluster-topology] centroid read failed: %s", exc)
    return None


def _cluster_centroids(kg: Any) -> List[Tuple[Any, Tuple[float, float]]]:
    try:
        from rdflib import RDF

        from app.infrastructure.kg.ontology import EntityTypes

        out = []
        for cluster in kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
            c = _centroid(kg, cluster)
            if c is not None:
                out.append((cluster, c))
        return out
    except Exception:  # noqa: BLE001
        return []


def _dist_deg(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def add_entity_cluster_topology(kg: Any, max_distance_deg: float = _MAX_DISTANCE_DEG) -> int:
    """为设施/水体/道路实体写最近村簇关系（serves/nearby）。返回写入边数。"""
    try:
        from rdflib import RDF

        from app.infrastructure.kg.ontology import EntityTypes, Relations

        clusters = _cluster_centroids(kg)
        if not clusters:
            return 0
        written = 0
        for etype, primary_rel in (
            (EntityTypes.Facility, Relations.serves),
            (EntityTypes.WaterBody, Relations.nearby),
            (EntityTypes.Road, Relations.nearby),
        ):
            for s in kg.g.subjects(RDF.type, etype):
                c = _centroid(kg, s)
                if c is None:
                    continue
                nearest_uri, nearest_centroid = min(
                    clusters,
                    key=lambda item: _dist_deg(c, item[1]),
                )
                ndist = _dist_deg(c, nearest_centroid)
                if ndist > max_distance_deg:
                    continue
                for rel in (primary_rel, Relations.nearby):
                    if (s, rel, nearest_uri) not in kg.g:
                        kg.g.add((s, rel, nearest_uri))
                        written += 1
        if written:
            logger.info("[entity-cluster-topology] added %d relations", written)
        return written
    except Exception as exc:  # noqa: BLE001
        logger.warning("[entity-cluster-topology] failed: %s", exc)
        return 0


__all__ = ["add_entity_cluster_topology", "_centroid", "_cluster_centroids"]