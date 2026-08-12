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
    from app.infrastructure.kg import RelationAnnotation
    from app.infrastructure.kg.ontology import PLN, Relations

    written = 0
    from rdflib import RDF

    from app.infrastructure.kg.ontology import EntityTypes

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


def annotate_parcel_protection(kg: Any, memory: Any, round_num: int = 1) -> int:
    """地块↔约束面 located_in/sfIntersects 关系注记（KG 三元组，无几何依赖）。"""
    from app.infrastructure.kg import RelationAnnotation
    from app.infrastructure.kg.ontology import PLN

    written = 0
    for s, _, o in kg.g.triples((None, None, None)):
        break  # 占位避免空循环（下方用具体谓词）
    for pred_name in ("sfIntersects", "located_in"):
        for s, p, o in kg.g.triples((None, None, None)):
            pn = str(p).split("#")[-1].split("/")[-1]
            if pn != pred_name:
                continue
            bsm = ""
            for _, _, b in kg.g.triples((s, PLN.bsm, None)):
                bsm = str(b)
                break
            if not bsm:
                continue
            label = str(o).split("#")[-1].split("/")[-1]
            memory.add_relation_annotation(
                RelationAnnotation(
                    subject_uri=str(s),
                    predicate=pred_name,
                    object_uri=str(o),
                    description=f"地块{bsm}位于{label}内" if pred_name == "located_in" else f"地块{bsm}与{label}相交",
                    derived_from="kg_relation_batch",
                    quantitative_detail={"protection": label},
                )
            )
            written += 1
    return written


def _parcel_uri(kg: Any, bsm: str) -> Optional[Any]:
    from app.infrastructure.kg.ontology import PLN

    for s, _, o in kg.g.triples((None, PLN.bsm, None)):
        if str(o) == bsm:
            return s
    return None


__all__ = ["annotate_cluster_relations", "annotate_parcel_protection"]
