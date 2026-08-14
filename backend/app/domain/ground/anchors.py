"""ground_anchors — L1 锚点接地（设计 §5.1/§6）。

domain/ground 唯一拥有"接地"：把 ``L1Snapshot.location_facts`` 编译为
``GroundedAnchor[]``（mention → entity_ref/BSM/geometry + topology_evidence），
并富化 KG（真名回填、语义注解、关系注记）与重建 ``PlaceEvidenceIndex``。

原则：
- 同一坐标 = 同一实体（``app.spatial.grounding.coordinate_identity``）。
- 空间操作全部留在 ``app.spatial`` / ``app.evidence.index``；本模块只编排。
- 不允许留下不可解析的地点：即使置信度低，LLM 在 KG/索引候选内推理出可用结果
  （``best_effort=True`` + 低置信），几何/BSM 永远来自 KG/bundle，不来自 LLM。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.contracts.spatial.grounding_contracts import GroundedAnchor
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _scope_names(village_name: str) -> set:
    """规划范围名集合（行政村名及其去"村"基础名）。"""
    v = str(village_name or "").strip()
    names = {v} if v else set()
    if v.endswith("村") and len(v) > 1:
        names.add(v[:-1])
    return {n for n in names if n}


def _is_scope_fact(fact: Any, village_name: str) -> bool:
    """该地点事实是否指代整个项目的规划范围（行政村）。"""
    names = _scope_names(village_name)
    if not names:
        return False
    normalized = str(getattr(fact, "normalized_name", "") or "").strip()
    mention = str(getattr(fact, "mention", "") or "").strip()
    return normalized in names or mention in names


def _scope_anchor(fact: Any, context: Any, trace: List[dict]) -> Optional[GroundedAnchor]:
    """构造规划范围锚点（administrative_village）。

    空间绑定 = **整个行政边界/规划范围面**（``workspace.boundary``），不是地块池；
    边界几何来自 bundle，BSM 为空（不作为候选地块）。
    """
    from app.spatial.grounding.coordinate_identity import coordinate_key

    scope = str(getattr(context, "village_name", "") or "")
    entity_ref = ""
    bsms: List[str] = []
    geometry_ref = None
    coord_key = ""
    # 1) 整个行政边界（规划范围）几何
    workspace = getattr(context, "workspace", None)
    boundary = getattr(workspace, "boundary", None) if workspace is not None else None
    if boundary is not None:
        geom = getattr(boundary, "geometry", None) or {}
        if isinstance(geom, dict) and geom.get("coordinates"):
            try:
                import shapely.geometry as sg

                g = sg.shape(geom)
                if not g.is_empty and g.is_valid:
                    geometry_ref = f"boundary:{g.wkt[:300]}"
                    cx, cy = g.centroid.x, g.centroid.y
                    coord_key = f"{round(cx, 6)},{round(cy, 6)}"
                    trace.append({"step": "scope:boundary_geometry", "wkt_chars": len(g.wkt)})
            except Exception:  # noqa: BLE001
                pass
    # 2) 实体引用：gazetteer / KG AdministrativeVillage
    gazetteer = getattr(context, "gazetteer", None)
    if gazetteer is not None:
        entry = None
        for candidate in (scope, scope.rstrip("村")):
            entry = gazetteer.resolve(candidate, fuzzy=False)
            if entry is not None:
                break
        if entry is not None:
            entity_ref = str(getattr(entry, "entity_uri", "") or "")
            bsms = [str(b) for b in (entry.bsms or []) if b]
            if not geometry_ref:
                centroid = getattr(entry, "centroid", None)
                if centroid and len(centroid) >= 2:
                    geometry_ref = f"POINT({centroid[0]} {centroid[1]})"
                    coord_key = coordinate_key(geometry_ref)
    if not entity_ref:
        try:
            from rdflib import RDF
            from app.infrastructure.kg.ontology import EntityTypes, PLN

            kg = getattr(context, "kg", None)
            graph = getattr(kg, "g", None) if kg is not None else None
            if graph is not None:
                for subject in graph.subjects(RDF.type, EntityTypes.AdministrativeVillage):
                    name = str(graph.value(subject, PLN.name) or "").strip()
                    if name in _scope_names(scope):
                        entity_ref = str(subject)
                        bsm = str(graph.value(subject, PLN.bsm) or "").strip()
                        if bsm:
                            bsms = [bsm]
                        break
        except Exception:  # noqa: BLE001
            pass
    if not coord_key:
        coord_key = coordinate_key(geometry_ref)
    trace.append({"step": "scope:administrative_village", "scope": scope})
    return GroundedAnchor(
        location_fact_ref=str(getattr(fact, "source_report_ref", "") or ""),
        mention=str(getattr(fact, "mention", "") or getattr(fact, "normalized_name", "") or ""),
        normalized_name=str(getattr(fact, "normalized_name", "") or ""),
        role="administrative_village",
        entity_ref=entity_ref,
        entity_type="administrative_village",
        geometry_ref=geometry_ref,
        source_bsms=list(dict.fromkeys(bsms)),
        coordinate_key=coord_key,
        confidence=0.9 if (entity_ref or geometry_ref) else 0.5,
        status="resolved",
        best_effort=False,
        source_report_ref=str(getattr(fact, "source_report_ref", "") or ""),
        source_span=str(getattr(fact, "source_span", "") or ""),
        query_trace=trace,
    )


_ORIENTATION_MARKERS = (
    "贯穿", "走向", "沿", "汇入", "通往", "东北", "东南", "西北", "西南",
    "南北", "东西", "至",
)


async def _llm_orientation_rebind(
    context: Any,
    fact: Any,
    anchor: GroundedAnchor,
    llm: Any,
) -> GroundedAnchor:
    """空间描述（如 西南至东北贯穿金田村）→ LLM 在同类候选里选实体级候选。

    触发：水/路/地标 且 hint 含方位/走向标记 且当前锚点是村锚点/粗绑定。
    LLM 只在索引候选内判别（几何/BSM 来自 KG/bundle），不新增几何。
    """
    if anchor.role not in ("water", "road", "landmark", "facility"):
        return anchor
    if llm is None:
        return anchor
    hints = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
    if not any(marker in hints for marker in _ORIENTATION_MARKERS):
        return anchor
    # 已实体级绑定（真实 POINT 几何）就不再重绑
    if _has_point_geometry(anchor.geometry_ref):
        return anchor
    candidates = _index_role_candidates(context, anchor.role)
    if len(candidates) < 2:
        return anchor
    picked = await _llm_reason_candidate(
        llm,
        str(anchor.normalized_name or anchor.mention or ""),
        anchor.role,
        hints,
        candidates,
    )
    if picked is None:
        return anchor
    picked_bsms = list(getattr(picked, "source_bsms", None) or [])
    if not picked_bsms or not _has_point_geometry(getattr(picked, "geometry_ref", None)):
        return anchor
    trace = list(getattr(anchor, "query_trace", None) or [])
    trace.append({
        "step": "llm_orientation_rebind",
        "picked": getattr(picked, "canonical_name", ""),
        "geometry": getattr(picked, "geometry_ref", ""),
    })
    rebound = _anchor_from_candidate(
        fact,
        picked,
        best_effort=False,
        topology_evidence=list(getattr(anchor, "topology_evidence", None) or []),
        query_trace=trace,
    )
    rebound.confidence = max(rebound.confidence, 0.75)
    return rebound


def _has_point_geometry(geometry_ref: Optional[str]) -> bool:
    from app.spatial.grounding.coordinate_identity import point_xy

    return point_xy(geometry_ref) is not None


def _index_role_candidates(context: Any, role: str) -> list:
    """从证据索引取同角色、有真实几何/地块的候选（供 LLM 判别）。"""
    from types import SimpleNamespace

    index = getattr(context, "evidence_index", None)
    if index is None:
        return []
    out: list = []
    for entry in getattr(index, "entries", []) or []:
        if getattr(entry, "role", "") != role:
            continue
        if not getattr(entry, "source_bsms", None) and not getattr(entry, "geometry_ref", None):
            continue
        if str(getattr(entry, "canonical_name", "") or "").startswith("l1_fact"):
            continue
        out.append(SimpleNamespace(
            entity_ref=str(getattr(entry, "entity_refs", None) or [""])[0] if getattr(entry, "entity_refs", None) else "",
            entity_type=str(getattr(entry, "entity_types", None) or ["unknown"])[0] if getattr(entry, "entity_types", None) else "unknown",
            canonical_name=str(getattr(entry, "canonical_name", "") or ""),
            source_bsms=list(getattr(entry, "source_bsms", None) or []),
            geometry_ref=getattr(entry, "geometry_ref", None),
            relation_refs=list(getattr(entry, "relation_refs", None) or []),
            score=float(getattr(entry, "confidence", 0.0) or 0.0),
        ))
    return out


def _cluster_bsms_of(kg: Any, cluster_uri: str) -> set:
    """村簇（ResidentialCluster）的地块 BSM 集（parcels sfWithin cluster → bsm）。"""
    from rdflib import URIRef

    from app.infrastructure.kg.ontology import PLN, Relations

    try:
        graph = getattr(kg, "g", None) if kg is not None else None
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


def _topology_refine_facility(
    context: Any,
    fact: Any,
    anchor: GroundedAnchor,
) -> GroundedAnchor:
    """设施@村 拓扑消歧：多个同名设施点中选 serves/nearby 指向 hint 村庄簇的那个。

    输入：anchor 已按索引/近邻绑定；hint（如 社前村）给出村庄。
    做法：取 hint 村庄 gazetteer BSM 集；对索引内同角色、有 KG 实体的候选设施，
    读其 serves/nearby → 村簇 → 簇地块 BSM 与村庄 BSM 的重叠；选重叠最大的候选
    重绑。几何/BSM 全部来自 KG/bundle，LLM 不参与（确定性拓扑推理）。
    """
    hints = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
    if not hints or getattr(context, "gazetteer", None) is None:
        return anchor
    from app.spatial.grounding.topology import hint_tokens

    village_bsms: set = set()
    for token in hint_tokens(hints):
        entry = context.gazetteer.resolve(token, fuzzy=False) or context.gazetteer.resolve(token, fuzzy=True)
        if entry is not None and (entry.bsms or entry.centroid):
            village_bsms.update(str(b) for b in (entry.bsms or []) if b)
            break
    if not village_bsms:
        return anchor
    kg = getattr(context, "kg", None)
    graph = getattr(kg, "g", None) if kg is not None else None
    if graph is None:
        return anchor
    from rdflib import URIRef

    from app.infrastructure.kg.ontology import Relations

    index = getattr(context, "evidence_index", None)
    if index is None:
        return anchor
    # 候选：同角色、POINT 几何、带 KG 实体引用的索引条目
    best = None
    best_overlap = 0
    current_entity = str(getattr(anchor, "entity_ref", "") or "")
    for entry in getattr(index, "entries", []) or []:
        if getattr(entry, "role", "") != "facility":
            continue
        entity_refs = list(getattr(entry, "entity_refs", None) or [])
        kg_uri = next((r for r in entity_refs if str(r).startswith("http")), None)
        if kg_uri is None:
            continue
        try:
            subj = URIRef(kg_uri)
            cluster_uris = set()
            for p, o in graph.predicate_objects(subj):
                if str(p) in (str(Relations.serves), str(Relations.nearby)) and str(o).startswith("http"):
                    cluster_uris.add(str(o))
            overlap = 0
            for cu in cluster_uris:
                overlap = max(overlap, len(_cluster_bsms_of(kg, cu) & village_bsms))
        except Exception:  # noqa: BLE001
            continue
        if overlap > best_overlap:
            best_overlap = overlap
            best = entry
    if best is None or best_overlap <= 0:
        trace = list(getattr(anchor, "query_trace", None) or [])
        trace.append({
            "step": "kg_topology_facility",
            "refined": False,
            "village_bsms": len(village_bsms),
            "overlap": best_overlap,
        })
        anchor = anchor.model_copy(update={"query_trace": trace})
        return anchor
    from types import SimpleNamespace

    cand = SimpleNamespace(
        entity_ref=str((getattr(best, "entity_refs", None) or [""])[0]),
        entity_type=str((getattr(best, "entity_types", None) or ["facility"])[0]),
        canonical_name=str(getattr(best, "canonical_name", "") or ""),
        source_bsms=list(getattr(best, "source_bsms", None) or []),
        geometry_ref=getattr(best, "geometry_ref", None),
        relation_refs=list(getattr(best, "relation_refs", None) or []),
        score=float(getattr(best, "confidence", 0.0) or 0.0),
    )
    if not cand.source_bsms:
        return anchor
    trace = list(getattr(anchor, "query_trace", None) or [])
    trace.append({
        "step": "kg_topology_facility",
        "village_bsms": len(village_bsms),
        "overlap": best_overlap,
        "picked": cand.canonical_name,
        "entity_ref": cand.entity_ref,
    })
    rebound = _anchor_from_candidate(
        fact,
        cand,
        best_effort=False,
        topology_evidence=list(getattr(anchor, "topology_evidence", None) or []),
        query_trace=trace,
    )
    rebound.confidence = max(rebound.confidence, 0.8)
    return rebound


async def _village_spatial_fallback(
    context: Any,
    fact: Any,
    anchor: GroundedAnchor,
    llm: Any,
    trace: List[dict],
) -> GroundedAnchor:
    """村锚点无空间引用时的兜底（不能留又不能解析）。

    顺序：① gazetteer 村条目 BSM（村映射已分配）；② 确定性分配到**未占用**聚落
    （面积降序；已分配村名/已用聚落跨调用累积，避免多个村共占同一聚落），
    best_effort + 低置信，可审计。
    """
    hints = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
    village_bsms = _village_anchor_bsms(context, hints)
    poi_bsms = _poi_anchor_bsms(context, fact)
    if poi_bsms or village_bsms:
        cand = _best_effort_candidate(fact, poi_bsms, village_bsms, trace)
        trace.append({"step": "village_fallback:gazetteer_bsms", "count": len(cand.source_bsms)})
        return _anchor_from_candidate(fact, cand, best_effort=True, query_trace=trace)

    # 已占用 BSM：已分配村名的 gazetteer BSM + 本次兜底已用聚落 BSM
    occupied: set = set()
    for other in getattr(context, "location_facts", []) or []:
        if other is fact:
            continue
        if str(getattr(other, "role", "") or "") != "village":
            continue
        other_name = str(getattr(other, "normalized_name", "") or getattr(other, "mention", "") or "").strip()
        if not other_name:
            continue
        entry = _resolve_gazetteer_entry_any(context, other_name)
        if entry is not None:
            occupied.update(str(b) for b in (entry.bsms or []))
    used = set(getattr(context, "_grounding_used_cluster_bsms", set()) or set())
    occupied |= used

    try:
        from types import SimpleNamespace

        from app.spatial.grounding.village_cluster_mapper import build_village_clusters

        parcels = list(context.current_parcels() or [])
        clusters = sorted(build_village_clusters(parcels), key=lambda c: -c.area_ha)
        unassigned = [
            c for c in clusters if not (set(c.bsms) & occupied)
        ]
        mention = str(anchor.normalized_name or anchor.mention or "")
        # ② 优先 LLM：在未占用聚落里按村名+hint+质心/面积判别（低置信 best_effort）
        if unassigned and llm is not None and mention:
            cand_list = [
                SimpleNamespace(
                    entity_ref=f"cluster:{c.index}",
                    entity_type="village",
                    canonical_name=f"聚落{c.index}",
                    source_bsms=list(c.bsms),
                    geometry_ref=(
                        f"POINT({c.centroid[0]} {c.centroid[1]})"
                        if c.centroid else None
                    ),
                    relation_refs=[],
                    score=0.4,
                )
                for c in unassigned
            ]
            picked = await _llm_reason_candidate(
                llm, mention, "village", hints, cand_list
            )
            if picked is not None:
                picked_bsms = list(getattr(picked, "source_bsms", None) or [])
                if picked_bsms:
                    trace.append({
                        "step": "village_fallback:llm_cluster_assign",
                        "picked": getattr(picked, "canonical_name", ""),
                        "geometry": getattr(picked, "geometry_ref", ""),
                    })
                    used |= set(picked_bsms)
                    try:
                        setattr(context, "_grounding_used_cluster_bsms", used)
                    except Exception:
                        pass
                    return _anchor_from_candidate(
                        fact, picked, best_effort=True, query_trace=trace
                    )
        # ③ 无 LLM/LLM 失败时才确定性分配（底线，显式标注 estimate）
        for cluster in unassigned:
            cluster_bsms = set(cluster.bsms)
            cand = _best_effort_candidate(fact, [], list(cluster_bsms), trace)
            trace.append({
                "step": "village_fallback:deterministic_cluster",
                "cluster_index": cluster.index,
                "area_ha": round(cluster.area_ha, 2),
                "estimate": True,
            })
            used |= cluster_bsms
            try:
                setattr(context, "_grounding_used_cluster_bsms", used)
            except Exception:
                pass
            return _anchor_from_candidate(fact, cand, best_effort=True, query_trace=trace)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ground_anchors] cluster fallback failed: %s", exc)
    return anchor


def _village_used_tokens(context: Any) -> list:
    """已分配到聚落的村名（避免确定性兜底重复分配同一聚落）。"""
    out: list = []
    for fact in getattr(context, "location_facts", []) or []:
        if str(getattr(fact, "role", "") or "") != "village":
            continue
        name = str(getattr(fact, "normalized_name", "") or getattr(fact, "mention", "") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _resolve_gazetteer_entry_any(context: Any, name: str):
    gazetteer = getattr(context, "gazetteer", None)
    if gazetteer is None:
        return None
    return gazetteer.resolve(name, fuzzy=False) or gazetteer.resolve(name, fuzzy=True)


def _linear_spatial_fallback(
    context: Any,
    fact: Any,
    anchor: GroundedAnchor,
    trace: List[dict],
) -> GroundedAnchor:
    """水/路无空间引用兜底：从 KG 同类实体里按 hint 村簇重叠/最近选一个。

    水体/道路现已在 KG 存质心 + nearby 村簇；用 hint（如 金田村/社前村）的
    gazetteer BSM 与该实体 nearby 簇的 BSM 求重叠，选重叠最大的（确定性，
    不依赖 LLM 输出解析），best_effort + 低置信。
    """
    from types import SimpleNamespace

    from app.infrastructure.kg.ontology import PLN, Relations

    kg = getattr(context, "kg", None)
    graph = getattr(kg, "g", None) if kg is not None else None
    if graph is None:
        return anchor
    hints = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
    village_bsms = _village_anchor_bsms(context, hints)
    index = getattr(context, "evidence_index", None)
    candidates = []
    if index is not None:
        for entry in getattr(index, "entries", []) or []:
            if getattr(entry, "role", "") != anchor.role:
                continue
            refs = list(getattr(entry, "entity_refs", None) or [])
            kg_uri = next((r for r in refs if str(r).startswith("http")), None)
            if kg_uri is None:
                continue
            if not getattr(entry, "source_bsms", None) and not getattr(entry, "geometry_ref", None):
                continue
            candidates.append(entry)
    if not candidates:
        return anchor
    best = None
    best_overlap = -1
    from rdflib import URIRef

    for entry in candidates:
        kg_uri = str(next((r for r in getattr(entry, "entity_refs", []) if str(r).startswith("http")), ""))
        overlap = 0
        try:
            subj = URIRef(kg_uri)
            for p, o in graph.predicate_objects(subj):
                if str(p) in (str(Relations.nearby), str(Relations.sfWithin)) and str(o).startswith("http"):
                    overlap = max(overlap, len(_cluster_bsms_of(kg, str(o)) & village_bsms))
        except Exception:  # noqa: BLE001
            continue
        if overlap > best_overlap or (overlap == best_overlap and best is None):
            best_overlap = overlap
            best = entry
    if best is None:
        return anchor
    cand = SimpleNamespace(
        entity_ref=str((getattr(best, "entity_refs", None) or [""])[0]),
        entity_type=str((getattr(best, "entity_types", None) or [anchor.role])[0]),
        canonical_name=str(getattr(best, "canonical_name", "") or ""),
        source_bsms=list(getattr(best, "source_bsms", None) or []),
        geometry_ref=getattr(best, "geometry_ref", None),
        relation_refs=list(getattr(best, "relation_refs", None) or []),
        score=0.35,
    )
    if not cand.source_bsms:
        return anchor
    trace = list(getattr(anchor, "query_trace", None) or [])
    trace.append({
        "step": "linear_fallback:kg_topology",
        "overlap": best_overlap,
        "picked": cand.canonical_name,
    })
    return _anchor_from_candidate(fact, cand, best_effort=True, query_trace=trace)


def _cluster_for_bsms(kg: Any, bsms: set) -> Optional[str]:
    """按地块 BSM 找 KG 村簇（parcels sfWithin cluster），取重叠最大的。"""
    from rdflib import Literal, URIRef

    from app.infrastructure.kg.ontology import PLN, Relations

    try:
        graph = getattr(kg, "g", None)
        if graph is None:
            return None
        best = None
        best_overlap = 0
        seen: set = set()
        for bsm in bsms:
            for parcel in graph.subjects(PLN.bsm, Literal(str(bsm))):
                for _, _, cluster in graph.triples((parcel, Relations.sfWithin, None)):
                    key = str(cluster)
                    if key in seen:
                        continue
                    seen.add(key)
                    # parcel→settlement 的 sfWithin 边本身就是簇归属证据；
                    # 取重叠最大的簇，首个命中即可（避免 overlap=0 被吞）。
                    if best is None:
                        best = key
                        best_overlap = 0
                    overlap = len(_cluster_bsms_of(kg, key) & bsms)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best = key
        return best
    except Exception:  # noqa: BLE001
        return None


def _is_placeholder_name(name: str, role: str) -> bool:
    name = str(name or "").strip()
    if not name:
        return True
    markers = {
        "village": ("居民点", "settlement", "cluster"),
        "facility": ("facility_", "设施_", "unknown"),
        "water": ("水体_", "水域", "溪流_"),
        "road": ("道路_", "行政界线_"),
    }.get(role, ())
    return any(m in name for m in markers)


def _inject_anchors_into_kg(context: Any, kg: Any, anchors: list, session_id: str) -> int:
    """把接地结果写回 KG 实体（幂等）：村名→簇、设施/水/路→实体名 + 语义注解。

    这样 KG 自包含：EXPLORE/get_village_cognition 直接读到真实村名与实体。
    """
    from rdflib import Literal

    from app.infrastructure.kg import EntityAnnotation, get_semantic_memory
    from app.infrastructure.kg.ontology import PLN, Relations

    graph = getattr(kg, "g", None)
    if graph is None:
        return 0
    memory = get_semantic_memory()
    written = 0
    for anchor in anchors:
        if not anchor.normalized_name:
            continue
        # 村：按 BSM 找 KG 聚落簇，把真实村名写上去（居民点N → 园寨村）
        if anchor.role == "village" and anchor.source_bsms:
            from rdflib import Literal as _Lit, URIRef as _URIRef

            written_cluster = False
            for bsm in anchor.source_bsms[:6]:
                if written_cluster:
                    break
                ps = list(graph.subjects(PLN.bsm, _Lit(str(bsm))))
                for parcel in ps:
                    _tris = list(graph.triples((parcel, Relations.sfWithin, None)))
                    for _, _, cluster in _tris:
                        if "settlement" not in str(cluster):
                            continue
                        cref = _URIRef(cluster)
                        current = str(graph.value(cref, PLN.name) or "")
                        if _is_placeholder_name(current, "village"):
                            graph.set((cref, PLN.name, _Lit(anchor.normalized_name)))
                            written += 1
                        memory.add_entity_annotation(EntityAnnotation(
                            entity_uri=cref,
                            entity_type="ResidentialCluster",
                            description=f"自然村「{anchor.normalized_name}」（L1 接地）",
                            source_text_refs=[anchor.source_report_ref] if anchor.source_report_ref else [],
                            round_added=1,
                            valid_from_round=1,
                            confidence=max(anchor.confidence, 0.3),
                        ))
                        written_cluster = True
                        break
                    if written_cluster:
                        break
            if written_cluster:
                continue
        # 设施/水/路：实体已有真实名（http entity_ref）时写名（占位名才写）
        if anchor.entity_ref and str(anchor.entity_ref).startswith("http"):
            current = str(graph.value(anchor.entity_ref, PLN.name) or "")
            if _is_placeholder_name(current, anchor.role):
                graph.set((anchor.entity_ref, PLN.name, Literal(anchor.normalized_name)))
                written += 1
            memory.add_entity_annotation(EntityAnnotation(
                entity_uri=anchor.entity_ref,
                entity_type=anchor.entity_type or anchor.role,
                description=f"L1 锚点「{anchor.normalized_name}」（{anchor.role}）",
                source_text_refs=[anchor.source_report_ref] if anchor.source_report_ref else [],
                round_added=1,
                valid_from_round=1,
                confidence=max(anchor.confidence, 0.3),
            ))
    if written:
        logger.info("[ground_anchors] injected %d names into KG entities", written)
    return written


def _context_report_text(context: Any) -> str:
    """报告正文（LLM 村庄/水系分配的证据来源），来自 context.reports。"""
    parts: List[str] = []
    reports = getattr(context, "reports", None) or {}
    if isinstance(reports, dict):
        for payload in reports.values():
            if isinstance(payload, dict):
                parts.append(str(payload.get("content") or payload.get("summary") or ""))
            else:
                parts.append(str(payload or ""))
    return "\n".join(part for part in parts if part)[:12000]


def _fact_mentions(facts: List[Any]) -> list["NameMention"]:
    """L1 location_facts → name_backfill mentions（名字回填 KG 无名实体）。"""
    from app.infrastructure.kg.enrichment.name_backfill import NameMention

    mentions: List[NameMention] = []
    seen: set = set()
    for fact in facts or []:
        name = str(getattr(fact, "normalized_name", "") or getattr(fact, "mention", "") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        mentions.append(
            NameMention(
                name=name,
                role=str(getattr(fact, "role", "unknown") or "unknown"),
                location=str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "").strip(),
                source_dimension=str(getattr(fact, "dimension_key", "") or ""),
            )
        )
    return mentions


async def _llm_reason_candidate(
    llm: Any,
    mention: str,
    role: str,
    hints: str,
    candidates: list,
) -> Optional[Any]:
    """有界 LLM 判别：只在候选内选最优（设计 §4.3）。返回候选或 None。

    失败返回 None（调用方回退到确定性首选，仍产出可用 best-effort 结果）。
    """
    if not candidates:
        return None
    if llm is None:
        return None
    lines = "\n".join(
        f"{i}. 名称={c.canonical_name} 类型={c.entity_type} 角色={c.role if hasattr(c, 'role') else 'unknown'} "
        f"BSM={','.join(c.source_bsms[:5]) or '无'} 几何={c.geometry_ref or '无'} 得分={c.score:.3f}"
        for i, c in enumerate(candidates, 1)
    )
    prompt = (
        f"地名「{mention}」（类型 {role}）位于「{hints or '未知'}」。以下是从 KG/索引召回"
        f"的候选实体，请选择最匹配的一个（只输出编号；都不可用时输出 0）：\n{lines}"
    )
    try:
        import asyncio

        if asyncio.iscoroutinefunction(getattr(llm, "ainvoke", None)):
            response = await llm.ainvoke(prompt)
        else:
            response = await asyncio.to_thread(llm.invoke, prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] LLM reason failed: %s", exc)
        return None
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(content)
    import re

    match = re.search(r"\b([0-9]+)\b", str(content or ""))
    if match is None:
        return None
    index = int(match.group(1)) - 1
    if 0 <= index < len(candidates):
        return candidates[index]
    return None


def _village_anchor_bsms(context: Any, hints: str) -> List[str]:
    """从 spatial_hint 解析自然村 → gazetteer BSMs（粗证据，best-effort 兜底）。"""
    if not hints or getattr(context, "gazetteer", None) is None:
        return []
    from app.spatial.grounding.topology import hint_tokens

    bsms: List[str] = []
    for token in hint_tokens(hints):
        for candidate in (token, f"{token}村", f"{token}自然村"):
            entry = context.gazetteer.resolve(candidate, fuzzy=False)
            if entry is not None:
                bsms.extend(str(b) for b in (entry.bsms or []) if b)
                break
    return list(dict.fromkeys(bsms))


def _poi_anchor_bsms(context: Any, fact: Any) -> List[str]:
    """设施 POI 点位 → 邻近地块（同坐标=同实体；几何来自 bundle）。"""
    role = str(getattr(fact, "role", "") or "")
    if role != "facility":
        return []
    workspace = getattr(context, "workspace", None)
    if workspace is None:
        return []
    name = str(getattr(fact, "normalized_name", "") or getattr(fact, "mention", "") or "").strip()
    if not name:
        return []
    try:
        from app.spatial.grounding.grounding import query_parcels_near_entity

        parcels = list(context.current_parcels() or [])
        if not parcels:
            return []
        points = list((workspace.points.get("facilities_current") or []) or [])
        hit: List[str] = []
        for pt in points:
            text = str(getattr(pt, "facility_name", "") or "")
            if not text:
                continue
            if text in name or name[0] == text:
                geom = getattr(pt, "geometry", None) or {}
                coords = geom.get("coordinates") if isinstance(geom, dict) else None
                if coords and len(coords) >= 2:
                    hit.extend(
                        query_parcels_near_entity(
                            parcels,
                            (float(coords[0]), float(coords[1])),
                            max_distance_m=500,
                        )
                    )
        return list(dict.fromkeys(hit))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ground_anchors] POI anchor failed: %s", exc)
        return []


def _anchor_from_candidate(
    fact: Any,
    candidate: Any,
    *,
    best_effort: bool,
    topology_evidence: Optional[List[str]] = None,
    query_trace: Optional[List[dict]] = None,
) -> GroundedAnchor:
    from app.spatial.grounding.coordinate_identity import coordinate_key

    mention = str(getattr(fact, "mention", "") or getattr(fact, "normalized_name", "") or "")
    normalized = str(getattr(fact, "normalized_name", "") or mention)
    status = "resolved"
    if best_effort:
        confidence = float(getattr(candidate, "score", 0.0) or 0.0)
        status = "resolved" if confidence > 0 else "ambiguous"
    else:
        confidence = float(getattr(candidate, "score", 0.0) or 0.0)
    geometry_ref = getattr(candidate, "geometry_ref", None) or None
    entity_ref = str(getattr(candidate, "entity_ref", "") or "")
    # 优先 KG 实体 URI；candidate 可能是索引/兜底/聚落等来源
    candidate_refs = list(getattr(candidate, "entity_refs", None) or []) or ([entity_ref] if entity_ref else [])
    http_refs = [str(r) for r in candidate_refs if str(r).startswith("http")]
    if http_refs:
        entity_ref = http_refs[0]
    return GroundedAnchor(
        location_fact_ref=str(getattr(fact, "source_report_ref", "") or ""),
        mention=mention,
        normalized_name=normalized,
        role=str(getattr(fact, "role", "unknown") or "unknown"),
        entity_ref=entity_ref,
        entity_type=str(getattr(candidate, "entity_type", "") or ""),
        geometry_ref=geometry_ref,
        source_bsms=list(getattr(candidate, "source_bsms", None) or []),
        relation_refs=list(getattr(candidate, "relation_refs", None) or []),
        topology_evidence=list(topology_evidence or []),
        coordinate_key=coordinate_key(geometry_ref),
        confidence=round(max(confidence, 0.0), 4),
        status=status,
        best_effort=best_effort,
        source_report_ref=str(getattr(fact, "source_report_ref", "") or ""),
        source_span=str(getattr(fact, "source_span", "") or ""),
        query_trace=list(query_trace or []),
    )


async def ground_l1_anchors(
    context: Any,
    session_id: str,
    *,
    cache_path: Optional[Path] = None,
    llm: Any = None,
    bump: bool = True,
) -> List[GroundedAnchor]:
    """核心：L1 锚点接地（name_backfill → 索引 → 解析 → LLM 兜底 → 注解）。

    ``bump=False`` 用于上下文水合（只回填/建索引，不写注解、不 bump kg_version）。
    """
    facts = list(getattr(context, "location_facts", []) or [])
    if not facts:
        return []
    kg = getattr(context, "kg", None)

    # 1) 真名回填 KG 无名实体（确定性单候选；多候选 flash 消歧；缓存可重放）
    if kg is not None:
        mentions = _fact_mentions(facts)
        if mentions:
            try:
                from app.infrastructure.kg.enrichment.name_backfill import backfill_kg_names

                await backfill_kg_names(
                    kg,
                    getattr(context, "gazetteer", None),
                    mentions,
                    llm=llm,
                    cache_path=cache_path,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ground_anchors] name backfill failed: %s", exc)

    # 2) 重建 gazetteer + 证据索引（同坐标=同实体在索引构建内生效）。
    #    保留既有富化条目（村庄聚落映射等）——gazetteer 是累积证据，重建不丢弃。
    try:
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.kg.memory import get_semantic_memory

        memory = get_semantic_memory()
        previous = getattr(context, "gazetteer", None)
        previous_entries = {
            str(getattr(e, "name", "") or ""): e
            for e in (getattr(previous, "entries", None) or [])
            if getattr(e, "name", "")
        }
        gazetteer = build_gazetteer(
            kg,
            getattr(context, "workspace", None),
            memory,
        )
        for name, entry in previous_entries.items():
            if gazetteer.resolve(name, fuzzy=False) is None:
                gazetteer.upsert(entry)
        context.gazetteer = gazetteer
        if getattr(context, "ports", None) is not None:
            from app.infrastructure.kg.adapters.gazetteer_adapter import KGGazetteerAdapter

            context.ports.gazetteer = KGGazetteerAdapter(gazetteer)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] gazetteer rebuild failed: %s", exc)

    # 2.5) L1 村名 → GIS 地块绑定（复用既有村庄绑定，证据优先：bundle 内
    #      含村名且几何可用的 feature 才建条目；BSM 来自 bundle）。
    try:
        from app.infrastructure.kg.enrichment.report_entity_enrichment import (
            _location_fact_mentions,
            _materialize_gis_village_entries,
        )

        bases = list(dict.fromkeys(
            str(item.get("name", ""))[:-1]
            for item in _location_fact_mentions(facts)
            if str(item.get("name", "")).endswith("村")
        ))
        if bases:
            _materialize_gis_village_entries(
                gazetteer,
                getattr(context, "workspace", None),
                bases,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] GIS village binding failed: %s", exc)

    # 2.6) 村/水系聚落映射（宅基地→聚落、水域→水体；LLM 只在报告证据内分配名字，
    #      fail-closed：无证据/无 LLM 时返回空，不伪造分配）。
    try:
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            assign_water_bodies,
        )

        parcels = list(context.current_parcels() or [])
        report_text = _context_report_text(context)
        village_names = [
            str(getattr(f, "normalized_name", "") or "").strip()
            for f in facts
            if str(getattr(f, "role", "") or "") == "village"
        ]
        water_names = [
            str(getattr(f, "normalized_name", "") or "").strip()
            for f in facts
            if str(getattr(f, "role", "") or "") == "water"
        ]
        if parcels and report_text and (village_names or water_names):
            if village_names:
                village_entries = await assign_villages_to_clusters(
                    gazetteer,
                    parcels,
                    village_names,
                    report_text,
                    llm=llm,
                    cache=cache_path,
                )
                for entry in village_entries:
                    gazetteer.upsert(entry)
            if water_names:
                water_entries = await assign_water_bodies(
                    gazetteer,
                    parcels,
                    water_names,
                    report_text,
                    llm=llm,
                    cache=cache_path,
                )
                for entry in water_entries:
                    gazetteer.upsert(entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] village/water cluster mapping failed: %s", exc)

    from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

    context.evidence_index = PlaceEvidenceIndex.build(context)

    # 3) 逐 fact 解析（索引 → 拓扑评分 → LLM 兜底，不允许留空）
    anchors: List[GroundedAnchor] = []
    for fact in facts:
        mention = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "mention", "")
            or ""
        ).strip()
        if not mention:
            continue
        role = str(getattr(fact, "role", "unknown") or "unknown")
        hints = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
        trace: List[dict] = [{"step": "resolve", "mention": mention}]

        # 规划范围识别：village_name（如 金田村）是行政村/项目规划范围，不是
        # 可落位的地点事实；作为 administrative_village 锚点记录，不进自然村池。
        if _is_scope_fact(fact, getattr(context, "village_name", "")):
            scope = _scope_anchor(fact, context, trace)
            if scope is not None:
                anchors.append(scope)
                continue
        try:
            result = context.evidence_index.resolve_mention(mention, role=role, hints=hints)
            trace.extend(result.query_trace)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ground_anchors] resolve failed %s: %s", mention, exc)
            result = None

        candidate = None
        topology_evidence: List[str] = []
        best_effort = False
        if result is not None and result.candidates:
            if result.status == "resolved":
                candidate = result.candidates[0]
            else:
                # 歧义/弱证据 → LLM 在候选内判别；失败回退确定性首选（best-effort）
                candidate = await _llm_reason_candidate(llm, mention, role, hints, result.candidates)
                if candidate is None:
                    candidate = result.candidates[0]
                best_effort = True
                trace.append({"step": "llm_reason", "picked": candidate.canonical_name, "best_effort": True})
        else:
            # 无索引候选 → 兜底：POI 点位 / 自然村 anchor / LLM 判别 gazetteer 候选
            best_effort = True
            poi_bsms = _poi_anchor_bsms(context, fact)
            village_bsms = _village_anchor_bsms(context, hints)
            if poi_bsms or village_bsms:
                candidate = _best_effort_candidate(fact, poi_bsms, village_bsms, trace)
            else:
                candidate = await _llm_anchor_fallback(context, llm, fact, mention, role, hints, trace)
            trace.append({"step": "fallback", "best_effort": True})

        if candidate is not None:
            if kg is not None:
                try:
                    from app.spatial.grounding.topology import topology_evidence_for

                    graph = getattr(kg, "g", None) or kg
                    topology_evidence = topology_evidence_for(
                        graph,
                        str(getattr(candidate, "entity_ref", "") or ""),
                        hints=hints,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[ground_anchors] topology evidence failed: %s", exc)
            anchor = _anchor_from_candidate(
                fact,
                candidate,
                best_effort=best_effort,
                topology_evidence=topology_evidence,
                query_trace=trace,
            )
            # 复杂空间描述（贯穿/走向/汇入…）→ 让 LLM 在同类候选里按空间语义
            # 挑实体级候选，避免都归并到村锚点（不靠正则解析方位）。
            anchor = await _llm_orientation_rebind(context, fact, anchor, llm)
            # 充分利用 KG 拓扑：设施@村（如 祠堂@社前村）用 serves/nearby +
            # 村簇 BSM 重叠在多个同名设施点里消歧，不靠 bundle 近邻近似。
            if anchor.role == "facility":
                anchor = _topology_refine_facility(context, fact, anchor)
            # 村锚点必须有空间引用：resolved 但 bsms=0 的村（如真实 LLM 未映射到
            # 簇）强制走兜底——gazetteer 村条目 → LLM → 确定性分配到未占用聚落。
            if (
                anchor.role == "village"
                and not anchor.source_bsms
                and not anchor.geometry_ref
            ):
                anchor = await _village_spatial_fallback(
                    context, fact, anchor, llm, trace
                )
            elif (
                anchor.role in ("water", "road")
                and not anchor.source_bsms
                and not anchor.geometry_ref
            ):
                anchor = _linear_spatial_fallback(context, fact, anchor, trace)
            anchors.append(anchor)

    # 4) 同坐标 = 同实体：按坐标去重合并
    anchors = _dedupe_anchors_by_coordinate(anchors)

    # 4.5) 把接地推理结果注入 KG 实体（L1 后：村名→簇、设施/水/路→实体名），
    #      让 KG 自带语义，下游 EXPLORE/GROUND 直接消费（设计 §5.1）。
    if kg is not None and anchors:
        try:
            _inject_anchors_into_kg(context, kg, anchors, session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ground_anchors] inject anchors into KG failed: %s", exc)

    # 5) 语义注解 + 版本 bump（水合路径跳过）
    if bump and anchors:
        try:
            from app.infrastructure.kg import EntityAnnotation, get_kg_manager, get_semantic_memory

            memory = get_semantic_memory()
            for anchor in anchors:
                if not anchor.entity_ref:
                    continue
                memory.add_entity_annotation(
                    EntityAnnotation(
                        entity_uri=anchor.entity_ref,
                        entity_type=anchor.entity_type or anchor.role,
                        description=f"L1 锚点「{anchor.mention}」（{anchor.role}）",
                        source_text_refs=[anchor.source_report_ref] if anchor.source_report_ref else [],
                        round_added=1,
                        valid_from_round=1,
                        confidence=max(anchor.confidence, 0.3),
                    )
                )
            get_kg_manager().bump_version(session_id)
            from app.infrastructure.kg.memory import save_memory_state

            save_memory_state(session_id, 1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ground_anchors] KG annotation failed: %s", exc)

    logger.info(
        "[ground_anchors] session=%s anchors=%d best_effort=%d",
        session_id,
        len(anchors),
        sum(1 for a in anchors if a.best_effort),
    )
    return anchors


def _best_effort_candidate(fact: Any, poi_bsms: List[str], village_bsms: List[str], trace: List[dict]) -> Any:
    """构造 best-effort 候选（几何/BSM 全部来自 bundle/gazetteer）。"""
    from types import SimpleNamespace

    bsms = list(dict.fromkeys([*poi_bsms, *village_bsms]))
    trace.append({"step": "best_effort_bsms", "count": len(bsms)})
    return SimpleNamespace(
        entity_ref="",
        entity_type=str(getattr(fact, "role", "unknown") or "unknown"),
        canonical_name=str(getattr(fact, "normalized_name", "") or ""),
        source_bsms=bsms,
        geometry_ref="bundled:coarse" if bsms else None,
        relation_refs=[],
        score=0.35 if bsms else 0.0,
    )


async def _llm_anchor_fallback(
    context: Any,
    llm: Any,
    fact: Any,
    mention: str,
    role: str,
    hints: str,
    trace: List[dict],
) -> Optional[Any]:
    """索引无候选时：用 hint token 在 gazetteer 召回候选，LLM 判别（仍无几何则 0 分）。"""
    candidates: List[Any] = []
    if getattr(context, "gazetteer", None) is not None and hints:
        from app.spatial.grounding.topology import hint_tokens

        for token in hint_tokens(hints):
            entry = context.gazetteer.resolve(token, fuzzy=True)
            if entry is None or not (entry.bsms or []):
                continue
            from types import SimpleNamespace

            candidates.append(
                SimpleNamespace(
                    entity_ref=str(getattr(entry, "entity_uri", "") or f"gazetteer:{token}"),
                    entity_type="village",
                    canonical_name=str(getattr(entry, "name", "") or token),
                    source_bsms=list(entry.bsms or []),
                    geometry_ref=(
                        f"POINT({entry.centroid[0]} {entry.centroid[1]})"
                        if getattr(entry, "centroid", None) and len(entry.centroid) >= 2
                        else None
                    ),
                    relation_refs=[],
                    score=0.4,
                )
            )
    picked = await _llm_reason_candidate(llm, mention, role, hints, candidates)
    if picked is None and candidates:
        picked = candidates[0]
    if picked is not None:
        trace.append({"step": "gazetteer_llm_fallback", "picked": picked.canonical_name})
    return picked


def _dedupe_anchors_by_coordinate(anchors: List[GroundedAnchor]) -> List[GroundedAnchor]:
    """同坐标 = 同一实体：坐标相同的锚点合并（保留高置信与全部证据）。"""
    kept: List[GroundedAnchor] = []
    for anchor in anchors:
        if not anchor.coordinate_key:
            kept.append(anchor)
            continue
        target = next(
            (a for a in kept if a.coordinate_key == anchor.coordinate_key and a.role == anchor.role),
            None,
        )
        if target is None:
            kept.append(anchor)
            continue
        target.source_bsms = list(dict.fromkeys([*target.source_bsms, *anchor.source_bsms]))
        if not target.entity_ref and anchor.entity_ref:
            target.entity_ref = anchor.entity_ref
        target.relation_refs = list(dict.fromkeys([*target.relation_refs, *anchor.relation_refs]))
        target.topology_evidence = list(
            dict.fromkeys([*target.topology_evidence, *anchor.topology_evidence])
        )
        if anchor.normalized_name != target.normalized_name and anchor.normalized_name not in target.relation_refs:
            target.relation_refs.append(anchor.normalized_name)
        target.confidence = max(target.confidence, anchor.confidence)
        target.best_effort = target.best_effort or anchor.best_effort
        target.query_trace.append({"step": "coordinate_merge", "merged": anchor.normalized_name})
    return kept


async def ground_anchors(state: Dict[str, Any], *, base_dir: str = ".run-tmp") -> Dict[str, Any]:
    """工作流入口：L1 gate PASS 后调用（设计 §5.1，无新节点）。

    加载 L1Snapshot → PlanningContext → ``ground_l1_anchors`` → 持久化
    ``grounded_anchors`` artifact。
    """
    from app.infrastructure.artifacts.runtime import store_artifact
    from app.contracts.domain.l1_contracts import L1Snapshot
    from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor

    session_id = str(state.get("session_id", "") or state.get("run_id", ""))
    if not session_id:
        return {}
    context = await _require_ground_context(state)
    if context is None:
        return {}

    snapshot = None
    try:
        from app.infrastructure.artifacts.runtime import load_artifact

        snapshot = load_artifact(state, "l1_snapshot", L1Snapshot)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ground_anchors] L1 snapshot load failed: %s", exc)
    if snapshot is not None and not getattr(context, "location_facts", None):
        context.location_facts = list(getattr(snapshot, "location_facts", []) or [])

    from app.infrastructure.llm.factory import create_flash_llm

    llm = None
    try:
        llm = create_flash_llm(max_tokens=300, temperature=0.1)
    except Exception:  # noqa: BLE001
        llm = None

    from app.infrastructure.paths import session_run_dir

    cache_path = None
    try:
        cache_path = session_run_dir(session_id) / "grounded-anchor-cache.json"
    except Exception:  # noqa: BLE001
        cache_path = None

    anchors = await ground_l1_anchors(
        context,
        session_id,
        cache_path=cache_path,
        llm=llm,
        bump=True,
    )
    if not anchors:
        return {}

    run_id = str(state.get("run_id", "") or session_id)
    artifact = store_artifact(
        state,
        "grounded_anchors",
        "ground",
        "GroundedAnchorList",
        [a.model_dump(mode="json") for a in anchors],
        base_dir=base_dir,
    )
    ref = ArtifactDescriptor.model_validate(artifact)
    logger.info("[ground_anchors] persisted artifact %s (%d anchors)", ref.artifact_id, len(anchors))
    return {
        "artifact_refs": {"grounded_anchors": ref.model_dump(mode="json")},
        "grounded_anchor_count": len(anchors),
    }


async def _require_ground_context(state: Dict[str, Any]) -> Optional[Any]:
    """获取/构建 PlanningContext（复用 workflow 的 bootstrap 语义）。"""
    try:
        from app.infrastructure.context.planning_context_factory import get_cached_context
        from app.workflow.layers.context_bootstrap import bootstrap_context_node

        session_id = str(state.get("session_id", "") or "")
        context = get_cached_context(session_id) if session_id else None
        if context is None:
            await bootstrap_context_node(state)
            context = get_cached_context(session_id) if session_id else None
        return context
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] context unavailable: %s", exc)
        return None


__all__ = [
    "ground_anchors",
    "ground_l1_anchors",
    "GroundedAnchor",
]