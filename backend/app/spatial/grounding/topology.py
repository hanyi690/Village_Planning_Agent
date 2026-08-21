"""KG 拓扑证据 — 预计算空间关系参与地名接地（设计 §4.2）。

确定性：只读 KG 预计算关系（touches/nearby/connected_via_road/sfWithin/
sfIntersects/sfContains/serves/derived_from），不调 LLM、不造几何。
空间职责留在 ``app.spatial``；evidence/index 与 domain/ground 通过这里消费拓扑。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_HINT_SEPARATORS = frozenset("、，,；;/ \t\n\r")
_HINT_SUFFIXES = ("自然村", "村", "组", "一带", "沿线", "两岸", "附近", "周边", "区域")


def hint_tokens(hints: str) -> List[str]:
    """把 location/relation hint 文本拆成候选实体名 token（含村后缀保留）。"""
    if not hints:
        return []
    tokens: List[str] = []
    parts: list[str] = []
    current: list[str] = []
    for char in hints:
        if char in _HINT_SEPARATORS:
            if current:
                parts.append("".join(current))
                current.clear()
            continue
        current.append(char)
    if current:
        parts.append("".join(current))
    for connector in ("至", "和", "与"):
        expanded: list[str] = []
        for part in parts:
            expanded.extend(part.split(connector))
        parts = expanded
    for part in parts:
        part = part.strip()
        if not part or len(part) < 2:
            continue
        tokens.append(part)
        # 同时登记去掉空间描述后缀的核名，例如 金田河两岸 -> 金田河
        core = part
        for suffix in ("沿线", "两岸", "附近", "周边", "一带", "区域", "范围内"):
            if core.endswith(suffix):
                core = core[: -len(suffix)].strip()
                break
        if core and core != part and core not in tokens:
            tokens.append(core)
    return list(dict.fromkeys(tokens))


def relation_pairs(graph: Any, subject: Any) -> List[tuple[str, str]]:
    """返回 (谓词短名, 对象 URI) 列表，来自 KG 预计算空间/语义关系。"""
    try:
        from app.infrastructure.kg.ontology import Relations

        predicates = {str(p) for p in Relations.spatial()}
        # serves/derived_from 是设施↔村、实体↔来源的关键语义关系（设计 §4.2：
        # ``祠堂@社前村`` 走 serves/nearby 拓扑证据）。
        predicates.update({
            str(Relations.serves),
            str(Relations.derived_from),
        })
        pairs: List[tuple[str, str]] = []
        for predicate, obj in graph.predicate_objects(subject):
            pred_str = str(predicate)
            if pred_str not in predicates:
                continue
            obj_str = str(obj)
            if not obj_str.startswith("http"):
                continue
            short = pred_str.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
            pairs.append((short, obj_str))
        return pairs
    except Exception as exc:  # noqa: BLE001
        logger.debug("[topology] relation_pairs failed: %s", exc)
        return []


def relation_object_names(graph: Any, object_uri: str) -> Set[str]:
    """关系对象实体的可检索名称（name/label/别名）。"""
    try:
        from rdflib import URIRef

        uri = URIRef(object_uri)
    except Exception:  # noqa: BLE001
        return set()
    names: Set[str] = set()
    for predicate, obj in graph.predicate_objects(uri):
        pred_str = str(predicate)
        if pred_str.endswith("name") or pred_str.endswith("label"):
            txt = str(obj).strip()
            if txt and not txt.startswith("http"):
                names.add(txt)
    return names


def topology_evidence_for(
    graph: Any,
    entity_uri: str,
    hints: str = "",
    relation_refs: Optional[List[str]] = None,
) -> List[str]:
    """候选实体是否与 hint 中出现的实体存在预计算拓扑/语义关系。

    返回命中证据列表（如 ``serves:社前村`` / ``nearby:园寨``）；hint 为空或
    无命中返回空列表（该维度 0 分，不惩罚）。
    """
    if graph is None or not entity_uri or not hints:
        return []
    tokens = set(hint_tokens(hints))
    if not tokens:
        return []
    try:
        from rdflib import URIRef

        subject = URIRef(entity_uri)
    except Exception:  # noqa: BLE001
        subject = entity_uri
    evidence: List[str] = []
    try:
        pairs = relation_pairs(graph, subject)
    except Exception:  # noqa: BLE001
        pairs = []
    for pred_short, obj_uri in pairs:
        names = relation_object_names(graph, obj_uri)
        if not names:
            continue
        for name in names:
            stripped = name.strip()
            if not stripped:
                continue
            for token in tokens:
                if token in stripped or stripped in token:
                    evidence.append(f"{pred_short}:{stripped}")
                    break
    return list(dict.fromkeys(evidence))


__all__ = [
    "hint_tokens",
    "relation_pairs",
    "relation_object_names",
    "topology_evidence_for",
]
