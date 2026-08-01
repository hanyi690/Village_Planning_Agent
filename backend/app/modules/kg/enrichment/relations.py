"""关系语义注记 — RelationAnnotation 批量生成。

批量（L1/L2 回流）：
  聚类 sfWithin 地块  → quantitative_detail {parcel_count, area_ha, dlbm_distribution}
  地块 located_in 约束面 → "该地块位于XX线内"
  设施 serves 聚类     → "XX服务XX"
按需：touches/nearby 数千对不批量，describe_entity 动态注入。
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def annotate_cluster_relations(kg: Any, memory: Any, round_num: int = 1) -> int:
    """聚类↔地块关系注记（sfWithin）。"""
    from app.modules.kg import RelationAnnotation
    from app.modules.kg.ontology import PLN, Relations

    written = 0
    from rdflib import RDF

    from app.modules.kg.ontology import EntityTypes

    for cluster in kg.g.subjects(RDF.type, EntityTypes.ResidentialCluster):
        bsms: List[str] = []
        areas: List[float] = []
        dlbms: List[str] = []
        for parcel, _, _ in kg.g.triples((None, Relations.sfWithin, cluster)):
            for _, _, bsm in kg.g.triples((parcel, PLN.bsm, None)):
                bsms.append(str(bsm))
            for _, _, area in kg.g.triples((parcel, PLN.area_ha, None)):
                try:
                    areas.append(float(area))
                except (TypeError, ValueError):
                    pass
            for _, _, dlbm in kg.g.triples((parcel, PLN.dlbm, None)):
                dlbms.append(str(dlbm))
        if not bsms:
            continue
        cluster_name = ""
        for _, _, o in kg.g.triples((cluster, PLN.name, None)):
            cluster_name = str(o)
            break
        dist = dict(Counter(dlbms).most_common(5))
        memory.add_relation_annotation(
            RelationAnnotation(
                subject_uri=str(cluster),
                predicate="sfWithin",
                object_uri=f"pln:parcels:{cluster_name or len(bsms)}",
                description=f"{cluster_name}居民点包含{len(bsms)}个地块（{sum(areas):.1f}公顷）",
                derived_from="kg_relation_batch",
                quantitative_detail={
                    "parcel_count": len(bsms),
                    "area_ha": round(sum(areas), 2),
                    "dlbm_distribution": dist,
                },
            )
        )
        written += 1
    return written


def annotate_parcel_protection(kg: Any, bundle: Any, memory: Any, round_num: int = 1) -> int:
    """地块↔约束面 located_in 关系注记（用 bundle 几何 intersects 红线/农田）。"""
    from app.modules.kg import RelationAnnotation
    from app.modules.kg.ontology import PLN

    if bundle is None:
        return 0
    from shapely.geometry import shape

    protection = {}
    for key, label in (("ecological_redline", "生态保护红线"), ("farmland_protection", "永久基本农田")):
        geoms = [shape(getattr(f, "geometry", None)) for f in (bundle.polygons.get(key) or [])]
        geoms = [g for g in geoms if g is not None and not g.is_empty]
        if geoms:
            from shapely.ops import unary_union

            protection[label] = unary_union(geoms)

    if not protection:
        return 0

    written = 0
    for f in (bundle.polygons.get("landuse_current") or []):
        bsm = str(getattr(f, "bsm", "") or "")
        geom = getattr(f, "geometry", None)
        if not bsm or geom is None:
            continue
        try:
            shp = shape(geom)
        except Exception:
            continue
        for label, pgeom in protection.items():
            if shp.intersects(pgeom):
                uri = _parcel_uri(kg, bsm)
                if uri is None:
                    continue
                memory.add_relation_annotation(
                    RelationAnnotation(
                        subject_uri=str(uri),
                        predicate="located_in",
                        object_uri=f"pln:{label}",
                        description=f"地块{bsm}位于{label}内",
                        derived_from="kg_relation_batch",
                        quantitative_detail={"protection": label},
                    )
                )
                written += 1
    return written


def _parcel_uri(kg: Any, bsm: str) -> Optional[Any]:
    from app.modules.kg.ontology import PLN

    for s, _, o in kg.g.triples((None, PLN.bsm, None)):
        if str(o) == bsm:
            return s
    return None


__all__ = ["annotate_cluster_relations", "annotate_parcel_protection"]
