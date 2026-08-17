# backend/app/agent/explore/service.py
"""EXPLORE evidence service - single retrieve_evidence entry point.

Returns EvidenceBundle + SpatialCognitionEvidence. Never returns candidate
BSMs, bbox, or intent. Deterministic (no LLM).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Mapping

from app.contracts.evidence.evidence_contracts import (
    ExplorationRequest,
    EvidenceBundle,
    EvidenceFact,
    EvidenceSource,
    ExplorationResult,
    SpatialCognitionEvidence,
)
from app.infrastructure.logging import get_logger
from app.evidence.retrieval.query_planner import build_query_plan, request_fingerprint
from app.evidence.retrieval.router import RetrieverKind
from app.evidence.retrieval.sufficiency import evaluate_sufficiency

logger = get_logger(__name__)
_EVIDENCE_CACHE: dict[tuple, ExplorationResult] = {}
_GATE_EVIDENCE_CACHE: dict[str, list[ExplorationResult]] = {}


def _gate_evidence_digest(session_id: str) -> str:
    entries = []
    for result in _GATE_EVIDENCE_CACHE.get(session_id, []):
        entries.append({
            "request": result.evidence_bundle.request,
            "facts": [fact.model_dump(mode="json") for fact in result.evidence_bundle.facts],
            "sources": [source.model_dump(mode="json") for source in result.evidence_bundle.sources],
        })
    raw = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_versions(session_id: str, supplied: Mapping[str, str] | None = None) -> tuple[tuple[str, str], ...]:
    from app.evidence.retrieval.retrievers.artifact_retriever import RETRIEVER_VERSION as artifact_version
    from app.evidence.retrieval.retrievers.bundle_retriever import RETRIEVER_VERSION as bundle_version
    from app.evidence.retrieval.retrievers.history_retriever import RETRIEVER_VERSION as history_version
    from app.evidence.retrieval.retrievers.integrity_retriever import RETRIEVER_VERSION as integrity_version
    from app.evidence.retrieval.retrievers.kg_retriever import RETRIEVER_VERSION as kg_version
    from app.evidence.retrieval.retrievers.report_retriever import RETRIEVER_VERSION as report_version

    versions: dict[str, str] = {
        "report": report_version,
        "kg": kg_version,
        "bundle": bundle_version,
        "artifact": artifact_version,
        "history": history_version,
        "integrity": integrity_version,
    }
    if supplied:
        versions.update({str(key): str(value) for key, value in supplied.items()})
    return tuple(sorted(versions.items()))


async def _active_source_versions(session_id: str, supplied: Mapping[str, str] | None = None) -> tuple[tuple[str, str], ...]:
    """Include active checkpoint artifact digests in the cache identity."""
    versions = dict(_source_versions(session_id, supplied))
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values(session_id)
        refs = dict((state or {}).get("artifact_refs") or {})
        digest_payload = {}
        for key, ref in sorted(refs.items()):
            if isinstance(ref, dict):
                digest = ref.get("descriptor_digest") or ref.get("digest") or ""
            else:
                digest = getattr(ref, "descriptor_digest", "") or getattr(ref, "digest", "") or ""
            digest_payload[key] = str(digest)
        context_version = str((state or {}).get("context_version") or "")
        raw = json.dumps({"context": context_version, "refs": digest_payload}, sort_keys=True)
        versions["active_artifacts"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    except Exception as exc:
        # Source unavailability must not make broad context injection fail;
        # the integrity retriever will report the missing source explicitly.
        logger.debug("[retrieve_evidence] active source version unavailable: %s", exc)
        versions["active_artifacts"] = "unavailable"
    return tuple(sorted(versions.items()))


async def _invoke(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a retriever while preserving compatibility with old test doubles."""
    try:
        return await function(*args, **kwargs)
    except TypeError as exc:
        if kwargs:
            logger.debug("retriever legacy signature fallback: %s", exc)
            return await function(*args)
        raise


