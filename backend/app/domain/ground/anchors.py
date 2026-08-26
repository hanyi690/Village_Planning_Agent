"""ground_anchors — L1 锚点接地（设计 §5.1/§6）。

domain/ground 唯一拥有"接地"：把 ``L1Snapshot.location_facts`` 编译为
``GroundedAnchor[]``（mention → entity_ref/BSM/geometry + topology_evidence），
并富化 KG（真名回填、语义注解、关系注记）与重建 ``EvidenceGraph``。

原则：
- 同一坐标 = 同一实体（``app.spatial.grounding.coordinate_identity``）。
- 空间操作全部留在 ``app.spatial`` / ``app.evidence.index``；本模块只编排。
- 不允许留下不可解析的地点：即使置信度低，LLM 在 KG/索引候选内推理出可用结果
  （``best_effort=True`` + 低置信），几何/BSM 永远来自 KG/bundle，不来自 LLM。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.contracts.spatial.spatial_reference_contracts import (
    CandidateSelectionProposal,
    spatial_candidate_descriptor,
    spatial_candidate_input_digest,
    stable_spatial_candidate_id,
    validate_spatial_candidate_proposal,
)
from app.contracts.spatial.grounding_contracts import GroundedAnchor
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _new_ground_llm_budget(
    context: Any = None,
    *,
    scope_key: str = "anchors",
) -> Dict[str, Any]:
    """Return one bounded best-effort budget for this grounding scope."""
    from app.spatial.grounding.call_budget import get_ground_llm_budget

    return get_ground_llm_budget(
        context,
        scope_key=f"{scope_key}:{getattr(context, 'session_id', '')}",
    )


def _reserve_ground_llm_call(budget: Optional[Dict[str, Any]]) -> float | None:
    """Reserve one fallback call and return its remaining timeout."""
    from app.spatial.grounding.call_budget import reserve_ground_llm_call

    return reserve_ground_llm_call(budget)


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
    budget: Optional[Dict[str, Any]] = None,
) -> GroundedAnchor:
    """空间描述（如 西南至东北贯穿金田村）→ LLM 在同类候选里选实体级候选。

    触发：水/路/地标 且 hint 含方位/走向标记 且当前锚点是村锚点/粗绑定。
    LLM 只在索引候选内判别（几何/BSM 来自 KG/bundle），不新增几何。
    """
    picked = await _llm_orientation_pick(context, fact, anchor, llm, budget=budget)
    if picked is None:
        return anchor
    return _orientation_rebound_anchor(fact, anchor, picked)


def _has_point_geometry(geometry_ref: Optional[str]) -> bool:
    from app.spatial.grounding.coordinate_identity import point_xy

    return point_xy(geometry_ref) is not None


def _has_spatial_evidence(anchor: Optional[Any], *, role: Optional[str] = None) -> bool:
    """Return whether an anchor has real KG/upload spatial evidence."""
    if anchor is None:
        return False
    geometry_ref = str(anchor.geometry_ref or "").strip().lower()
    if geometry_ref.startswith("bundled:") or geometry_ref in {"coarse", "approximate"}:
        return False
    anchor_role = str(role or getattr(anchor, "role", "") or "").strip()
    if anchor_role in {"facility", "road", "water", "landmark", "axis"}:
        return bool(
            geometry_ref
            or str(anchor.feature_bsm or "").strip()
            or str(anchor.source_feature_id or "").strip()
            or (
                anchor_role == "water"
                and any(str(bsm).strip() for bsm in (anchor.source_bsms or []))
            )
        )
    return bool(anchor.source_bsms or anchor.geometry_ref or anchor.entity_ref)


def _candidate_has_authoritative_geometry(candidate: Any) -> bool:
    """Only a bundle/source-feature candidate can become a resolved anchor."""
    geometry_ref = str(getattr(candidate, "geometry_ref", "") or "").strip().lower()
    if not geometry_ref or geometry_ref.startswith("bundled:"):
        return bool(
            str(getattr(candidate, "feature_bsm", "") or "").strip()
            and str(getattr(candidate, "source_feature_id", "") or "").strip()
        )
    return bool(
        geometry_ref.startswith("bundle://feature/")
        or str(getattr(candidate, "feature_bsm", "") or "").strip()
        or str(getattr(candidate, "source_feature_id", "") or "").strip()
    )


def _candidate_bundle_ref(candidate: Any) -> str:
    """Return an opaque Bundle geometry ref for LLM-facing candidate text."""
    bsm = str(
        getattr(candidate, "feature_bsm", "")
        or getattr(candidate, "source_bsm", "")
        or (
            getattr(candidate, "source_bsms", [])[0]
            if len(getattr(candidate, "source_bsms", []) or []) == 1
            else ""
        )
        or ""
    ).strip()
    return f"bundle://feature/{bsm}" if bsm else ""


def _index_role_candidates(context: Any, role: str) -> list:
    """从 EvidenceGraph 取同角色、有真实几何/地块的候选（供 LLM 判别）。"""
    from types import SimpleNamespace

    graph = getattr(context, "evidence_graph", None)
    if graph is None:
        return []
    out: list = []
    for entry in graph.iter_entries():
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


def _candidate_fingerprint(candidates: list) -> tuple:
    """Return a stable identity for the candidate set shown to the LLM.

    A name is not sufficient to identify grounding work: two roles can share a
    name, and the same role/name can resolve to different KG entities.  Keep
    the ordered candidate payload in the key because the prompt uses the
    candidate number, so changing either membership or order changes the work.
    """
    fingerprint = []
    for candidate in candidates or []:
        refs = tuple(str(ref) for ref in (getattr(candidate, "entity_refs", None) or []))
        bsms = tuple(str(bsm) for bsm in (getattr(candidate, "source_bsms", None) or []))
        relations = tuple(
            str(ref) for ref in (getattr(candidate, "relation_refs", None) or [])
        )
        fingerprint.append(
            (
                str(getattr(candidate, "entity_ref", "") or ""),
                refs,
                str(getattr(candidate, "entity_type", "") or ""),
                str(getattr(candidate, "role", "") or ""),
                str(getattr(candidate, "canonical_name", "") or ""),
                _candidate_bundle_ref(candidate),
                bsms,
                relations,
                float(getattr(candidate, "score", 0.0) or 0.0),
            )
        )
    return tuple(fingerprint)


def _grounding_work_key(item: Dict[str, Any], kind: str, candidates: list) -> tuple:
    """Key only work that has the same prompt semantics and candidate set."""
    fact = item["fact"]
    return (
        kind,
        item["role"],
        item["mention"],
        str(getattr(fact, "normalized_name", "") or ""),
        item["hints"],
        _candidate_fingerprint(candidates),
    )


def _orientation_candidates(context: Any, fact: Any, anchor: GroundedAnchor) -> list:
    """Return the exact candidate set eligible for orientation rebinding."""
    if anchor.role not in ("water", "road", "landmark", "facility"):
        return []
    hints = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
    if not any(marker in hints for marker in _ORIENTATION_MARKERS):
        return []
    if _has_point_geometry(anchor.geometry_ref):
        return []
    candidates = _index_role_candidates(context, anchor.role)
    return candidates if len(candidates) >= 2 else []


async def _llm_orientation_pick(
    context: Any,
    fact: Any,
    anchor: GroundedAnchor,
    llm: Any,
    budget: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """Resolve one orientation candidate; callers can fan it out per fact."""
    if llm is None:
        return None
    candidates = _orientation_candidates(context, fact, anchor)
    if not candidates:
        return None
    hints = str(getattr(fact, "spatial_hint", "") or getattr(fact, "source_span", "") or "")
    return await _llm_reason_candidate(
        llm,
        str(anchor.normalized_name or anchor.mention or ""),
        anchor.role,
        hints,
        candidates,
        budget=budget,
    )


def _orientation_rebound_anchor(
    fact: Any,
    anchor: GroundedAnchor,
    picked: Any,
) -> GroundedAnchor:
    """Build a fact-specific anchor from a shared orientation decision."""
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

    evidence_graph = getattr(context, "evidence_graph", None)
    if evidence_graph is None:
        return anchor
    # 候选：同角色、POINT 几何、带 KG 实体引用的索引条目
    best = None
    best_overlap = 0
    current_entity = str(getattr(anchor, "entity_ref", "") or "")
    for entry in evidence_graph.iter_entries():
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
    # Topology is only a disambiguation signal.  It must never downgrade an
    # exact bundle POINT to a KG entry that only carries parcel context.
    if not _has_point_geometry(getattr(best, "geometry_ref", None)):
        trace = list(getattr(anchor, "query_trace", None) or [])
        trace.append({
            "step": "kg_topology_facility",
            "refined": False,
            "reason": "topology_candidate_without_point_geometry",
            "overlap": best_overlap,
        })
        return anchor.model_copy(update={"query_trace": trace})
    from types import SimpleNamespace

    cand = SimpleNamespace(
        entity_ref=str((getattr(best, "entity_refs", None) or [""])[0]),
        entity_type=str((getattr(best, "entity_types", None) or ["facility"])[0]),
        canonical_name=str(getattr(best, "canonical_name", "") or ""),
        source_bsms=list(getattr(best, "source_bsms", None) or []),
        geometry_ref=getattr(best, "geometry_ref", None),
        feature_bsm=getattr(best, "feature_bsm", None),
        source_feature_id=getattr(best, "source_feature_id", None),
        source_layer=getattr(best, "source_layer", None),
        related_parcel_bsms=list(getattr(best, "related_parcel_bsms", None) or []),
        l1_fact_refs=list(getattr(best, "l1_fact_refs", None) or []),
        l1_snapshot_ref=getattr(best, "l1_snapshot_ref", ""),
        bundle_snapshot_digest=getattr(best, "bundle_snapshot_digest", ""),
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
    budget: Optional[Dict[str, Any]] = None,
) -> GroundedAnchor:
    """Resolve one village fallback while committing ownership in order."""
    plan = _village_spatial_fallback_plan(context, fact, anchor, trace)
    picked = None
    candidates = plan.get("candidates", [])
    mention = str(getattr(anchor, "normalized_name", "") or getattr(anchor, "mention", ""))
    hints = plan["hints"]
    if candidates and llm is not None and mention:
        picked = await _llm_reason_candidate(
            llm, mention, "village", hints, candidates, budget=budget
        )
    return _commit_village_spatial_fallback(context, plan, picked)


def _village_fallback_occupied(context: Any, fact: Any) -> set:
    """Snapshot occupied BSMs without mutating the ordered ownership state."""
    occupied: set = set()
    for other in getattr(context, "location_facts", []) or []:
        if other is fact:
            continue
        if str(getattr(other, "role", "") or "") != "village":
            continue
        other_name = str(
            getattr(other, "normalized_name", "")
            or getattr(other, "mention", "")
            or ""
        ).strip()
        if not other_name:
            continue
        entry = _resolve_gazetteer_entry_any(context, other_name)
        if entry is not None:
            occupied.update(str(b) for b in (entry.bsms or []))
    occupied |= set(getattr(context, "_grounding_used_cluster_bsms", set()) or set())
    return occupied


def _village_spatial_fallback_plan(
    context: Any,
    fact: Any,
    anchor: Optional[GroundedAnchor],
    trace: List[dict],
) -> Dict[str, Any]:
    """Prepare village fallback candidates without changing shared occupancy."""
    hints = str(
        getattr(fact, "spatial_hint", "")
        or getattr(fact, "source_span", "")
        or ""
    )
    village_bsms = _village_anchor_bsms(context, hints)
    poi_bsms = _poi_anchor_bsms(context, fact)
    if poi_bsms or village_bsms:
        candidate = _scope_candidate(fact, poi_bsms, village_bsms, trace)
        trace.append({
            "step": "village_fallback:gazetteer_bsms",
            "count": len(candidate.source_bsms),
        })
        return {
            "fact": fact,
            "anchor": anchor,
            "candidate": candidate,
            "candidates": [],
            "clusters": [],
            "hints": hints,
            "trace": trace,
        }

    try:
        from types import SimpleNamespace

        from app.spatial.grounding.village_cluster_mapper import build_village_clusters

        occupied = _village_fallback_occupied(context, fact)
        parcels = list(context.current_parcels() or [])
        clusters = sorted(build_village_clusters(parcels), key=lambda c: -c.area_ha)
        unassigned = [c for c in clusters if not (set(c.bsms) & occupied)]
        candidates = [
            SimpleNamespace(
                entity_ref=f"cluster:{cluster.index}",
                entity_type="village",
                canonical_name=f"聚落{cluster.index}",
                source_bsms=list(cluster.bsms),
                geometry_ref=(
                    f"POINT({cluster.centroid[0]} {cluster.centroid[1]})"
                    if cluster.centroid
                    else None
                ),
                relation_refs=[],
                score=0.4,
            )
            for cluster in unassigned
        ]
        return {
            "fact": fact,
            "anchor": anchor,
            "candidate": None,
            "candidates": candidates,
            "clusters": unassigned,
            "hints": hints,
            "trace": trace,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ground_anchors] cluster fallback planning failed: %s", exc)
        return {
            "fact": fact,
            "anchor": anchor,
            "candidate": None,
            "candidates": [],
            "clusters": [],
            "hints": hints,
            "trace": trace,
        }


def _commit_village_spatial_fallback(
    context: Any,
    plan: Dict[str, Any],
    picked: Optional[Any],
) -> Optional[GroundedAnchor]:
    """Commit one prepared village decision in original fact order."""
    fact = plan.get("fact")
    anchor = plan.get("anchor")
    trace = plan["trace"]
    direct = plan.get("candidate")
    if direct is not None:
        return _anchor_from_candidate(fact, direct, best_effort=True, query_trace=trace)

    occupied = _village_fallback_occupied(context, fact)
    available = [
        cluster
        for cluster in plan.get("clusters", [])
        if not (set(cluster.bsms) & occupied)
    ]
    selected = None
    if picked is not None:
        picked_bsms = set(getattr(picked, "source_bsms", None) or [])
        if picked_bsms and not (picked_bsms & occupied):
            selected = picked
    if selected is not None:
        trace.append({
            "step": "village_fallback:llm_cluster_assign",
            "picked": getattr(selected, "canonical_name", ""),
            "geometry": getattr(selected, "geometry_ref", ""),
        })
    elif available:
        trace.append({
            "step": "village_fallback:llm_selection_unresolved",
            "candidate_count": len(available),
        })
    if selected is None:
        if anchor is not None and _has_spatial_evidence(anchor):
            return anchor.model_copy(update={"query_trace": list(trace)})
        return None

    picked_bsms = set(getattr(selected, "source_bsms", None) or [])
    used = set(getattr(context, "_grounding_used_cluster_bsms", set()) or set())
    used |= picked_bsms
    setattr(context, "_grounding_used_cluster_bsms", used)
    return _anchor_from_candidate(fact, selected, best_effort=True, query_trace=trace)


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
                        if (
                            _is_placeholder_name(current, "village")
                            or current == str(getattr(context, "village_name", "") or "")
                        ):
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
            from rdflib import URIRef as _URIRef

            entity_ref_uri = _URIRef(anchor.entity_ref)
            current = str(graph.value(entity_ref_uri, PLN.name) or "")
            if _is_placeholder_name(current, anchor.role):
                graph.set((entity_ref_uri, PLN.name, Literal(anchor.normalized_name)))
                written += 1
            memory.add_entity_annotation(EntityAnnotation(
                entity_uri=entity_ref_uri,
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


def _fact_mentions(facts: List[Any]) -> list["NameMention"]:
    """L1 location_facts → name_backfill mentions（名字回填 KG 无名实体）。"""
    from app.infrastructure.kg.enrichment.name_backfill import NameMention

    mentions: List[NameMention] = []
    seen: set = set()
    for fact in facts or []:
        name = str(getattr(fact, "normalized_name", "") or getattr(fact, "mention", "") or "").strip()
        if not name:
            continue
        role = str(getattr(fact, "role", "unknown") or "unknown")
        location = str(
            getattr(fact, "spatial_hint", "")
            or getattr(fact, "source_span", "")
            or ""
        ).strip()
        mention_key = (name, role, location)
        if mention_key in seen:
            continue
        seen.add(mention_key)
        mentions.append(
            NameMention(
                name=name,
                role=role,
                location=location,
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
    *,
    budget: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """Use one strict stable-ID selector; failure remains unresolved."""
    if not candidates:
        return None
    if llm is None:
        return None
    call_timeout = _reserve_ground_llm_call(budget)
    if call_timeout is None:
        logger.info(
            "[ground_anchors] LLM selection budget exhausted; candidate remains unresolved for %s",
            mention,
        )
        return None
    descriptors = [
        spatial_candidate_descriptor(candidate, kind=role or "candidate")
        for candidate in candidates
    ]
    decision_id = f"ground-anchor:{role}:{mention}"
    query_text = f"{mention}\n{role}\n{hints}"
    input_digest = spatial_candidate_input_digest(
        decision_id=decision_id,
        query_text=query_text,
        candidates=descriptors,
    )
    lines = "\n".join(
        _candidate_prompt_line(candidate, descriptor.candidate_id)
        for candidate, descriptor in zip(candidates, descriptors)
    )
    prompt = (
        "根据报告证据，从下面这个运行时候选集合中做一次闭集选择。只返回 JSON 对象，不要解释。\n"
        f"地名={mention}；类型={role}；空间提示={hints or '未知'}\n"
        "字段必须完整：status 为 selected、abstain 或 ambiguous；"
        "selected_candidate_id 在 selected 时原样填写候选 candidate_id，"
        "否则填写空字符串；input_digest 必须原样复制。"
        f"input_digest={input_digest}\n{lines}"
    )
    try:
        from app.infrastructure.llm.structured import (
            run_structured_output,
            structured_failure_summary,
        )

        async def _invoke():
            return await run_structured_output(
                CandidateSelectionProposal,
                [{"role": "user", "content": prompt}],
                llm=llm,
                max_retries=1,
                timeout=call_timeout,
            )

        from app.spatial.grounding.call_budget import run_ground_llm_call

        response = await run_ground_llm_call(budget, call_timeout, _invoke)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[ground_anchors] LLM reason failed: %s",
            structured_failure_summary(exc),
        )
        return None
    decision = validate_spatial_candidate_proposal(
        decision_id=decision_id,
        query_text=query_text,
        candidates=descriptors,
        proposal=response,
    )
    if decision.status == "selected":
        selected_id = decision.selected_candidate_id
        for candidate, descriptor in zip(candidates, descriptors):
            if descriptor.candidate_id == selected_id:
                return candidate
    logger.info(
        "[ground_anchors] candidate selection status=%s reason=%s mention=%s",
        decision.status,
        decision.reason,
        mention,
    )
    return None


def _candidate_prompt_line(candidate: Any, candidate_id: str | None = None) -> str:
    """Render bounded candidate evidence for closed-set LLM selection.

    The LLM receives identity and provenance clues, never executable geometry.
    Every value is already attached to a bundle-backed candidate; the model
    can only return the stable ID and cannot invent a BSM or coordinate.
    """
    identity = getattr(candidate, "identity", None)
    canonical_name = str(
        getattr(candidate, "canonical_name", "")
        or getattr(identity, "canonical_name", "")
        or "未命名"
    ).strip()
    entity_type = str(
        getattr(candidate, "entity_type", "")
        or getattr(identity, "entity_type", "")
        or "unknown"
    ).strip()
    role = str(
        getattr(candidate, "role", "")
        or getattr(identity, "role", "")
        or "unknown"
    ).strip()
    aliases = list(
        dict.fromkeys(
            str(value).strip()
            for value in (
                getattr(candidate, "aliases", None)
                or getattr(identity, "aliases", None)
                or []
            )
            if str(value).strip()
        )
    )[:8]
    feature_bsm = str(
        getattr(candidate, "feature_bsm", "")
        or getattr(identity, "bundle_feature_bsm", "")
        or ""
    ).strip()
    source_bsm = str(
        getattr(candidate, "source_bsm", "")
        or getattr(identity, "source_bsm", "")
        or ""
    ).strip()
    source_bsms = list(
        dict.fromkeys(
            str(value).strip()
            for value in (getattr(candidate, "source_bsms", None) or [])
            if str(value).strip()
        )
    )[:8]
    related_parcels = list(
        dict.fromkeys(
            str(value).strip()
            for value in (getattr(candidate, "related_parcel_bsms", None) or [])
            if str(value).strip()
        )
    )[:8]
    relation_refs = list(
        dict.fromkeys(
            _short_evidence_ref(value)
            for value in (getattr(candidate, "relation_refs", None) or [])
            if str(value).strip()
        )
    )[:8]
    l1_refs = list(
        dict.fromkeys(
            str(value).strip()
            for value in (getattr(candidate, "l1_fact_refs", None) or [])
            if str(value).strip()
        )
    )[:6]
    provenance_refs = list(
        dict.fromkeys(
            _short_evidence_ref(value)
            for value in (getattr(candidate, "evidence_refs", None) or [])
            if str(value).strip()
        )
    )[:6]
    score = float(getattr(candidate, "score", 0.0) or 0.0)
    bundle_ref = _candidate_bundle_ref(candidate)
    candidate_id = candidate_id or stable_spatial_candidate_id(candidate, namespace="ground")
    return (
        f"candidate_id={candidate_id} 名称={canonical_name} 别名={'、'.join(aliases) or '无'} "
        f"类型={entity_type} 角色={role} 来源层={getattr(candidate, 'source_layer', '') or getattr(identity, 'source_layer', '') or '未知'} "
        f"feature_BSM={feature_bsm or '无'} source_BSM={source_bsm or '无'} "
        f"来源BSM={','.join(source_bsms) or '无'} 关联地块={','.join(related_parcels) or '无'} "
        f"bundle引用={bundle_ref or '无'} "
        f"KG关系={','.join(relation_refs) or '无'} L1事实={','.join(l1_refs) or '无'} "
        f"来源证据={','.join(provenance_refs) or '无'} 得分={score:.3f}"
    )


def _short_evidence_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


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
    # Evidence-index KG candidates may carry the storage prefix
    # ``kg_wkt:``.  The anchor contract exposes the canonical geometry form;
    # keep the prefix-free POINT representation so downstream renderers and
    # coordinate identity see the same value regardless of index construction
    # order.
    if isinstance(geometry_ref, str) and geometry_ref.startswith("kg_wkt:"):
        geometry_ref = geometry_ref[len("kg_wkt:"):].strip()
        if geometry_ref.startswith("POINT ("):
            geometry_ref = "POINT(" + geometry_ref[len("POINT ("):]
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
        feature_bsm=getattr(candidate, "feature_bsm", None),
        source_feature_id=getattr(candidate, "source_feature_id", None),
        source_layer=getattr(candidate, "source_layer", None),
        related_parcel_bsms=list(
            getattr(candidate, "related_parcel_bsms", None) or []
        ),
        source_bsms=list(getattr(candidate, "source_bsms", None) or []),
        relation_refs=list(getattr(candidate, "relation_refs", None) or []),
        l1_fact_refs=list(getattr(candidate, "l1_fact_refs", None) or []),
        l1_snapshot_ref=str(getattr(candidate, "l1_snapshot_ref", "") or ""),
        bundle_snapshot_digest=str(
            getattr(candidate, "bundle_snapshot_digest", "") or ""
        ),
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
    ground_llm_budget: Optional[Dict[str, Any]] = None,
) -> List[GroundedAnchor]:
    """核心：L1 锚点接地（name_backfill → 索引 → 解析 → LLM 兜底 → 注解）。

    ``bump=False`` 用于上下文水合（只回填/建索引，不写注解、不 bump kg_version）。
    """
    facts = list(getattr(context, "location_facts", []) or [])
    if not facts:
        return []
    kg = getattr(context, "kg", None)
    ground_llm_budget = ground_llm_budget or _new_ground_llm_budget(
        context,
        scope_key="anchors",
    )

    # 0.5) 先将上传 GIS 中明确带村名的要素绑定到运行时村簇；名称回填
    #      需要这份空间证据来收窄设施/道路候选，不能在其生成之后才补写。
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
                getattr(context, "gazetteer", None),
                getattr(context, "workspace", None),
                bases,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] GIS village binding failed: %s", exc)

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
                    budget=ground_llm_budget,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[ground_anchors] name backfill failed: %s", exc)

    # 2) 重建 gazetteer + EvidenceGraph（同坐标=同实体在图构建内生效）。
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
            village_name=str(getattr(context, "village_name", "") or ""),
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

    # 2.6) 村/水系聚落映射（宅基地→聚落、水域→水体；LLM 只在报告证据内分配名字，
    #      fail-closed：无证据/无 LLM 时返回空，不伪造分配）。
    try:
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            assign_water_bodies,
        )

        parcels = list(context.current_parcels() or [])
        from app.evidence.retrieval.retrievers.report_retriever import load_report_corpus

        report_text = await load_report_corpus(
            str(getattr(context, "session_id", "") or ""),
            context=context,
        )
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
                    context=context,
                    llm=llm,
                    cache=cache_path,
                    budget=ground_llm_budget,
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
                    budget=ground_llm_budget,
                )
                for entry in water_entries:
                    gazetteer.upsert(entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] village/water cluster mapping failed: %s", exc)

    from app.evidence.retrieval.evidence_graph import EvidenceGraph

    context.evidence_graph = EvidenceGraph.build(context)

    # 3) 先做确定性解析，再把相互独立的地点判别一次性有界并发。
    #    最终锚点写入、村簇占用和 KG 注解仍按原始顺序串行提交，避免共享
    #    ``_grounding_used_cluster_bsms`` 在并发兜底时发生竞态。
    prepared: List[Dict[str, Any]] = []
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
        scope_names = list(dict.fromkeys([
            str(value).strip()
            for value in (
                *(getattr(fact, "village_scopes", None) or []),
                *(getattr(fact, "place_scopes", None) or []),
            )
            if str(value).strip()
        ]))
        trace: List[dict] = [{"step": "resolve", "mention": mention}]
        item: Dict[str, Any] = {
            "fact": fact,
            "mention": mention,
            "role": role,
            "hints": hints,
            "trace": trace,
            "candidate": None,
            "best_effort": False,
            "llm_kind": None,
        }

        if _is_scope_fact(fact, getattr(context, "village_name", "")):
            item["candidate"] = _scope_anchor(fact, context, trace)
            item["scope"] = True
            prepared.append(item)
            continue

        try:
            result = context.evidence_graph.resolve_mention(mention, role=role, hints=hints)
            trace.extend(result.query_trace)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ground_anchors] resolve failed %s: %s", mention, exc)
            result = None
        item["result"] = result

        expansion: Dict[str, Any] = {}
        expand_support = getattr(
            context.evidence_graph,
            "expand_supporting_evidence",
            None,
        )
        if callable(expand_support):
            try:
                expansion = expand_support(
                    mention,
                    role=role,
                    hints=hints,
                    scope_names=scope_names,
                    direct_result=result,
                    source_feature_ids=list(
                        getattr(fact, "source_feature_ids", None) or []
                    ),
                ) or {}
                trace.extend(list(expansion.get("query_trace", []) or []))
            except Exception as exc:  # noqa: BLE001
                trace.append({
                    "step": "supporting_evidence_error",
                    "error": type(exc).__name__,
                })

        inferred_scope_candidate = expansion.get("inferred_scope_candidate")
        supporting_candidates = list(expansion.get("candidates", []) or [])
        expansion_scope_names = next(
            (
                item.get("scope_names", [])
                for item in (expansion.get("query_trace", []) or [])
                if item.get("step") == "supporting_evidence_start"
            ),
            [],
        )
        strict_scope_requested = (
            role in {"facility", "landmark"}
            and bool(scope_names or expansion_scope_names)
        )
        strict_scope = expansion.get("status") in {"resolved", "ambiguous"} and any(
            item.get("step") == "strict_facility_scope"
            for item in (expansion.get("query_trace", []) or [])
        )
        if result is not None and result.candidates:
            candidate_pool = list(result.candidates)
        else:
            candidate_pool = []
        if strict_scope:
            candidate_pool = supporting_candidates
        elif strict_scope_requested:
            candidate_pool = []
        elif not candidate_pool and supporting_candidates:
            candidate_pool = supporting_candidates

        candidate_has_spatial = any(
            _has_spatial_evidence(candidate, role=role)
            for candidate in candidate_pool
        )
        if inferred_scope_candidate is not None and (
            not candidate_pool
            or not candidate_has_spatial
            or result is None
            or result.status != "resolved"
        ) and role in {"village", "natural_village", "unknown"}:
            item["candidate"] = inferred_scope_candidate
            item["best_effort"] = True
            item["supporting_evidence_status"] = "inferred"
            trace.append({
                "step": "consume_inferred_scope_candidate",
                "best_effort": True,
                "geometry_granularity": "parcel_set",
            })
        elif candidate_pool:
            if role in {"facility", "road", "water", "landmark", "axis"}:
                spatial_candidates = [
                    candidate
                    for candidate in candidate_pool
                    if _has_spatial_evidence(candidate, role=role)
                ]
                if spatial_candidates:
                    trace.append({
                        "step": "spatial_identity_filter",
                        "role": role,
                        "before": len(candidate_pool),
                        "after": len(spatial_candidates),
                    })
                    candidate_pool = spatial_candidates
            resolved = (
                (result is not None and result.status == "resolved")
                or expansion.get("status") == "resolved"
            )
            if resolved and len(candidate_pool) == 1:
                item["candidate"] = next(iter(candidate_pool))
            else:
                item["best_effort"] = True
                item["llm_kind"] = "candidate"
                item["llm_candidates"] = candidate_pool
        else:
            item["best_effort"] = True
            poi_bsms = _poi_anchor_bsms(context, fact)
            village_bsms = _village_anchor_bsms(context, hints)
            if role == "village" and (poi_bsms or village_bsms):
                item["candidate"] = _scope_candidate(
                    fact, poi_bsms, village_bsms, trace
                )
                trace.append({
                    "step": "scope_only_candidate",
                    "role": role,
                    "spatial_identity": "unresolved",
                })
            else:
                # A nearby parcel pool is not an identity for a road, water,
                # or facility.  Keep the typed gap visible and require an
                # EvidenceGraph/source-feature candidate instead of promoting
                # a coarse BSM set through a fallback.
                trace.append({
                    "step": "identity_candidate_missing",
                    "role": role,
                    "spatial_identity": "unresolved",
                })
        prepared.append(item)

    llm_groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for item in prepared:
        kind = item.get("llm_kind")
        candidates = item.get("llm_candidates", [])
        if kind == "candidate":
            key = _grounding_work_key(item, kind, candidates)
            llm_groups.setdefault(key, []).append(item)
        elif kind == "fallback":
            key = _grounding_work_key(item, kind, candidates)
            llm_groups.setdefault(key, []).append(item)

    llm_tasks = []
    llm_group_items = []
    for group in llm_groups.values():
        representative = group[0]
        candidates = representative.get("llm_candidates", [])
        llm_tasks.append(_llm_reason_candidate(
            llm,
            representative["mention"],
            representative["role"],
            representative["hints"],
            candidates,
            budget=ground_llm_budget,
        ))
        llm_group_items.append(group)
    if llm_tasks:
        logger.info(
            "[ground_anchors] concurrent fact fallback groups=%d facts=%d max_concurrent=%d",
            len(llm_tasks),
            sum(len(group) for group in llm_group_items),
            int(ground_llm_budget.get("max_concurrent", 1) or 1),
        )
        decisions = await asyncio.gather(*llm_tasks, return_exceptions=True)
        for group, decision in zip(llm_group_items, decisions):
            decision = None if isinstance(decision, Exception) else decision
            for item in group:
                item["llm_decision"] = decision

    # Orientation rebinding is also a per-location LLM fallback.  Keep it in
    # the same bounded async wave as the initial candidate decisions.  Calling
    # it from the commit loop made every directional road/water/facility
    # mention wait for the previous one, which recreated the old tail latency
    # even though the first candidate wave was concurrent.
    orientation_groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for item in prepared:
        fact = item["fact"]
        hints = item["hints"]
        trace = item["trace"]
        candidate = item.get("candidate")
        if item.get("scope"):
            continue
        if item.get("llm_kind") == "candidate":
            candidate = item.get("llm_decision")
            if candidate is not None:
                trace.append({
                    "step": "llm_candidate_selection",
                    "picked": getattr(candidate, "canonical_name", ""),
                    "selection": "typed_closed_set",
                })
        elif item.get("llm_kind") == "fallback":
            candidate = item.get("llm_decision")
            trace.append({"step": "fallback", "best_effort": True})

        if candidate is None:
            if item.get("llm_kind") == "fallback" and item["role"] == "village":
                item["village_fallback_pending"] = True
            continue
        topology_evidence: List[str] = []
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
        base_anchor = _anchor_from_candidate(
            fact,
            candidate,
            best_effort=(
                False
                if item.get("llm_kind") == "candidate"
                and _candidate_has_authoritative_geometry(candidate)
                else bool(item.get("best_effort"))
            ),
            topology_evidence=topology_evidence,
            query_trace=trace,
        )
        item["base_anchor"] = base_anchor
        orientation_candidates = _orientation_candidates(context, fact, base_anchor)
        if llm is None or not orientation_candidates:
            item["orientation_anchor"] = base_anchor
            continue
        orientation_key = (
            _grounding_work_key(item, "orientation", [candidate]),
            _candidate_fingerprint(orientation_candidates),
        )
        item["orientation_candidates"] = orientation_candidates
        orientation_groups.setdefault(orientation_key, []).append(item)

    orientation_tasks = []
    orientation_group_items = []
    for group in orientation_groups.values():
        representative = group[0]
        orientation_tasks.append(_llm_orientation_pick(
            context,
            representative["fact"],
            representative["base_anchor"],
            llm,
            budget=ground_llm_budget,
        ))
        orientation_group_items.append(group)
    if orientation_tasks:
        logger.info(
            "[ground_anchors] concurrent orientation fallback groups=%d facts=%d max_concurrent=%d",
            len(orientation_tasks),
            sum(len(group) for group in orientation_group_items),
            int(ground_llm_budget.get("max_concurrent", 1) or 1),
        )
        orientation_results = await asyncio.gather(
            *orientation_tasks,
            return_exceptions=True,
        )
        for group, result in zip(orientation_group_items, orientation_results):
            if isinstance(result, Exception) or result is None:
                for item in group:
                    item["orientation_anchor"] = item["base_anchor"]
                continue
            for item in group:
                item["orientation_anchor"] = _orientation_rebound_anchor(
                    item["fact"], item["base_anchor"], result
                )

    # Village cluster fallback has ordered ownership state.  Prepare every
    # candidate list from a read-only occupancy snapshot, run only the LLM
    # decisions in a bounded/grouped wave, then commit picks in fact order.
    village_groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for item in prepared:
        if item.get("scope"):
            continue
        anchor = item.get("orientation_anchor") or item.get("base_anchor")
        pending = item.get("village_fallback_pending")
        needs_fallback = (
            pending
            or (
                anchor is not None
                and anchor.role == "village"
                and not _has_spatial_evidence(anchor)
            )
        )
        if not needs_fallback:
            continue
        plan = _village_spatial_fallback_plan(
            context,
            item["fact"],
            anchor,
            item["trace"],
        )
        item["village_fallback_plan"] = plan
        candidates = plan.get("candidates", [])
        if llm is not None and candidates:
            key = _grounding_work_key(item, "village_fallback", candidates)
            village_groups.setdefault(key, []).append(item)

    village_tasks = []
    village_group_items = []
    for group in village_groups.values():
        representative = group[0]
        plan = representative["village_fallback_plan"]
        village_tasks.append(_llm_reason_candidate(
            llm,
            representative["mention"],
            "village",
            plan["hints"],
            plan["candidates"],
            budget=ground_llm_budget,
        ))
        village_group_items.append(group)
    if village_tasks:
        logger.info(
            "[ground_anchors] concurrent village fallback groups=%d facts=%d max_concurrent=%d",
            len(village_tasks),
            sum(len(group) for group in village_group_items),
            int(ground_llm_budget.get("max_concurrent", 1) or 1),
        )
        village_results = await asyncio.gather(
            *village_tasks,
            return_exceptions=True,
        )
        for group, result in zip(village_group_items, village_results):
            picked = None if isinstance(result, Exception) else result
            for item in group:
                item["village_fallback_pick"] = picked

    anchors: List[GroundedAnchor] = []
    unresolved_items: List[dict] = []
    for item in prepared:
        fact = item["fact"]
        trace = item["trace"]
        if item.get("scope"):
            if item.get("candidate") is not None:
                anchors.append(item["candidate"])
            continue
        anchor = item.get("orientation_anchor") or item.get("base_anchor")
        plan = item.get("village_fallback_plan")
        if plan is not None:
            anchor = _commit_village_spatial_fallback(
                context,
                plan,
                item.get("village_fallback_pick"),
            )
        if anchor is None:
            unresolved_items.append({
                "code": "grounding_unresolved",
                "mention": item["mention"],
                "role": item["role"],
                "reason": "typed_candidate_selection_or_spatial_evidence_missing",
                "trace": list(trace),
            })
            if item["role"] in ("village", "water", "road"):
                trace.append({
                    "step": "skip_no_spatial_evidence",
                    "role": item["role"],
                })
                item["skip_trace"] = list(trace)
                logger.info(
                    "[ground_anchors] skipped anchor without spatial evidence mention=%s role=%s trace=%s",
                    item["mention"],
                    item["role"],
                    item["skip_trace"],
                )
            continue
        if anchor.role == "facility":
            anchor = _topology_refine_facility(context, fact, anchor)
        elif anchor.role in ("water", "road") and not _has_spatial_evidence(anchor):
            trace.append({
                "step": "linear_fallback_disabled",
                "role": anchor.role,
                "reason": "requires_bundle_source_feature_geometry",
            })
        if anchor.role != "village" and not _has_spatial_evidence(anchor):
            unresolved_items.append({
                "code": "grounding_spatial_evidence_missing",
                "mention": item["mention"],
                "role": anchor.role,
                "reason": "resolved_entity_has_no_bundle_geometry_or_bsm",
                "trace": list(trace),
            })
            trace.append({
                "step": "skip_no_spatial_evidence",
                "role": anchor.role,
            })
            item["skip_trace"] = list(trace)
            logger.info(
                "[ground_anchors] skipped anchor without spatial evidence mention=%s role=%s trace=%s",
                item["mention"],
                anchor.role,
                item["skip_trace"],
            )
            continue
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
    # Keep the typed evidence on the live context for callers that continue
    # directly into GROUND/SELECT.  Workflow stages also persist the same
    # value as the grounded_anchors artifact, so this is an in-memory bridge,
    # not a second source of truth.
    context.grounded_anchors = list(anchors)
    context.grounding_unresolved = list(unresolved_items)
    return anchors


def _scope_candidate(fact: Any, poi_bsms: List[str], village_bsms: List[str], trace: List[dict]) -> Any:
    """构造仅用于村域筛选的 parcel scope，不伪造 feature geometry。"""
    from types import SimpleNamespace

    bsms = list(dict.fromkeys([*poi_bsms, *village_bsms]))
    trace.append({"step": "scope_candidate", "count": len(bsms)})
    return SimpleNamespace(
        entity_ref=f"scope:village:{getattr(fact, 'normalized_name', '')}",
        entity_type=str(getattr(fact, "role", "unknown") or "unknown"),
        canonical_name=str(getattr(fact, "normalized_name", "") or ""),
        source_bsms=bsms,
        geometry_ref=None,
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
    budget: Optional[Dict[str, Any]] = None,
    candidates: Optional[List[Any]] = None,
) -> Optional[Any]:
    """索引无候选时：用 hint token 在 gazetteer 召回候选，LLM 判别（仍无几何则 0 分）。"""
    candidates = list(candidates) if candidates is not None else _llm_anchor_candidates(
        context, hints
    )
    picked = await _llm_reason_candidate(
        llm, mention, role, hints, candidates, budget=budget
    )
    if picked is not None:
        trace.append({"step": "gazetteer_llm_fallback", "picked": picked.canonical_name})
    return picked


def _llm_anchor_candidates(context: Any, hints: str) -> List[Any]:
    """Build the deterministic gazetteer candidate list for fallback work."""
    candidates: List[Any] = []
    if getattr(context, "gazetteer", None) is None or not hints:
        return candidates
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
    return candidates


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
    from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor

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

    observation_refs: dict[str, dict] = {}
    try:
        from app.evidence.identity.observation_store import ObservationStore

        observations = ObservationStore.from_location_facts(
            list(getattr(context, "location_facts", []) or [])
        )
        if observations:
            observation_state = dict(state)
            observation_state["artifact_refs"] = dict(state.get("artifact_refs") or {})
            observation_ref = ObservationStore(base_dir=base_dir).put_snapshot(
                observation_state,
                observations,
                parent_digest=str(getattr(snapshot, "artifact_id", "") or ""),
            )
            observation_refs["l1_observations"] = observation_ref.model_dump(mode="json")
            logger.info(
                "[ground_anchors] persisted l1 observations %s (%d observations)",
                observation_ref.digest,
                len(observations),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ground_anchors] l1 observation snapshot failed: %s", exc)

    from app.infrastructure.llm.factory import create_flash_llm

    llm = None
    try:
        llm = create_flash_llm(max_tokens=800, temperature=0.1)
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
    try:
        from app.evidence.identity.binding_store import BindingStore

        bindings = BindingStore.from_context(context, anchors)
        context.grounded_bindings = bindings
        binding_state = dict(state)
        binding_state["artifact_refs"] = {
            **dict(state.get("artifact_refs") or {}),
            **observation_refs,
        }
        binding_ref = BindingStore(base_dir=base_dir).put_snapshot(
            binding_state,
            bindings,
            observation_snapshot_ref=str(
                (observation_refs.get("l1_observations") or {}).get("digest", "")
            ),
            parent_digest=str(
                (observation_refs.get("l1_observations") or {}).get("digest", "")
            ),
        )
        observation_refs["l1_bindings"] = binding_ref.model_dump(mode="json")
        logger.info(
            "[ground_anchors] persisted l1 bindings %s (%d bindings)",
            binding_ref.digest,
            len(bindings),
        )
    except Exception as exc:  # noqa: BLE001 - binding persistence must not block grounding
        logger.warning("[ground_anchors] l1 binding snapshot failed: %s", exc)
    if not anchors:
        return {
            "artifact_refs": observation_refs,
            "grounded_anchor_count": 0,
        }

    run_id = str(state.get("run_id", "") or session_id)
    anchor_state = dict(state)
    anchor_state["artifact_refs"] = {
        **dict(state.get("artifact_refs") or {}),
        **observation_refs,
    }
    artifact = store_artifact(
        anchor_state,
        "grounded_anchors",
        "ground",
        "GroundedAnchorList",
        [a.model_dump(mode="json") for a in anchors],
        base_dir=base_dir,
    )
    ref = ArtifactDescriptor.model_validate(artifact)
    logger.info("[ground_anchors] persisted artifact %s (%d anchors)", ref.digest, len(anchors))
    return {
        "artifact_refs": {
            **observation_refs,
            "grounded_anchors": ref.model_dump(mode="json"),
        },
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
