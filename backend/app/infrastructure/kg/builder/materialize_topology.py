"""统一拓扑构建 — KG 构建收尾时从 bundle 几何一次性生成全部空间关系。

原则（Regalia/SAWGraph）：几何留在 bundle（几何权威，空间操作在 app/spatial），
KG 只存质心 + 预计算拓扑关系。所有实体构建完成后统一执行，避免分散在多处不一致：

  1. 聚落簇（宅基地→聚落，build_village_clusters）+ 地块→簇 sfWithin 边；
  2. 设施/水体/道路 → 最近簇 serves/nearby（KG 质心 → 簇质心最近邻）；
  3. 缺失质心持久化（hasCentroid）。

幂等：已存在的簇/边不重复写。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
_MAX_DISTANCE_DEG = 0.02


def _cluster_bsm_set(kg: Any, cluster_uri: Any) -> set:
    from rdflib import URIRef

    from app.infrastructure.kg.ontology import PLN, Relations

    try:
        graph = getattr(kg, "g", None)
        if graph is None:
            return set()
        cluster = URIRef(cluster_uri)
        bsms: set = set()
        for parcel, _, _ in graph.triples((None, Relations.sfWithin, cluster)):
            bsm = graph.value(parcel, PLN.bsm)
            if bsm:
                bsms.add(str(bsm))
        return bsms
    except Exception:  # noqa: BLE001
        return set()


def _centroid(kg: Any, uri: Any) -> Optional[Tuple[float, float]]:
    from rdflib import URIRef

    from app.infrastructure.kg.ontology import GeoPredicates, PLN
    from app.spatial.grounding.coordinate_identity import point_xy

    try:
        subj = URIRef(uri)
        for predicate in (GeoPredicates.hasCentroid, GeoPredicates.hasGeometry):
            node = kg.g.value(subj, predicate)
            if node is None:
                continue
            xy = point_xy(str(kg.g.value(node, GeoPredicates.asWKT) or ""))
            if xy is not None:
                return xy
        lon = kg.g.value(subj, PLN.lon)
        lat = kg.g.value(subj, PLN.lat)
        if lon is not None and lat is not None:
            return (float(lon), float(lat))
    except Exception:  # noqa: BLE001
        return None
    return None


def _dist_deg(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    import math

    return math.hypot(a[0] - b[0], a[1] - b[1])


def materialize_kg_topology(
    kg: Any,
    bundle: Any,
    max_distance_deg: float = _MAX_DISTANCE_DEG,
) -> Dict[str, int]:
    """KG 构建收尾：聚落簇 + 地块→簇 + 实体→簇拓扑，一次统一生成。"""
    from rdflib import Literal, RDF

    from app.infrastructure.kg.builder.geo_helpers import add_centroid, add_geo_feature_type
    from app.infrastructure.kg.ontology import EntityIdPolicy, EntityTypes, PLN, Relations
    from app.spatial.grounding.village_cluster_mapper import build_village_clusters

    parcels = list(getattr(bundle, "polygons", None).get("landuse_current") or []) if getattr(bundle, "polygons", None) else []
    clusters = build_village_clusters(parcels) if parcels else []
    stats = {"clusters": 0, "parcel_edges": 0, "entity_relations": 0}

    # 1) 聚落簇 + 地块→簇（幂等：复用已存在簇）
    existing_clusters = list(kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster))
    existing_bsm_sets = {
        id(c): frozenset(_cluster_bsm_set(kg, c)) for c in existing_clusters
    }
    cluster_uris: List[Any] = []
    seq = 0
    for cluster in clusters:
        key = frozenset(cluster.bsms)
        uri = None
        for c, bset in existing_bsm_sets.items():
            if bset == key:
                uri = c
                break
        if uri is None:
            uri = EntityIdPolicy.fallback_uri("settlement", f"居民点{seq + 1}", seq)
            kg.g.add((uri, RDF.type, EntityTypes.ResidentialCluster))
            kg.g.add((uri, PLN.name, Literal(f"居民点{seq + 1}")))
            kg.g.add((uri, Relations.sfWithin, PLN.village))
            add_geo_feature_type(kg.g, uri)
            stats["clusters"] += 1
        if cluster.centroid:
            add_centroid(kg.g, uri, cluster.centroid[0], cluster.centroid[1])
        for bsm in cluster.bsms:
            for s in kg.g.subjects(PLN.bsm, Literal(bsm)):
                if (s, RDF.type, EntityTypes.Parcel) in kg.g and (s, Relations.sfWithin, uri) not in kg.g:
                    kg.g.add((s, Relations.sfWithin, uri))
                    stats["parcel_edges"] += 1
        cluster_uris.append(uri)
        seq += 1

    if not cluster_uris:
        return stats

    # 2) 设施/水体/道路 → 最近簇（KG 质心最近邻）
    cluster_centroids = [
        (uri, c) for uri in cluster_uris if (c := _centroid(kg, uri)) is not None
    ]
    if not cluster_centroids:
        return stats
    for etype, primary_rel in (
        (EntityTypes.Facility, Relations.serves),
        (EntityTypes.WaterBody, Relations.nearby),
        (EntityTypes.Road, Relations.nearby),
    ):
        for s in kg.g.subjects(RDF.type, etype):
            c = _centroid(kg, s)
            if c is None:
                continue
            nearest_uri, nearest_c = min(
                cluster_centroids, key=lambda item: _dist_deg(c, item[1])
            )
            if _dist_deg(c, nearest_c) > max_distance_deg:
                continue
            for rel in (primary_rel, Relations.nearby):
                if (s, rel, nearest_uri) not in kg.g:
                    kg.g.add((s, rel, nearest_uri))
                    stats["entity_relations"] += 1

    logger.info(
        "[materialize_kg_topology] clusters=%d parcel_edges=%d entity_relations=%d",
        stats["clusters"], stats["parcel_edges"], stats["entity_relations"],
    )
    return stats


__all__ = ["materialize_kg_topology"]