async def retrieve_evidence(
    request: ExplorationRequest,
    session_id: str,
    village_name: str = "",
    source_versions: Mapping[str, str] | None = None,
) -> ExplorationResult:
    """Retrieve evidence from all session sources for a planning stage.

    Searches: session KG, VillageBundle, all AnalysisReports (content),
    typed artifacts (placeholder until Wave D/E).

    Returns ExplorationResult with evidence_bundle and spatial_cognition.
    """
    versions = await _active_source_versions(session_id, source_versions)
    cache_key = (session_id, request_fingerprint(request), versions, _gate_evidence_digest(session_id))
    cached = _EVIDENCE_CACHE.get(cache_key)
    if cached is not None:
        logger.debug("[retrieve_evidence] cache hit session=%s dimension=%s stage=%s", session_id, request.dimension_key, request.stage)
        return cached

    from app.evidence.retrieval.retrievers.artifact_retriever import retrieve_from_artifacts
    from app.evidence.retrieval.retrievers.bundle_retriever import retrieve_from_bundle
    from app.evidence.retrieval.retrievers.history_retriever import retrieve_from_history
    from app.evidence.retrieval.retrievers.integrity_retriever import retrieve_from_integrity
    from app.evidence.retrieval.retrievers.kg_retriever import retrieve_from_kg
    from app.evidence.retrieval.retrievers.report_retriever import retrieve_from_reports

    all_facts: List[EvidenceFact] = []
    all_sources: List[EvidenceSource] = []

    plan = build_query_plan(request)
    failed_sources: list[str] = []
    kg_facts: List[EvidenceFact] = []
    cognition = SpatialCognitionEvidence()
    for query in plan.queries:
        try:
            if query.retriever is RetrieverKind.REPORT:
                facts, sources = await _invoke(
                    retrieve_from_reports,
                    session_id,
                    request.dimension_key,
                    request.stage,
                    query=query.query,
                    required_facts=list(query.required_facts),
                    entity_scope=list(query.entity_scope),
                )
            elif query.retriever is RetrieverKind.KG:
                facts, cognition = await _invoke(
                    retrieve_from_kg,
                    session_id,
                    village_name,
                    request.dimension_key,
                    request.stage,
                    query=query.query,
                    required_facts=list(query.required_facts),
                    entity_scope=list(query.entity_scope),
                )
                sources = []
                if facts or cognition.kg_confidence > 0:
                    sources = [EvidenceSource(source_type="kg", reference=f"session_kg:{session_id}", confidence=cognition.kg_confidence)]
            elif query.retriever is RetrieverKind.BUNDLE:
                facts, sources = await _invoke(
                    retrieve_from_bundle,
                    session_id,
                    list(query.entity_scope),
                    query=query.query,
                    required_facts=list(query.required_facts),
                )
            elif query.retriever is RetrieverKind.ARTIFACT:
                facts, sources = await _invoke(
                    retrieve_from_artifacts,
                    session_id,
                    query=query.query,
                    source_refs=query.source_refs,
                    required_facts=query.required_facts,
                )
            elif query.retriever is RetrieverKind.HISTORY:
                facts, sources = await _invoke(
                    retrieve_from_history,
                    session_id,
                    query=query.query,
                    source_refs=query.source_refs,
                    required_facts=query.required_facts,
                )
            else:
                facts, sources = await _invoke(
                    retrieve_from_integrity,
                    session_id,
                    query=query.query,
                    source_refs=query.source_refs,
                    required_facts=query.required_facts,
                )
            all_facts.extend(facts)
            all_sources.extend(sources)
        except Exception as exc:
            failed_sources.append(query.retriever.value)
            logger.warning("[retrieve_evidence] %s retriever failed: %s", query.retriever.value, exc)

    # Evidence found by a gate request is promoted into the next canonical
    # context request.  This gives the gate loop a real hand-off without
    # requiring workers to concatenate a second prompt section.
    for prior in _GATE_EVIDENCE_CACHE.get(session_id, []):
        all_facts.extend(prior.evidence_bundle.facts)
        all_sources.extend(prior.evidence_bundle.sources)
        if prior.spatial_cognition and prior.spatial_cognition.kg_confidence > cognition.kg_confidence:
            cognition = prior.spatial_cognition

    # Deduplicate typed facts by normalized content and provenance, not a
    # lossy first-80-character prefix.
    seen = set()
    unique_facts: List[EvidenceFact] = []
    for f in all_facts:
        key = (
            " ".join(f.statement.split()).casefold(),
            tuple(sorted(f.source_refs)),
            f.fact_type,
        )
        if key not in seen:
            seen.add(key)
            unique_facts.append(f)

    # Deduplicate sources by reference
    seen_src = set()
    unique_sources: List[EvidenceSource] = []
    for s in all_sources:
        if s.reference not in seen_src:
            seen_src.add(s.reference)
            unique_sources.append(s)

    confidence = 0.0
    if unique_facts:
        confidence = sum(f.confidence for f in unique_facts) / len(unique_facts)

    result = ExplorationResult(
        evidence_bundle=EvidenceBundle(
            request=request.query,
            facts=unique_facts,
            sources=unique_sources,
            confidence=round(confidence, 3),
            unresolved=[],
        ),
        spatial_cognition=cognition,
    )
    decision = evaluate_sufficiency(request, result)
    unresolved = list(decision.missing_facts or decision.ambiguous_facts)
    if decision.status.value in {"source_unavailable", "insufficient_geometry"} and not unresolved:
        unresolved = [decision.reason]
    result.evidence_bundle.unresolved = unresolved
    if failed_sources and not all_sources:
        result.evidence_bundle.unresolved = [f"source_unavailable:{name}" for name in failed_sources]
    _EVIDENCE_CACHE[cache_key] = result
    return result


