"""Natural-village -> residential-cluster(s) mapping for L1/GROUND resolution.

A natural village is a first-class spatial anchor: it is NOT one-to-one with a
residential cluster.  One village may span several 宅基地 clusters.  This module
derives *real* residential clusters from the bundle's 宅基地 (DLBM 1340) parcels
and lets the flash LLM decide which cluster(s) belong to each report-named
natural village (many-to-one), using only report evidence + cluster geometry.

Evidence-first / fail-closed:
- Geometry and BSMs always come from the bundle clusters, never from the LLM.
- A village is assigned only when the report provides a verifiable evidence
  snippet (verbatim substring); villages without evidence stay unresolved.
- The LLM only produces name -> cluster-index assignment text; no coordinates.

Determinism & resume:
- The cluster derivation is fully deterministic.
- The mapping is cached by sha256(report excerpt + village order) and can be
  replayed on resume; llm=None or no report evidence yields an empty mapping.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_RESIDENTIAL_DLMC = ("1340", "0702")
_CLUSTER_DISTANCE_DEG = 0.008  # ~800m at 24N


@dataclass
class VillageCluster:
    index: int
    centroid: tuple
    bsms: List[str] = field(default_factory=list)
    parcel_count: int = 0
    area_ha: float = 0.0
    features: Dict[str, Any] = field(default_factory=dict)


def build_landuse_bodies(
    parcels: List[Any],
    markers: tuple,
    distance_deg: float = _CLUSTER_DISTANCE_DEG,
) -> List[VillageCluster]:
    """Cluster landuse parcels whose DLBM/DLMC/name carries any marker into
    deterministic spatial bodies (e.g. 宅基地 -> residential settlements,
    水域/河流 -> water bodies).  Geometry always comes from the parcels.
    """
    from app.spatial.grounding.grounding import build_parcel_centroid_cache

    cache = build_parcel_centroid_cache(parcels)
    selected = []
    for parcel in parcels:
        code = str(getattr(parcel, "dlbm", "") or "") or str(getattr(parcel, "dlmc", "") or "")
        name = str(getattr(parcel, "name", "") or "")
        text = f"{code} {name}"
        if not any(marker in text for marker in markers):
            continue
        bsm = str(getattr(parcel, "bsm", "") or "")
        centroid = cache.get(bsm) or cache.get(str(getattr(parcel, "bsm", None)))
        if centroid is None:
            continue
        area = float(getattr(parcel, "area_sqm", 0) or 0) / 10000.0
        selected.append((bsm, centroid, area))
    if not selected:
        return []

    clusters: List[VillageCluster] = []
    member_pts: List[List[tuple]] = []
    for bsm, centroid, area in selected:
        placed = False
        for cluster in clusters:
            if math.hypot(centroid[0] - cluster.centroid[0], centroid[1] - cluster.centroid[1]) < distance_deg:
                cluster.bsms.append(bsm)
                cluster.parcel_count += 1
                cluster.area_ha += area
                n = cluster.parcel_count
                cluster.centroid = (
                    (cluster.centroid[0] * (n - 1) + centroid[0]) / n,
                    (cluster.centroid[1] * (n - 1) + centroid[1]) / n,
                )
                member_pts[clusters.index(cluster)].append(centroid)
                placed = True
                break
        if not placed:
            clusters.append(VillageCluster(
                index=len(clusters),
                centroid=centroid,
                bsms=[bsm],
                parcel_count=1,
                area_ha=area,
            ))
            member_pts.append([centroid])
    # Stable ordering: largest settlement first, then west->east, south->north
    # and finally the sorted BSM set.  The final tie-breaker prevents source
    # feature arrival order from changing LLM candidate indexes on resume.
    ordered = sorted(
        zip(clusters, member_pts),
        key=lambda pair: (
            -pair[0].parcel_count,
            round(pair[0].centroid[0], 12),
            round(pair[0].centroid[1], 12),
            tuple(sorted(str(bsm) for bsm in pair[0].bsms)),
        ),
    )
    clusters = [pair[0] for pair in ordered]
    member_pts = [pair[1] for pair in ordered]
    for i, cluster in enumerate(clusters):
        cluster.index = i
    _attach_body_features(clusters, member_pts)
    return clusters


def _relative_position(dx: float, dy: float) -> str:
    """Map a vector from the village centre to a compass-ish label."""
    ns = "北" if dy > 0 else ("南" if dy < 0 else "")
    ew = "东" if dx > 0 else ("西" if dx < 0 else "")
    if ns and ew:
        # dominant axis decides 东北/东南/西北/西南 vs plain 北/东
        return f"{ew}{ns}" if abs(dx) > abs(dy) else f"{ns}{ew}"
    return f"{ns}{ew}" or "中部"


def _attach_body_features(
    clusters: List[VillageCluster],
    member_pts: List[List[tuple]],
) -> None:
    """Give every body candidate semantic features the LLM can match report
    clues to (GER-LLM featurizer): position relative to the village centre,
    span (km) and shape (elongated vs compact)."""
    pts = [p for group in member_pts for p in group]
    if not pts:
        return
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    for cluster, group in zip(clusters, member_pts):
        if not group:
            continue
        rel = _relative_position(cluster.centroid[0] - cx, cluster.centroid[1] - cy)
        xs = [p[0] for p in group]
        ys = [p[1] for p in group]
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        span_km = max(math.hypot(dx * 102.0, dy * 111.0), 0.05)
        shape = "长条" if (max(dx, dy) > 0 and max(dx, dy) > 3 * min(dx, dy) + 0.0005) else "面状"
        cluster.features["方位"] = rel
        cluster.features["跨度km"] = round(span_km, 2)
        cluster.features["形态"] = shape


def build_village_clusters(parcels: List[Any]) -> List[VillageCluster]:
    """Cluster 宅基地 parcels into residential settlements (deterministic)."""
    return build_landuse_bodies(
        parcels,
        (*_RESIDENTIAL_DLMC, "宅基地", "村庄建设用地", "农村居民点"),
    )


_PROMPT_TEMPLATE = """你是村庄规划 GIS 证据编译器。待核对的聚落名称：{villages}。
该村有 {m} 个宅基地聚落（编号 0..{max_index}），每个聚落有质心坐标与规模：
{clusters}

