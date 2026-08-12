"""execute_queries — EXECUTE 阶段 KG 查询（激活提案 execute-kg-utilization §2）。

首个激活：get_parcel_context — 生成期上下文（邻接/约束/聚类/三线），
供多因子上下文构造（B3）与地块语义描述（enrichment.descriptions）复用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


def get_parcel_context(
    kg: Any,
    bsm: str,
    depth: int = 1,
) -> Optional[Dict[str, Any]]:
    """Parcel context: attributes + adjacency + constraints + settlement cluster.

    SPARQL-聚合实现（KG L1/L2 关系）：
      - attributes: bsm/dlbm/area_ha/zone_type
      - adjacency: touches/nearby/connected_via_road 邻接 BSM 列表（top-N）
      - cluster: sfWithin 的 ResidentialCluster URI/名称
      - protection: intersects/located_in 的约束面类型
    """
    from app.infrastructure.kg.ontology import PLN, Relations

    if kg is None or not bsm:
        return None

    # 定位 parcel 实体
    parcel_uri = None
    for s, _, o in kg.g.triples((None, PLN.bsm, None)):
        if str(o) == bsm:
            parcel_uri = s
            break
    if parcel_uri is None:
        return None

    attrs: Dict[str, Any] = {"bsm": bsm}
    for p, o in kg.g.predicate_objects(parcel_uri):
        pred = str(p).split("#")[-1].split("/")[-1]
        if pred not in ("type",):
            attrs[pred] = str(o)

    adjacency: List[str] = []
    for p, o in kg.g.predicate_objects(parcel_uri):
        pred = str(p).split("#")[-1].split("/")[-1]
        if pred not in ("sfTouches", "nearby", "connected_via_road"):
            continue
        for _, _, o_bsm in kg.g.triples((o, PLN.bsm, None)):
            adjacency.append(str(o_bsm))
        if len(adjacency) >= 8:
            break

    cluster = None
    for _, _, c in kg.g.triples((parcel_uri, Relations.sfWithin, None)):
        cname = ""
        for _, _, o in kg.g.triples((c, PLN.name, None)):
            cname = str(o)
            break
        cluster = {"uri": str(c), "name": cname or str(c).split("#")[-1]}
        break

    protection: List[str] = []
    for p, o in kg.g.predicate_objects(parcel_uri):
        pred = str(p).split("#")[-1].split("/")[-1]
        if pred in ("sfIntersects", "located_in"):
            protection.append(str(o).split("#")[-1].split("/")[-1])

    return {
        "bsm": bsm,
        "attributes": attrs,
        "adjacency_bsms": list(dict.fromkeys(adjacency)),
        "cluster": cluster,
        "protection": protection,
    }


__all__ = ["get_parcel_context"]
