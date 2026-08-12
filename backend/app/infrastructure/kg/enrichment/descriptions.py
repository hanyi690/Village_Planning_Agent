"""实体语义描述 — 动态三源注入（属性 + 邻接关系 + 静态要素）。

describe_entity(kg, uri, entity_type, depth=1, top_n=8):
  ① 属性注入：实时读该实体全部 pln:* 三元组
  ② 邻接注入：touches/nearby/connected_via_road/serves/sfWithin 邻接实体
     （depth=2 时邻接实体带核心属性）
  ③ 静态要素：dlbm 字典名称 / 面积换算

批量快照：describe_parcels → EntityAnnotation（memory 轮次文件，L1 回流用）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

_RELATION_LABELS = {
    "sfTouches": "邻接",
    "nearby": "邻近",
    "connected_via_road": "经道路相连",
    "serves": "服务",
    "sfWithin": "位于",
    "sfIntersects": "相交",
    "sfContains": "包含",
    "derived_from": "源自",
}

_DLBM_NAMES = {
    "1100": "耕地", "1200": "园地", "1300": "林地", "1340": "商品林",
    "1350": "生态林", "1400": "草地", "1510": "设施农用地",
    "2121": "宅基地", "2122": "公共服务用地", "2124": "经营性建设用地",
    "2125": "景观绿化用地", "2126": "村内交通用地", "2200": "对外交通用地",
    "2270": "水利设施用地", "3100": "水域", "3200": "自然保留地",
}


def _obj_name(o: Any) -> str:
    s = str(o)
    if "#" in s:
        return s.split("#")[-1]
    return s.split("/")[-1]


def _label(kg: Any, uri: Any) -> str:
    """Best-effort entity label: name → bsm → uri tail."""
    from app.infrastructure.kg.ontology import PLN

    for _, _, o in kg.g.triples((uri, PLN.name, None)):
        return str(o)
    for _, _, o in kg.g.triples((uri, PLN.bsm, None)):
        return str(o)
    return _obj_name(uri)


def _entity_type(kg: Any, uri: Any) -> str:
    from rdflib import RDF

    for _, _, o in kg.g.triples((uri, RDF.type, None)):
        return _obj_name(o)
    return ""


def _attribute_text(kg: Any, uri: Any, skip: Optional[set] = None) -> str:
    """① 属性注入：实体全部 pln:* 属性 → 文本。"""
    from app.infrastructure.kg.ontology import PLN

    skip = skip or {"type", "name"}
    parts: List[str] = []
    for p, o in kg.g.predicate_objects(uri):
        pred = _obj_name(p)
        if pred in skip:
            continue
        val = str(o)
        if pred == "dlbm":
            val = f"{_DLBM_NAMES.get(val, val)}({val})"
        if pred == "area_ha":
            val = f"{val}公顷"
        parts.append(f"{pred}={val}")
    return "，".join(parts[:14])


def _neighbor_text(kg: Any, uri: Any, depth: int, top_n: int, seen: set) -> List[str]:
    """② 邻接注入：关系 → 邻接实体（depth=2 带核心属性）。"""
    from app.infrastructure.kg.ontology import PLN

    out: List[str] = []
    count = 0
    for p, o in kg.g.predicate_objects(uri):
        pred = _obj_name(p)
        if pred not in _RELATION_LABELS:
            continue
        if str(o) in seen or o == uri:
            continue
        seen.add(str(o))
        label = _label(kg, o)
        etype = _entity_type(kg, o)
        desc = f"{_RELATION_LABELS[pred]}{label}"
        if etype:
            desc += f"({etype})"
        if depth >= 2:
            core = _attribute_text(kg, o, skip={"type", "name", "bsm"})
            if core:
                desc += f"[{core[:60]}]"
        out.append(desc)
        count += 1
        if count >= top_n:
            break
    return out


def describe_entity(
    kg: Any,
    uri: Any,
    entity_type: Optional[str] = None,
    depth: int = 1,
    top_n: int = 8,
) -> str:
    """动态实体语义描述（属性 + 邻接 + 静态要素）。"""
    if kg is None or uri is None:
        return ""
    etype = entity_type or _entity_type(kg, uri)
    label = _label(kg, uri)

    parts = [f"{label}({etype})" if etype else str(label)]
    attrs = _attribute_text(kg, uri)
    if attrs:
        parts.append(attrs)
    neighbors = _neighbor_text(kg, uri, depth, top_n, {str(uri)})
    if neighbors:
        parts.append("邻接/关系：" + "；".join(neighbors))
    return "，".join(parts)


def describe_parcels(
    kg: Any,
    bundle: Any,
    bsms: List[str],
    round_num: int = 1,
) -> int:
    """批量地块语义描述（L1 回流：绑定村名的聚类内地块）→ EntityAnnotation 落盘。"""
    from app.infrastructure.kg import EntityAnnotation, get_semantic_memory

    memory = get_semantic_memory()
    written = 0
    for bsm in bsms[:200]:
        uri = _find_parcel_uri(kg, bsm)
        if uri is None:
            continue
        desc = describe_entity(kg, uri, "Parcel", depth=1, top_n=6)
        if not desc:
            continue
        memory.add_entity_annotation(
            EntityAnnotation(
                entity_uri=str(uri),
                entity_type="Parcel",
                description=desc[:300],
                source_text_refs=[f"l1_batch:{bsm}"],
                round_added=round_num,
                valid_from_round=round_num,
                confidence=0.8,
            )
        )
        written += 1
    return written


def _find_parcel_uri(kg: Any, bsm: str) -> Optional[Any]:
    from app.infrastructure.kg.ontology import PLN

    for s, _, o in kg.g.triples((None, PLN.bsm, None)):
        if str(o) == bsm:
            return s
    return None


__all__ = ["describe_entity", "describe_parcels"]