任务：把聚落分配到自然村；一个自然村可能由多个聚落组成（多对一），同一个聚落只能属于一个自然村。
只允许根据报告摘录中明确出现的名称、方位、坐标或可核对空间关系建立映射。
禁止按名称顺序、聚落规模顺序、常识或猜测分配。证据不足的名称必须省略。

只输出符合结构化合同的 JSON：
{{"entries": [{{"name": "自然村名称", "candidate_indexes": [编号, ...], "evidence": "报告原文短句"}}]}}。
每个待核对名称最多一个 entry；evidence 必须是报告摘录中可以逐字找到的短句；不要输出其它文字。"""


_WATER_PROMPT_TEMPLATE = """你是村庄规划 GIS 证据编译器。待核对的水体名称：{villages}。
该村有 {m} 个由水域/河流地块聚合而成的水体（编号 0..{max_index}），每个水体有质心坐标与规模：
{clusters}

一个水体可能由多个地块组成（多对一），同一组地块只能属于一个水体。
只允许根据报告摘录中明确出现的名称、方位、流向或可核对空间关系建立映射。
禁止按名称顺序、规模顺序、常识或猜测分配。证据不足的名称必须省略。

只输出符合结构化合同的 JSON：
{{"entries": [{{"name": "水体名称", "candidate_indexes": [编号, ...], "evidence": "报告原文短句"}}]}}。
每个待核对名称最多一个 entry；evidence 必须是报告摘录中可以逐字找到的短句；不要输出其它文字。"""


def _cache_path(run_root: Optional[Path]) -> Optional[Path]:
    if run_root is None:
        return None
    return (run_root / "village-cluster-map.json").resolve()


async def _map_bodies(
    bodies: List[VillageCluster],
    names: List[str],
    *,
    prompt_template: str,
    cache_key_prefix: str,
    prompt_kwargs: Optional[Dict[str, Any]] = None,
    require_evidence: bool = True,
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Core flash-LLM name -> body assignment (evidence-constrained, cached)."""
    if not bodies or not names:
        return {}
    cache_key = hashlib.sha256(
        (
            f"{cache_key_prefix}|{report_text[:4000]}|{','.join(names)}|"
            f"{source_artifact_ref}|{source_artifact_digest}"
        ).encode("utf-8")
    ).hexdigest()
    if cache is not None and cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if raw.get("key") == cache_key and isinstance(raw.get("map"), dict):
                return {str(k): v for k, v in raw["map"].items()}
        except Exception:
            pass

    mapping: Dict[str, Dict[str, Any]] = {}
    if llm is not None and report_text.strip():
        try:
            from app.spatial.grounding.call_budget import (
                reserve_ground_llm_call,
                run_ground_llm_call,
            )
            cluster_lines = "\n".join(
                f"{c.index}: 质心({c.centroid[0]:.5f},{c.centroid[1]:.5f}) 地块数{c.parcel_count} 面积{c.area_ha:.2f}ha"
                for c in bodies
            )
            prompt = prompt_template.format(
                villages="、".join(names),
                m=len(bodies),
                max_index=len(bodies) - 1,
                clusters=cluster_lines,
                **(prompt_kwargs or {}),
            )
            if report_text:
                prompt += (
                    f"\n\n报告摘录（用于方位判断，只含与待分配名称相关的段落）:\n"
                    f"{_evidence_excerpt(report_text, names)}\n"
                )
            anchor_lines, allowed_anchor_indexes = _spatial_anchor_prompt(
                names,
                bodies,
                spatial_evidence,
            )
            if spatial_evidence is None:
                allowed_anchor_indexes = None
            if anchor_lines:
                prompt += f"\n\n跨源空间锚点证据（优先于村名清单）:\n{anchor_lines}\n"
            # Only the typed mapping contract may cross this boundary.  A
            # provider failure yields an empty mapping with a warning; raw
            # model text is never parsed as spatial identity.
            structured_timeout = reserve_ground_llm_call(budget)
            payload = None
            if structured_timeout is not None:
                async def _invoke_structured():
                    return await _structured_mapping(
                        llm,
                        prompt,
                        report_text,
                        require_evidence=require_evidence,
                        timeout=structured_timeout,
                        allowed_candidate_indexes=allowed_anchor_indexes,
                    )

                payload = await run_ground_llm_call(
                    budget, structured_timeout, _invoke_structured
                )
            if payload:
                mapping = _resolve_cluster_conflicts(payload, bodies)
        except Exception as exc:  # noqa: BLE001 - typed failure is surfaced by the empty mapping
            logger.warning("[landuse-bodies] flash mapping failed or timed out: %s", exc)

    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"key": cache_key, "map": mapping}, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(cache)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[landuse-bodies] cache flush failed: %s", exc)
    return mapping