def render_evidence_prompt_section(
    bundle: EvidenceBundle,
    cognition: SpatialCognitionEvidence | None = None,
) -> str:
    """Render an ExplorationResult as a unified markdown prompt section.

    Replaces the old _optimize_semantics + _build_explore_brief output.
    """
    lines = ["## EXPLORE 证据"]

    if cognition and cognition.village_overview:
        lines.append(f"**村域概况**: {cognition.village_overview}")
        if cognition.spatial_pattern:
            lines.append(f"**空间格局**: {cognition.spatial_pattern}")
        if cognition.constraint_coverage:
            lines.append(f"**约束覆盖**: {cognition.constraint_coverage}")
        if cognition.topology_facts:
            lines.append("**拓扑结构**: " + "; ".join(cognition.topology_facts[:5]))
        if cognition.entity_annotations:
            lines.append("**关键实体**: " + "、".join(cognition.entity_annotations[:8]))
        lines.append(f"**KG 置信度**: {cognition.kg_confidence:.2f}")

    if bundle.facts:
        lines.append("")
        lines.append("**空间事实**:")
        for fact in bundle.facts[:12]:
            lines.append(f"- {fact.statement}")

    if bundle.sources:
        src_summary = ", ".join(
            f"{s.source_type}:{s.reference}" for s in bundle.sources[:6]
        )
        lines.append(f"**证据来源**: {src_summary}")

    if bundle.unresolved:
        lines.append("**待查问题**: " + "; ".join(bundle.unresolved[:3]))

    return "\n".join(lines)


async def retrieve_evidence_for_gate(
    gate_decision: dict,
    session_id: str,
    village_name: str = "",
) -> list:
    """Translate a gate's EXPLORE pending_requests into evidence retrievals.

    Wave M2: called when a layer gate returns feedback_route="EXPLORE".
    Converts each PendingRequest (with stage="explore") into an
    ExplorationRequest, calls retrieve_evidence, and returns the list of
    ExplorationResult objects. Non-EXPLORE gates or empty pending_requests
    produce no retrievals.
    """
    route = gate_decision.get("feedback_route") if isinstance(gate_decision, dict) else None
    if route != "EXPLORE":
        return []

    pending = gate_decision.get("pending_requests") or []
    if not pending:
        return []

    results: list[ExplorationResult] = []
    for pr in pending:
        if isinstance(pr, dict):
            ctx = pr.get("context") or {}
            required_fact = ctx.get("required_fact")
            required_facts = required_fact if isinstance(required_fact, list) else [required_fact] if required_fact else []
            request = ExplorationRequest(
                run_id=session_id,
                request_type=pr.get("request_type", "evidence_gap"),
                query=ctx.get("message", ctx.get("reason", "")),
                context_refs=list(ctx.get("source_refs") or []),
                evidence_gaps_to_resolve=list(ctx.get("gaps") or []),
                dimension_key=ctx.get("dimension", ""),
                stage=gate_decision.get("stage", ""),
                query_purpose="gap_resolution",
                questions=list(ctx.get("questions") or []),
                required_facts=required_facts,
                entity_scope=list(ctx.get("entity_scope") or []),
            )
        else:
            # PendingRequest Pydantic model
            ctx = getattr(pr, "context", {}) or {}
            request = ExplorationRequest(
                run_id=session_id,
                request_type=getattr(pr, "request_type", "evidence_gap"),
                query=ctx.get("message", ctx.get("reason", "")),
                context_refs=list(ctx.get("source_refs") or []),
                evidence_gaps_to_resolve=list(ctx.get("gaps") or []),
                dimension_key=ctx.get("dimension", ""),
                stage=gate_decision.get("stage", ""),
                query_purpose="gap_resolution",
                questions=list(ctx.get("questions") or []),
                required_facts=list(ctx.get("required_facts") or []),
                entity_scope=list(ctx.get("entity_scope") or []),
            )
        try:
            result = await retrieve_evidence(request, session_id, village_name)
            results.append(result)
        except Exception as e:
            logger.warning("[retrieve_evidence_for_gate] failed for %s: %s", request.request_type, e)

    if results:
        _GATE_EVIDENCE_CACHE.setdefault(session_id, []).extend(results)
        # Keep only the latest bounded gate evidence to avoid prompt growth on
        # repeated retries.  The cache key of the canonical request still
        # includes all request fields and active artifact versions.
        _GATE_EVIDENCE_CACHE[session_id] = _GATE_EVIDENCE_CACHE[session_id][-8:]
    return results


def retrieve_evidence_for_gate_sync(
    gate_decision: dict,
    session_id: str,
    village_name: str = "",
) -> list[ExplorationResult]:
    """Synchronous routing adapter used by LangGraph conditional edges.

    Conditional edges are synchronous in the current graph.  Run the async
    retrieval in a short-lived worker thread when an event loop is already
    active; this preserves the graph API while making pending requests cause a
    real, scoped retrieval before the next worker dispatch.
    """
    async def _run() -> list[ExplorationResult]:
        return await retrieve_evidence_for_gate(gate_decision, session_id, village_name)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="explore-gate") as executor:
        return executor.submit(lambda: asyncio.run(_run())).result()


__all__ = [
    "retrieve_evidence",
    "render_evidence_prompt_section",
    "retrieve_evidence_for_gate",
    "retrieve_evidence_for_gate_sync",
]