async def assign_names(
    candidates: List[VillageCluster],
    names: List[str],
    *,
    prompt_template: str,
    cache_key_prefix: str,
    prompt_kwargs: Optional[Dict[str, Any]] = None,
    require_evidence: bool = True,
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Public generic entry: flash-LLM name -> candidate assignment for any
    role (villages / water bodies / roads / facilities / landmarks).  The LLM
    only decides with verbatim report evidence; geometry stays in the
    candidates.  ``prompt_template`` must format {villages}/{m}/{max_index}/
    {clusters}."""
    return await _map_bodies(
        candidates,
        names,
        prompt_template=prompt_template,
        cache_key_prefix=cache_key_prefix,
        prompt_kwargs=prompt_kwargs,
        require_evidence=require_evidence,
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
        spatial_evidence=spatial_evidence,
    )


async def map_villages(
    clusters: List[VillageCluster],
    village_names: List[str],
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Map village names to clusters through the typed Flash contract."""
    return await _map_bodies(
        clusters,
        village_names,
        prompt_template=_PROMPT_TEMPLATE,
        cache_key_prefix="v3",
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
        spatial_evidence=spatial_evidence,
    )


async def map_water_bodies(
    bodies: List[VillageCluster],
    water_names: List[str],
    report_text: str = "",
    cache: Optional[Path] = None,
    llm: Any = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
    spatial_evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Map report water-body names to landuse-derived water bodies."""
    return await _map_bodies(
        bodies,
        water_names,
        prompt_template=_WATER_PROMPT_TEMPLATE,
        cache_key_prefix="water-v1",
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
        spatial_evidence=spatial_evidence,
    )


from pydantic import BaseModel as _BaseModel, Field as _Field


class _GMappingEntry(_BaseModel):
    name: str = ""
    candidate_indexes: list = _Field(default_factory=list)
    evidence: str = ""


class _GMappingSet(_BaseModel):
    entries: list[_GMappingEntry] = _Field(default_factory=list)


async def _structured_mapping(
    model: Any,
    prompt: str,
    report_text: str,
    *,
    require_evidence: bool = True,
    timeout: Optional[float] = None,
    allowed_candidate_indexes: Optional[Mapping[str, set[int]]] = None,
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Structured-output mapping {name -> {candidate_indexes, evidence}}.

    Returns None when the provider cannot do structured output or produces no
    usable entries; the caller records an unresolved mapping.
    """
    try:
        from app.infrastructure.llm.structured import run_structured_output
        structured_llm = model
        allow_provider_content_json = False
        # MiniMax's LangChain adapter can complete a thinking response without
        # producing the tool-call object expected by ``with_structured_output``
        # (the observed result is ``None``).  The application already has an
        # Instructor/TOOLS client for the same provider contract.  Use it only
        # for the real provider adapter; deterministic injected test doubles
        # continue through their supplied ``llm`` seam.
        from app.infrastructure.llm.factory import LLMProvider, get_provider

        provider = get_provider()
        model_module = str(type(model).__module__ or "")
        model_name = str(type(model).__name__ or "")
        is_minimax_adapter = (
            provider is LLMProvider.MINIMAX
            and (
                model_module.startswith("langchain_openai")
                or model_name in {"ChatOpenAI", "AzureChatOpenAI"}
            )
        )
        if is_minimax_adapter:
            structured_llm = None
            # MiniMax-M2 high-speed currently returns thinking text plus
            # a JSON object, but no tool call.  This remains a typed
            # provider channel: the shared strict JSON decoder and
            # Pydantic response model must both accept it.  It never
            # parses a name into a BSM or geometry.
            allow_provider_content_json = True
        response = await run_structured_output(
            _GMappingSet,
            [{"role": "user", "content": prompt}],
            max_retries=0,
            timeout=timeout,
            temperature=0.1,
            max_tokens=1200,
            llm=structured_llm,
            allow_content_json_fallback=allow_provider_content_json,
        )
        if response is None:
            raise ValueError("structured_mapping_empty_response")
    except Exception as exc:
        logger.warning(
            "[village-cluster] structured mapping rejected: %s: %s",
            type(exc).__name__,
            str(exc)[:500],
        )
        return None
    entries = getattr(response, "entries", None)
    if entries is None and isinstance(response, dict):
        entries = response.get("entries")
    if not entries:
        return None
    result: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        name = str(getattr(e, "name", "") or "").strip()
        evidence = str(getattr(e, "evidence", "") or "").strip()
        if not name:
            continue
        if require_evidence and not _evidence_in_report(evidence, report_text):
            continue
        try:
            idx = [int(i) for i in (getattr(e, "candidate_indexes", None) or [])]
        except (TypeError, ValueError):
            idx = []
        if not idx:
            continue
        if allowed_candidate_indexes is not None:
            allowed = allowed_candidate_indexes.get(name)
            if allowed is None:
                base_name = name.removesuffix("自然村").removesuffix("村")
                allowed = allowed_candidate_indexes.get(base_name)
            if allowed is None:
                logger.warning(
                    "[village-cluster] %s has no cross-source spatial anchor; mapping rejected",
                    name,
                )
                continue
            if not set(idx).issubset(allowed):
                logger.warning(
                    "[village-cluster] %s selected clusters outside spatial evidence: selected=%s allowed=%s",
                    name,
                    sorted(set(idx)),
                    sorted(allowed),
                )
                continue
        # Canonical mapping key is ``cluster_indexes`` (the text parser and the
        # conflict resolver/aggregator both read it).
        result[name] = {"cluster_indexes": idx, "evidence": evidence}
    return result or None


def _aggregate_clusters(member_clusters: List[VillageCluster]) -> Dict[str, Any]:
    """Aggregate member clusters into a village-level extent (many-to-one).

    BSMs are the deduplicated union; centroid is parcel-count-weighted.
    Returns keys ``cluster_indexes`` / ``bsms`` / ``centroid``.
    """
    member_clusters = sorted(member_clusters, key=lambda c: c.index)
    indexes = [c.index for c in member_clusters]
    bsms = list(dict.fromkeys(b for c in member_clusters for b in c.bsms))
    weights = [max(int(c.parcel_count or 0), 1) for c in member_clusters]
    total = sum(weights)
    centroid = (
        sum(c.centroid[0] * w for c, w in zip(member_clusters, weights)) / total,
        sum(c.centroid[1] * w for c, w in zip(member_clusters, weights)) / total,
    )
    return {
        "cluster_indexes": indexes,
        "bsms": bsms,
        "centroid": [round(x, 6) for x in centroid],
    }


_EVIDENCE_STRIP = " \t\n\r，。、；：""（）()《》【】「」『』"


def _evidence_excerpt(report_text: str, names: List[str], max_chars: int = 3000) -> str:
    """Targeted report excerpt: keep only the segments that mention any of the
    names being assigned.  A short focused excerpt lets the real model map
    names to candidates instead of drowning in a 12k-char dump."""
    wanted = [str(n) for n in (names or []) if n]
    if not wanted:
        return (report_text or "")[:max_chars]
    parts: List[str] = []
    segments: list[str] = []
    current: list[str] = []
    for char in report_text or "":
        current.append(char)
        if char in "。；\n":
            segments.append("".join(current))
            current.clear()
    if current:
        segments.append("".join(current))
    for seg in segments:
        if any(w in seg for w in wanted):
            parts.append(seg)
    out = "".join(parts).strip()
    return (out or report_text or "")[:max_chars]


def _evidence_in_report(evidence: str, report_text: str) -> bool:
    """Evidence must literally appear in the report.  The real flash LLM often
    re-quotes a span with surrounding punctuation/whitespace, so compare on a
    normalized form (whitespace + common punctuation stripped) instead of a
    brittle verbatim substring - fabrication is still impossible because the
    normalized evidence must be a substring of the normalized report."""
    ev = (evidence or "").strip()
    if not ev:
        return False
    if ev in (report_text or ""):
        return True
    trans = str.maketrans("", "", _EVIDENCE_STRIP)
    ev_norm = ev.translate(trans)
    rep_norm = (report_text or "").translate(trans)
    return bool(ev_norm) and ev_norm in rep_norm


def _spatial_anchor_prompt(
    names: List[str],
    bodies: List[VillageCluster],
    spatial_evidence: Optional[Mapping[str, Any]],
) -> tuple[str, Dict[str, set[int]]]:
    """Describe source-backed spatial anchors and derive a hard candidate set.

    ``spatial_evidence`` contains only identity/provenance and related Bundle
    parcel BSMs supplied by EvidenceGraph.  The mapper joins those BSMs to
    deterministic residential bodies; it never receives or parses geometry
    from the model.  An anchor can therefore narrow the LLM's decision, but
    cannot manufacture a new parcel or coordinate.
    """
    if not spatial_evidence:
        return "", {}
    body_bsms = {int(body.index): {str(bsm) for bsm in body.bsms} for body in bodies}
    lines: List[str] = []
    allowed: Dict[str, set[int]] = {}
    for requested_name in names:
        raw_anchors = spatial_evidence.get(requested_name)
        if raw_anchors is None:
            raw_anchors = spatial_evidence.get(
                requested_name.removesuffix("自然村").removesuffix("村")
            )
        if not isinstance(raw_anchors, (list, tuple)):
            continue
        hits: Dict[int, int] = {}
        anchor_labels: List[str] = []
        anchor_related_bsms: set[str] = set()
        for raw_anchor in raw_anchors:
            if not isinstance(raw_anchor, Mapping):
                continue
            label = str(raw_anchor.get("canonical_name") or "").strip()
            feature_bsm = str(raw_anchor.get("feature_bsm") or "").strip()
            related_bsms = {
                str(value).strip()
                for value in (raw_anchor.get("related_parcel_bsms") or [])
                if str(value).strip()
            }
            if label:
                anchor_labels.append(label)
            anchor_related_bsms.update(related_bsms)
            for index, bsms in body_bsms.items():
                overlap = len(related_bsms.intersection(bsms))
                if overlap:
                    hits[index] = hits.get(index, 0) + overlap
        if not hits:
            continue
        ordered_hits = sorted(hits.items(), key=lambda item: (-item[1], item[0]))
        allowed[requested_name] = {index for index, _count in ordered_hits}
        labels = "、".join(list(dict.fromkeys(anchor_labels))[:6])
        candidates = "；".join(
            f"{index}(关联地块交集{count})" for index, count in ordered_hits
        )
        lines.append(
            f"- {requested_name}: Bundle锚点={labels or '未命名空间特征'}，"
            f"锚点关联地块数={len(anchor_related_bsms)}，支持的聚落候选={candidates}。"
            "只能从这些候选中选择；村名列表本身不能证明聚落归属。"
        )
    return "\n".join(lines), allowed


def collect_spatial_anchor_evidence(
    context: Any,
    names: List[str],
    *,
    max_candidates: int = 16,
) -> Dict[str, List[Dict[str, Any]]]:
    """Collect source-backed cross-layer anchors for village mapping.

    This is intentionally a retrieval adapter, not a second index.  It asks
    EvidenceGraph for all bounded candidates matching each name without a
    caller-provided layer.  The returned payload contains Bundle identities,
    related parcel BSMs, KG relation refs and L1 fact refs; authoritative
    geometry remains behind ``bundle://feature/...`` and is never copied into
    the prompt or into the mapper result.
    """
    graph = getattr(context, "evidence_graph", None)
    if graph is None:
        from app.evidence.retrieval.evidence_graph import EvidenceGraph

        graph = EvidenceGraph.build(context)
    result: Dict[str, List[Dict[str, Any]]] = {}
    for name in names:
        normalized = str(name or "").strip()
        if not normalized:
            continue
        candidates = graph.query_scope_candidates(
            normalized,
            entity_scope=[],
            max_candidates=max(1, int(max_candidates or 1)),
        )
        anchors = []
        for candidate in candidates:
            related = [
                str(value).strip()
                for value in (getattr(candidate, "related_parcel_bsms", None) or [])
                if str(value).strip()
            ]
            feature_bsm = str(getattr(candidate, "feature_bsm", "") or "").strip()
            if not related or not feature_bsm:
                continue
            anchors.append({
                "canonical_name": str(getattr(candidate, "canonical_name", "") or ""),
                "role": str(getattr(candidate, "role", "") or ""),
                "feature_bsm": feature_bsm,
                "related_parcel_bsms": list(dict.fromkeys(related)),
                "relation_refs": list(getattr(candidate, "relation_refs", None) or []),
                "l1_fact_refs": list(getattr(candidate, "l1_fact_refs", None) or []),
                "evidence_refs": list(getattr(candidate, "evidence_refs", None) or []),
            })
        if anchors:
            result[normalized] = anchors
    return result


def _resolve_cluster_conflicts(
    mapping: Dict[str, Dict[str, Any]],
    clusters: List[VillageCluster],
) -> Dict[str, Dict[str, Any]]:
    """GER-LLM-style global consistency: one cluster belongs to at most one
    village.  When the LLM assigns the same cluster to several villages, keep
    the village with the longest evidence snippet (then earliest in input
    order); the losing village keeps only its non-conflicting clusters, and is
    dropped when it has none left.  Deterministic; never fabricates geometry.
    """
    if not mapping or not clusters:
        return mapping
    order = sorted(
        mapping,
        key=lambda n: -len(str(mapping[n].get("evidence") or "") or ""),
    )
    cluster_owner: Dict[int, str] = {}
    for name in order:
        for idx in mapping[name].get("cluster_indexes", []) or []:
            cluster_owner.setdefault(int(idx), name)
    out: Dict[str, Dict[str, Any]] = {}
    for name, item in mapping.items():
        kept = [
            int(idx)
            for idx in (item.get("cluster_indexes", []) or [])
            if cluster_owner.get(int(idx)) == name
        ]
        if not kept:
            logger.info(
                "[village-cluster] %s lost all clusters to conflict; dropped",
                name,
            )
            continue
        member_clusters = [c for c in clusters if c.index in kept]
        if not member_clusters:
            continue
        aggregate = _aggregate_clusters(member_clusters)
        new_item = dict(item)
        new_item.update(aggregate)
        new_item["source_feature_id"] = ",".join(
            f"residential-cluster:{i}" for i in aggregate["cluster_indexes"]
        )
        if len(aggregate["cluster_indexes"]) == 1:
            new_item["cluster_index"] = aggregate["cluster_indexes"][0]
        else:
            new_item.pop("cluster_index", None)
        out[name] = new_item
    return out


def village_gazetteer_entries(
    mapping: Dict[str, Dict[str, Any]],
    clusters: List[VillageCluster],
    *,
    canonical_suffix: str = "村",
    uri_prefix: str = "pln:natural_village:",
    source: str = "village_cluster_map",
    kind_label: str = "自然村",
    member_label: str = "宅基地聚落",
) -> List["GazetteerEntry"]:
    """Turn a many-to-one name->bodies mapping into aggregated gazetteer
    entries (natural villages, water bodies, ...).

    Each named body owns the union of its member clusters' BSMs and a
    parcel-count-weighted centroid.  Geometry always comes from the bundle
    clusters; the LLM only decided the assignment.  ``entity_uri`` is a
    synthetic anchor because one named place spans several clusters.
    """
    from app.infrastructure.kg.gazetteer import GazetteerEntry

    entries: List[GazetteerEntry] = []
    for name in sorted(mapping):
        item = mapping[name]
        bsms = list(dict.fromkeys(item.get("bsms") or []))
        if not bsms:
            continue
        centroid = list(item.get("centroid") or [])
        indexes = list(item.get("cluster_indexes") or [])
        raw = str(name).strip()
        canonical = f"{raw}{canonical_suffix}" if canonical_suffix and not raw.endswith(canonical_suffix) else raw
        aliases = [raw]
        if raw.endswith(canonical_suffix) and len(raw) > len(canonical_suffix):
            aliases.append(raw[: -len(canonical_suffix)])
        entries.append(GazetteerEntry(
            name=canonical,
            aliases=aliases,
            entity_uri=f"{uri_prefix}{raw}",
            bsms=bsms,
            centroid=centroid or None,
            source=source,
            confidence=float(item.get("confidence", 0.6) or 0.6),
            description=(
                f"{kind_label}「{raw}」：依据报告证据「{item.get('evidence', '')}」"
                f"映射 {len(indexes)} 个{member_label}（{indexes}），BSM 并集 {len(bsms)} 个"
            ),
        ))
    return entries


def water_gazetteer_entries(
    mapping: Dict[str, Dict[str, Any]],
    bodies: List[VillageCluster],
) -> List["GazetteerEntry"]:
    """Aggregated gazetteer entries for LLM-named water bodies."""
    return village_gazetteer_entries(
        mapping,
        bodies,
        canonical_suffix="",
        uri_prefix="pln:water_body:",
        source="water_cluster_map",
        kind_label="水体",
        member_label="水域地块",
    )


async def assign_villages_to_clusters(
    gazetteer: Any,
    parcels: List[Any],
    village_names: List[str],
    report_text: str,
    *,
    context: Any = None,
    llm: Any = None,
    cache: Optional[Path] = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
) -> List["GazetteerEntry"]:
    """LLM-decided many-to-one village assignment -> aggregated gazetteer entries.

    Only villages that are still absent from ``gazetteer`` are considered.
    Clusters are derived deterministically from the 宅基地 parcels.  A village
    is assigned only when the report carries verifiable evidence; the rest stay
    unresolved (fail-closed).  Callers upsert the returned entries.
    """
    clusters = build_village_clusters(parcels)
    if not clusters or not village_names:
        return []
    names: List[str] = []
    for v in village_names:
        base = str(v or "").strip()
        if base.endswith("自然村"):
            base = base[:-3]
        elif base.endswith("村"):
            base = base[:-1]
        base = base.strip()
        if not base:
            continue
        if gazetteer is not None:
            existing = gazetteer.resolve(f"{base}村", fuzzy=False)
            # A name-only entry is semantic evidence, not spatial grounding.
            # Keep it eligible for cluster mapping until it carries BSMs.
            if existing is not None and getattr(existing, "bsms", None):
                continue
        names.append(base)
    names = list(dict.fromkeys(names))
    if not names:
        return []
    mapping = await map_villages(
        clusters,
        names,
        report_text=report_text,
        spatial_evidence=(
            collect_spatial_anchor_evidence(context, names)
            if context is not None
            else None
        ),
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
    )
    return village_gazetteer_entries(mapping, clusters)


_WATER_MARKERS = ("水域", "河流", "水库", "坑塘", "沟渠", "水利设施")


async def assign_water_bodies(
    gazetteer: Any,
    parcels: List[Any],
    water_names: List[str],
    report_text: str,
    *,
    llm: Any = None,
    cache: Optional[Path] = None,
    source_artifact_ref: str = "",
    source_artifact_digest: str = "",
    budget: Optional[Dict[str, Any]] = None,
) -> List["GazetteerEntry"]:
    """LLM-decided many-to-one water-name -> landuse water-body assignment.

    Water bodies are derived deterministically from the landuse parcels whose
    DLBM/DLMC marks them as water (水域/河流/水库/坑塘/沟渠/水利设施).  The LLM
    only assigns names to bodies when the report carries verifiable evidence;
    geometry and BSMs always come from the parcels.
    """
    bodies = build_landuse_bodies(parcels, _WATER_MARKERS)
    if not bodies or not water_names:
        return []
    names: List[str] = []
    for n in water_names:
        base = str(n or "").strip()
        if not base:
            continue
        if gazetteer is not None and gazetteer.resolve(base, fuzzy=False) is not None:
            continue
        names.append(base)
    names = list(dict.fromkeys(names))
    if not names:
        return []
    mapping = await map_water_bodies(
        bodies,
        names,
        report_text=report_text,
        cache=cache,
        llm=llm,
        source_artifact_ref=source_artifact_ref,
        source_artifact_digest=source_artifact_digest,
        budget=budget,
    )
    return water_gazetteer_entries(mapping, bodies)


__all__ = [
    "VillageCluster",
    "build_landuse_bodies",
    "build_village_clusters",
    "collect_spatial_anchor_evidence",
    "map_villages",
    "map_water_bodies",
    "village_gazetteer_entries",
    "water_gazetteer_entries",
    "assign_villages_to_clusters",
    "assign_water_bodies",
    "assign_names",
]
