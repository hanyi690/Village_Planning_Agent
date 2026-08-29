"""Central Evidence Runtime - single retrieve_evidence execution entry point.

Returns EvidenceBundle + SpatialCognitionEvidence. Never returns candidate
BSMs, bbox, or intent. Deterministic (no LLM).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Mapping

from app.contracts.evidence.evidence_contracts import (
    ExplorationRequest,
    EvidenceBundle,
    EvidenceCoverage,
    EvidenceFact,
    EvidenceSource,
    ExplorationResult,
    SpatialCognitionEvidence,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.infrastructure.logging import get_logger
from app.infrastructure.evidence_runtime.coverage import build_evidence_coverage
from app.infrastructure.evidence_runtime.query_planner import build_query_plan, request_fingerprint
from app.infrastructure.evidence_runtime.retriever_router import RetrieverKind
from app.infrastructure.evidence_runtime.sufficiency import evaluate_sufficiency
from app.infrastructure.evidence_runtime.fact_quality import apply_fact_quality
from app.infrastructure.evidence_runtime.fusion import fuse_facts, fuse_sources
from app.infrastructure.evidence_runtime.provenance import annotate_sources

logger = get_logger(__name__)
_EVIDENCE_CACHE: OrderedDict[tuple, ExplorationResult] = OrderedDict()
_GATE_EVIDENCE_CACHE: dict[str, list[ExplorationResult]] = {}

# Gate-triggered retrieval is allowed to ask a bounded number of narrower
# questions.  This is deliberately a small orchestration limit, not a hidden
# retry policy: every follow-up is derived from an explicit unresolved
# requirement and is visible in the returned query trace.
_GATE_GAP_MAX_DEPTH = 2
_GATE_GAP_MAX_REQUESTS = 8


def gate_evidence_digest(session_id: str) -> str:
    entries = []
    for result in _GATE_EVIDENCE_CACHE.get(session_id, []):
        entries.append({
            "request": result.evidence_bundle.request,
            "facts": [fact.model_dump(mode="json") for fact in result.evidence_bundle.facts],
            "sources": [source.model_dump(mode="json") for source in result.evidence_bundle.sources],
        })
    # Gate retrieval appends each attempt to the bounded session cache.  A
    # cached retry therefore must not look like new evidence merely because
    # the same typed result was appended a second time.  Canonicalize exact
    # entries before hashing; changed facts/sources still produce a new digest.
    entries = sorted({
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for entry in entries
    })
    raw = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_versions(session_id: str, supplied: Mapping[str, str] | None = None) -> tuple[tuple[str, str], ...]:
    from app.infrastructure.evidence_runtime.retrievers.artifact_retriever import RETRIEVER_VERSION as artifact_version
    from app.infrastructure.evidence_runtime.retrievers.bundle_retriever import RETRIEVER_VERSION as bundle_version
    from app.infrastructure.evidence_runtime.retrievers.integrity_retriever import RETRIEVER_VERSION as integrity_version
    from app.infrastructure.evidence_runtime.retrievers.l1_retriever import RETRIEVER_VERSION as l1_version
    from app.infrastructure.evidence_runtime.retrievers.kg_retriever import RETRIEVER_VERSION as kg_version
    from app.infrastructure.evidence_runtime.retrievers.local_text_retriever import RETRIEVER_VERSION as local_text_version
    from app.infrastructure.evidence_runtime.retrievers.rag_retriever import RETRIEVER_VERSION as rag_version
    from app.infrastructure.evidence_runtime.retrievers.report_retriever import RETRIEVER_VERSION as report_version
    from app.infrastructure.evidence_runtime.retrievers.cached_map_retriever import RETRIEVER_VERSION as cached_map_version

    versions: dict[str, str] = {
        "report": report_version,
        "kg": kg_version,
        "bundle": bundle_version,
        "artifact": artifact_version,
        "integrity": integrity_version,
        "l1": l1_version,
        "local_text": local_text_version,
        "rag": rag_version,
        "external_map_cache": cached_map_version,
    }
    if supplied:
        versions.update({str(key): str(value) for key, value in supplied.items()})
    return tuple(sorted(versions.items()))


def _retrieval_runtime_fingerprint(runtime_config: Mapping[str, Any] | None) -> str:
    config = dict(runtime_config or {})
    payload = {
        "rag_enabled": config.get("rag_enabled"),
        "rag_layer_config": config.get("rag_layer_config"),
        "evidence_external_for_llm": config.get("evidence_external_for_llm"),
        "external_provider": os.getenv("EVIDENCE_EXTERNAL_PROVIDER", "disabled"),
        "external_for_llm_env": os.getenv("EVIDENCE_EXTERNAL_FOR_LLM", "false"),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


async def _active_source_versions(session_id: str, supplied: Mapping[str, str] | None = None) -> tuple[tuple[str, str], ...]:
    """Include active checkpoint artifact digests in the cache identity."""
    versions = dict(_source_versions(session_id, supplied))
    try:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        # Evidence lookup is also used by bounded CLI/unit-test calls that do
        # not own the FastAPI lifespan.  Merely computing a cache key must not
        # lazily create the global LangGraph aiosqlite checkpointer: its worker
        # thread is intentionally long-lived and can only be reclaimed by the
        # application shutdown hook.  The running application initializes the
        # runtime before serving requests, so it still receives the active
        # artifact digest; cold callers get a distinct cache identity without
        # acquiring process-wide resources.
        if not PlanningRuntimeService._initialized or PlanningRuntimeService._graph is None:
            versions["active_artifacts"] = "runtime_cold"
            versions["retrieval_runtime"] = _retrieval_runtime_fingerprint(None)
            return tuple(sorted(versions.items()))

        state = await PlanningRuntimeService.aget_state_values_if_initialized(session_id)
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
        runtime_config = dict(
            (state or {}).get("config")
            or ((state or {}).get("runtime") or {}).get("config")
            or {}
        )
        versions["retrieval_runtime"] = _retrieval_runtime_fingerprint(runtime_config)
    except Exception as exc:
        # Source unavailability must not make broad context injection fail;
        # the integrity retriever will report the missing source explicitly.
        logger.debug("[retrieve_evidence] active source version unavailable: %s", exc)
        versions["active_artifacts"] = "unavailable"
    return tuple(sorted(versions.items()))


def _context_evidence_digest(session_id: str) -> str:
    """Version the retrieval cache by the mutable typed evidence context.

    Source-semantic and L1 hydration can update a cached ``PlanningContext``
    without changing the uploaded bundle or workflow artifact versions.  A
    query cached before that update must therefore never be reused after the
    update, otherwise the public evidence API can return stale ambiguity.
    """
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context

        context = get_cached_context(session_id)
    except Exception:
        return ""
    if context is None:
        return ""

    def _typed_dump(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump(mode="json")
            except Exception:
                return str(value)
        if isinstance(value, dict):
            return {
                str(key): _typed_dump(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [_typed_dump(item) for item in value]
        return value

    payload = {
        "context_version": str(getattr(context, "version", "") or ""),
        "data_snapshot_digest": str(
            getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
        ),
        "kg_version": str(getattr(context, "kg_version", "") or ""),
        "l1_snapshot_ref": str(getattr(context, "l1_snapshot_ref", "") or ""),
        "source_semantic_fingerprint": str(
            getattr(context, "source_semantic_fingerprint", "") or ""
        ),
        "source_semantic_decisions": _typed_dump(
            getattr(context, "source_semantic_decisions", {}) or {}
        ),
        "location_mentions": _typed_dump(
            getattr(context, "location_mentions", None)
            or getattr(context, "location_facts", [])
            or []
        ),
        "l1_fact_records": _typed_dump(getattr(context, "l1_fact_records", []) or []),
        "external_observation_digest": str(
            getattr(getattr(context, "external_observation_snapshot", None), "digest", "") or ""
        ),
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _external_policy_fingerprint(policy: Any | None) -> str:
    """Return a stable cache identity for the external evidence gate."""
    if policy is None:
        return ""
    payload = {
        "type": f"{type(policy).__module__}.{type(policy).__name__}",
        "allowed_dimensions": list(getattr(policy, "allowed_dimensions", []) or []),
        "freshness": getattr(policy, "freshness", {}) or {},
        "max_cost": getattr(policy, "max_cost", None),
        "allowlist": list(getattr(policy, "allowlist", []) or []),
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _invoke(function: Any, *args: Any, **kwargs: Any) -> Any:
    """Call one retriever through its typed, current contract."""
    return await function(*args, **kwargs)


async def extract_spatial_query_spec(
    context: Any,
    query: str,
    *,
    scope_key: str = "evidence-query",
) -> tuple[Any | None, dict[str, Any]]:
    """Run the optional typed spatial parser with an explicit outcome trace.

    HTTP and LLM-tool callers must share the same parser gate.  The parser is
    never allowed to manufacture an identity; EvidenceGraph still owns local
    candidate binding.  A disabled, empty, or failed provider result is
    returned as a diagnostic instead of being silently converted to a clean
    deterministic parse.
    """
    from app.core.llm_config import get_llm_settings

    disabled = get_llm_settings().ground_llm_is_disabled()
    if disabled:
        return None, {
            "step": "spatial_query_parser",
            "status": "disabled",
            "provider": "ground_llm",
            "reason": "ground_llm_disabled",
        }
    try:
        from app.spatial.grounding.call_budget import get_ground_llm_budget
        from app.spatial.grounding.flash_mention_extractor import (
            extract_spatial_reference_spec,
        )

        spec = await extract_spatial_reference_spec(
            query,
            budget=get_ground_llm_budget(
                context,
                scope_key=(
                    f"{scope_key}:"
                    + hashlib.sha256(query.encode("utf-8")).hexdigest()
                ),
            ),
            raise_on_failure=True,
        )
        return spec, {
            "step": "spatial_query_parser",
            "status": "resolved" if spec is not None else "no_structured_reference",
            "provider": "ground_llm",
        }
    except Exception as exc:
        return None, {
            "step": "spatial_query_parser",
            "status": "failed",
            "provider": "ground_llm",
            "error": f"{type(exc).__name__}: {exc}",
        }




def _enrich_local_spatial_graph(
    result: ExplorationResult,
    context: Any,
    *,
    query: str,
    village_name: str,
    entity_scope: list[str],
    spatial_spec: Any = None,
    candidate_offset: int = 0,
    candidate_limit: int = 12,
) -> ExplorationResult:
    """Join local L1/KG/bundle identity before optional external retrieval.

    EvidenceGraph is a local authoritative source, but its structured packet
    used to be attached only after the external sufficiency decision.  That
    ordering could spend external quota on a query already resolved to a
    bundle feature.  A graph candidate gets a typed local source marker when
    the ordinary retrievers returned no source rows, keeping sufficiency
    fail-closed while allowing identity questions to terminate locally.
    """
    from app.infrastructure.evidence_runtime.evidence_graph import (
        append_feature_identity_facts,
        enrich_evidence_packet_with_spatial_graph,
    )

    packet = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(
            request=query,
            query_fingerprint=request_fingerprint(
                ExplorationRequest(
                    run_id="local-graph",
                    request_type="spatial_lookup",
                    query=query,
                    entity_scope=list(entity_scope),
                )
            ),
        ),
        context,
        query=query,
        village_name=village_name,
        entity_scope=entity_scope,
        spatial_spec=spatial_spec,
        candidate_offset=candidate_offset,
        candidate_limit=candidate_limit,
    )
    bundle = append_feature_identity_facts(
        result.evidence_bundle,
        packet,
        context=context,
    )
    if packet.candidate_refs and not bundle.sources:
        digest = str(packet.bundle_snapshot_digest or "local")
        bundle = bundle.model_copy(update={
            "sources": [
                EvidenceSource(
                    source_type="bundle",
                    reference=f"bundle:snapshot:{digest}",
                    confidence=max(
                        0.5,
                        max(
                            (
                                float(
                                    getattr(
                                        item,
                                        "source_authority_score",
                                        0.0,
                                    )
                                    or 0.0
                                )
                                for item in packet.candidate_refs
                            ),
                            default=0.0,
                        ),
                    ),
                )
            ]
        })
    if bundle.facts:
        bundle.confidence = round(
            sum(float(fact.confidence or 0.0) for fact in bundle.facts)
            / len(bundle.facts),
            3,
        )
    return result.model_copy(update={
        "evidence_bundle": bundle,
        "evidence_packet": packet,
    })


def _needs_spatial_graph(request: ExplorationRequest, spatial_spec: Any = None) -> bool:
    """Keep geometry candidate joins out of ordinary factual retrieval."""

    return request.request_type == "spatial_lookup" or spatial_spec is not None


async def retrieve_evidence(
    request: ExplorationRequest,
    session_id: str,
    village_name: str = "",
    source_versions: Mapping[str, str] | None = None,
    external_port: Any | None = None,
    external_policy: Any | None = None,
    spatial_spec: Any = None,
) -> ExplorationResult:
    """Retrieve evidence from all session sources for a planning stage.

    Searches: session KG, VillageBundle, all AnalysisReports (content),
    typed artifacts (placeholder until Wave D/E).

    Returns ExplorationResult with evidence_bundle and spatial_cognition.
    """
    requested_entity_scopes = list(request.entity_scope)
    structured_entity_scopes = (
        spatial_spec.all_retrieval_scopes()
        if spatial_spec is not None
        and callable(getattr(spatial_spec, "all_retrieval_scopes", None))
        else []
    )
    effective_entity_scopes = list(dict.fromkeys([
        *requested_entity_scopes,
        *structured_entity_scopes,
    ]))
    if effective_entity_scopes != list(request.entity_scope):
        request = request.model_copy(update={
            "entity_scope": effective_entity_scopes,
        })
    versions = await _active_source_versions(session_id, source_versions)
    context_evidence_digest = _context_evidence_digest(session_id)
    if external_port is not None:
        versions = tuple(
            sorted(
                [
                    *versions,
                    (
                        "external_provider",
                        str(getattr(external_port, "version", "external-v1")),
                    ),
                ]
            )
        )
    spatial_spec_digest = ""
    if spatial_spec is not None:
        try:
            spatial_spec_digest = hashlib.sha256(
                json.dumps(
                    spatial_spec.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        except Exception:
            spatial_spec_digest = str(spatial_spec)
    cache_key = (
        session_id,
        str(village_name or ""),
        request_fingerprint(request),
        versions,
        gate_evidence_digest(session_id),
        context_evidence_digest,
        spatial_spec_digest,
        _external_policy_fingerprint(external_policy),
    )
    cached = _EVIDENCE_CACHE.get(cache_key)
    if cached is not None:
        _EVIDENCE_CACHE.move_to_end(cache_key)
        logger.debug("[retrieve_evidence] cache hit session=%s dimension=%s stage=%s", session_id, request.dimension_key, request.stage)
        return cached

    from app.infrastructure.evidence_runtime.retrievers.artifact_retriever import retrieve_from_artifacts
    from app.infrastructure.evidence_runtime.retrievers.bundle_retriever import retrieve_from_bundle
    from app.infrastructure.evidence_runtime.retrievers.integrity_retriever import retrieve_from_integrity
    from app.infrastructure.evidence_runtime.retrievers.l1_retriever import retrieve_from_l1_context
    from app.infrastructure.evidence_runtime.retrievers.kg_retriever import retrieve_from_kg
    from app.infrastructure.evidence_runtime.retrievers.local_text_retriever import retrieve_from_local_text
    from app.infrastructure.evidence_runtime.retrievers.report_retriever import retrieve_from_reports
    from app.infrastructure.evidence_runtime.retrievers.cached_map_retriever import (
        retrieve_from_cached_map,
    )

    all_facts: List[EvidenceFact] = []
    all_sources: List[EvidenceSource] = []

    # The API may infer retrieval scopes from the natural-language query for
    # candidate recall.  That must not narrow an originally unscoped project
    # query back to one layer: source coverage follows the original request,
    # while inferred scopes remain query hints.
    project_wide_query = (
        request.query_purpose == "gap_resolution"
        or (
            not requested_entity_scopes
            and request.request_type in {"fact_check", "evidence_gap", "spatial_lookup"}
        )
    )
    if project_wide_query:
        request = request.model_copy(update={"project_wide": True})
    plan = build_query_plan(request)
    failed_sources: list[str] = []
    retrieval_status: list[dict[str, Any]] = []
    retrieval_status.append({
        "step": "semantic_candidate_scope",
        "status": (
            "llm_structured"
            if structured_entity_scopes
            else "request_declared"
            if requested_entity_scopes
            else "unscoped_exact_evidence"
        ),
        "requested_scopes": requested_entity_scopes,
        "structured_scopes": structured_entity_scopes,
        "effective_scopes": effective_entity_scopes,
        "project_wide": project_wide_query,
        "source_coverage": "project_wide" if project_wide_query else "scoped",
    })
    kg_facts: List[EvidenceFact] = []
    cognition = SpatialCognitionEvidence()
    for query in plan.queries:
        try:
            if query.retriever is RetrieverKind.LOCAL_TEXT:
                facts, sources = await _invoke(
                    retrieve_from_local_text,
                    session_id,
                    request.dimension_key,
                    request.stage,
                    query=query.query,
                    required_facts=list(query.required_facts),
                    entity_scope=list(query.entity_scope),
                )
            elif query.retriever is RetrieverKind.REPORT:
                facts, sources = await _invoke(
                    retrieve_from_reports,
                    session_id,
                    request.dimension_key,
                    request.stage,
                    query=query.query,
                    required_facts=list(query.required_facts),
                    entity_scope=list(query.entity_scope),
                )
            elif query.retriever is RetrieverKind.RAG:
                from app.infrastructure.evidence_runtime.retrievers.rag_retriever import (
                    peek_rag_log,
                    retrieve_from_rag,
                )

                facts, sources = await _invoke(
                    retrieve_from_rag,
                    session_id,
                    request.dimension_key,
                    request.stage,
                    query=query.query,
                    required_facts=list(query.required_facts),
                    entity_scope=list(query.entity_scope),
                )
                rag_log = peek_rag_log(session_id, request.dimension_key)
                skip_reason = str(getattr(rag_log, "skip_reason", "") or "")
                if skip_reason:
                    rag_status = (
                        "rag_disabled"
                        if skip_reason in {
                            "disabled_by_config",
                            "dimension_rag_query_missing",
                        }
                        else "external_rag_unavailable"
                    )
                    retrieval_status.append({
                        "step": "rag_source",
                        "status": rag_status,
                        "reason": skip_reason,
                    })
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
            elif query.retriever is RetrieverKind.EXTERNAL:
                # External retrieval is deferred until local sufficiency is
                # evaluated below.  This guarantees that an injected
                # provider is not contacted when L1/KG/bundle already answer.
                retrieval_status.append({
                    "step": "retriever",
                    "retriever": query.retriever.value,
                    "status": "deferred",
                    "reason": "local_sufficiency_first",
                })
                continue
            else:
                facts, sources = await _invoke(
                    retrieve_from_integrity,
                    session_id,
                    query=query.query,
                    source_refs=query.source_refs,
                    required_facts=query.required_facts,
                )
            retrieval_status.append({
                "step": "retriever",
                "retriever": query.retriever.value,
                "status": "returned" if facts or sources else "empty",
                "fact_count": len(facts),
                "source_count": len(sources),
            })
            all_facts.extend(facts)
            all_sources.extend(sources)
        except Exception as exc:
            failed_sources.append(query.retriever.value)
            retrieval_status.append({
                "step": "retriever",
                "retriever": query.retriever.value,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            })
            logger.warning("[retrieve_evidence] %s retriever failed: %s", query.retriever.value, exc)

    # Evidence found by a gate request is promoted into the next canonical
    # context request.  This gives the gate loop a real hand-off without
    # requiring workers to concatenate a second prompt section.
    for prior in _GATE_EVIDENCE_CACHE.get(session_id, []):
        all_facts.extend(prior.evidence_bundle.facts)
        all_sources.extend(prior.evidence_bundle.sources)
        if prior.spatial_cognition and prior.spatial_cognition.kg_confidence > cognition.kg_confidence:
            cognition = prior.spatial_cognition

    cached_context = None
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context

        cached_context = get_cached_context(session_id)
        if cached_context is not None:
            from app.infrastructure.evidence_runtime.context_hydration import (
                hydrate_source_semantic_context,
            )

            semantic_snapshot = await hydrate_source_semantic_context(
                session_id,
                cached_context,
            )
            semantic_diagnostics = list(
                getattr(cached_context, "source_semantic_diagnostics", []) or []
            )
            retrieval_status.append({
                "step": "source_semantic_runtime",
                "status": (
                    "snapshot_ready"
                    if semantic_snapshot is not None
                    else "unresolved_or_disabled"
                ),
                "fingerprint": str(
                    getattr(cached_context, "source_semantic_fingerprint", "") or ""
                ),
                "diagnostics": semantic_diagnostics[-8:],
            })
            l1_facts, l1_sources = retrieve_from_l1_context(
                cached_context,
                query=request.query,
                required_facts=[*request.required_facts, *request.questions],
                dimension_key=request.dimension_key,
                strict_dimension=False,
                allow_cross_dimension=(
                    project_wide_query
                    or request.project_wide
                    or request.query_purpose == "gap_resolution"
                ),
            )
            all_facts.extend(l1_facts)
            all_sources.extend(l1_sources)
            map_facts, map_sources, map_trace = retrieve_from_cached_map(
                cached_context,
                query=request.query,
                entity_scope=request.entity_scope,
                limit=request.candidate_limit * 2,
            )
            all_facts.extend(map_facts)
            all_sources.extend(map_sources)
            retrieval_status.append({
                "step": "external_map_cache",
                **map_trace,
            })
    except Exception as exc:
        retrieval_status.append({
            "step": "context_hydration",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })
        logger.warning("[retrieve_evidence] context hydration unavailable: %s", exc)

    # Deduplicate typed facts by normalized content and provenance, not a
    # lossy first-80-character prefix.
    unique_facts = fuse_facts(all_facts)
    unique_sources = fuse_sources(all_sources)

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
    if cached_context is not None and _needs_spatial_graph(request, spatial_spec):
        try:
            result = _enrich_local_spatial_graph(
                result,
                cached_context,
                query=request.query,
                village_name=village_name,
                entity_scope=list(request.entity_scope),
                spatial_spec=spatial_spec,
                candidate_offset=request.candidate_offset,
                candidate_limit=request.candidate_limit,
            )
            unique_facts = list(result.evidence_bundle.facts)
            unique_sources = list(result.evidence_bundle.sources)
            all_sources = list(unique_sources)
            unique_facts = fuse_facts(unique_facts)
            unique_sources = fuse_sources(unique_sources)
        except Exception as exc:
            retrieval_status.append({
                "step": "evidence_graph_prefetch",
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            })
            logger.warning(
                "[retrieve_evidence] early spatial graph unavailable: %s",
                exc,
            )
    decision = evaluate_sufficiency(request, result)
    external_trace: list[dict[str, Any]] = []
    if external_port is not None and decision.status.value != "sufficient":
        try:
            from app.infrastructure.evidence_runtime.external_search_policy import ExternalSearchPolicy
            from app.infrastructure.evidence_runtime.retrievers.external_retriever import (
                retrieve_from_external,
            )

            facts, sources, trace = await retrieve_from_external(
                session_id,
                provider=external_port,
                policy=external_policy or ExternalSearchPolicy(),
                dimension_key=request.dimension_key,
                query=request.query,
                entity_scope=request.entity_scope,
                required_facts=[*request.required_facts, *request.questions],
                source_refs=request.context_refs,
            )
            external_trace.append(trace)
            unique_facts = fuse_facts([*unique_facts, *facts])
            unique_sources = fuse_sources([*unique_sources, *sources])
            result.evidence_bundle.facts = unique_facts
            result.evidence_bundle.sources = unique_sources
            result.evidence_bundle.confidence = round(
                sum(fact.confidence for fact in unique_facts) / len(unique_facts),
                3,
            ) if unique_facts else 0.0
            # The local-source failure check below must see external facts
            # accepted in this same retrieval round.  Otherwise a successful
            # external fallback would be overwritten by stale ``all_sources``
            # state and returned as source-unavailable.
            all_sources = list(unique_sources)
            decision = evaluate_sufficiency(request, result)
        except Exception as exc:  # noqa: BLE001 - external is optional
            external_trace.append(
                {"step": "external_exception", "status": "failed", "error": str(exc)}
            )
            logger.warning("[retrieve_evidence] external retriever failed: %s", exc)
    unique_sources = annotate_sources(
        unique_sources,
        context=cached_context,
    )
    from app.infrastructure.evidence_runtime.provenance import (
        canonicalize_fact_provenance,
    )

    unique_facts = canonicalize_fact_provenance(
        unique_facts,
        unique_sources,
        session_id=session_id,
    )
    result.evidence_bundle.facts = unique_facts
    result.evidence_bundle.sources = unique_sources
    unresolved = list(decision.missing_facts or decision.ambiguous_facts)
    if decision.status.value in {"source_unavailable", "insufficient_geometry"} and not unresolved:
        unresolved = [decision.reason]
    external_failures = []
    for trace in external_trace:
        if not isinstance(trace, dict):
            continue
        status = str(trace.get("status") or "").strip().lower()
        if status in {"success", "allowed", ""}:
            continue
        failure = trace.get("failure")
        code = (
            str(failure.get("code") or "").strip()
            if isinstance(failure, dict)
            else ""
        ) or str(trace.get("code") or "external_unresolved").strip()
        if code:
            external_failures.append(f"external:{code}")
    unresolved = list(dict.fromkeys([*unresolved, *external_failures]))
    result.evidence_bundle.unresolved = unresolved
    if failed_sources and not unique_sources:
        result.evidence_bundle.unresolved = list(dict.fromkeys([
            *result.evidence_bundle.unresolved,
            *(f"source_unavailable:{name}" for name in failed_sources),
        ]))
    decision_status = str(decision.status.value)
    packet_status = {
        "sufficient": "resolved",
        "ambiguous": "multiple",
    }.get(decision_status, "unresolved")
    sufficiency = (
        "sufficient"
        if decision_status == "sufficient"
        else "partial"
        if unique_facts
        else "insufficient"
    )
    packet_source_spans: list[str] = []
    packet_span_facts = [
        fact
        for fact in unique_facts
        if fact.fact_type == "l1_fact"
        or fact.evidence_role == "location_binding"
        or fact.fields.get("evidence_role") == "location_binding"
        or fact.source_kind == "l1_typed_fact"
    ]
    packet_span_facts.extend(
        fact for fact in unique_facts if fact not in packet_span_facts
    )
    for fact in packet_span_facts:
        role = fact.evidence_role or fact.fields.get("evidence_role", "")
        is_l1_spatial = (
            fact.fact_type == "l1_fact"
            or role == "location_binding"
            or fact.source_kind == "l1_typed_fact"
        )
        values = []
        if is_l1_spatial and fact.statement:
            values.append(f"L1空间事实：{fact.statement[:400]}")
        values.extend((fact.evidence_span, fact.source_locator))
        for value in values:
            text = str(value or "").strip()
            if text and text not in packet_source_spans:
                packet_source_spans.append(text)
            if len(packet_source_spans) >= 12:
                break
        if len(packet_source_spans) >= 12:
            break

    result.evidence_packet = EvidencePacket(
        request=request.query,
        query_fingerprint=request_fingerprint(request),
        candidate_offset=request.candidate_offset,
        candidate_limit=request.candidate_limit,
        source_spans=packet_source_spans,
        external_refs=[
            source.reference
            for source in unique_sources
            if source.source_type == "external"
        ][:12],
        ambiguity_status=packet_status,
        sufficiency=sufficiency,
        missing_evidence=list(result.evidence_bundle.unresolved)[:12],
        query_trace=[
            {
                "step": "retriever_plan",
                "retrievers": [item.value for item in plan.retrievers],
            },
            {"step": "sufficiency", "status": decision_status},
            *retrieval_status,
            *external_trace,
        ],
    )
    # The context cache is already populated by workflow bootstrap in normal
    # runs.  Enrich only when it is available; broad EXPLORE retrieval must
    # remain useful during cold start and must not rebuild a full context here.
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context
        from app.infrastructure.evidence_runtime.evidence_graph import (
            append_feature_identity_facts,
            enrich_evidence_packet_with_spatial_graph,
        )

        context = cached_context or get_cached_context(session_id)
        if context is not None and _needs_spatial_graph(request, spatial_spec):
            result.evidence_packet = enrich_evidence_packet_with_spatial_graph(
                result.evidence_packet,
                context,
                query=request.query,
                village_name=village_name,
                entity_scope=request.entity_scope,
                spatial_spec=spatial_spec,
                candidate_offset=request.candidate_offset,
                candidate_limit=request.candidate_limit,
            )
            result.evidence_bundle = append_feature_identity_facts(
                result.evidence_bundle,
                result.evidence_packet,
                context=context,
            )
    except Exception as exc:
        diagnostic = {
            "step": "evidence_graph_enrichment",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        result.evidence_packet = result.evidence_packet.model_copy(update={
            "query_trace": [
                *result.evidence_packet.query_trace,
                diagnostic,
            ][-24:],
            "missing_evidence": list(dict.fromkeys([
                *result.evidence_packet.missing_evidence,
                "evidence_graph_unavailable",
            ]))[:12],
            "sufficiency": (
                "partial"
                if result.evidence_bundle.facts
                else "insufficient"
            ),
        })
        logger.warning(
            "[retrieve_evidence] spatial evidence graph unavailable: %s",
            exc,
        )
    packet = result.evidence_packet
    if (
        packet is not None
        and request.request_type == "spatial_lookup"
        and not packet.candidate_refs
        and not packet.relation_evidence
    ):
        if packet.candidate_total > 0 and request.candidate_offset >= packet.candidate_total:
            reason = "candidate page offset is outside the returned evidence range"
            missing_code = "candidate_offset_out_of_range"
        else:
            reason = "no Bundle-backed spatial candidate was resolved for this query"
            missing_code = "spatial_candidates_unresolved"
        final_status = "partial" if result.evidence_bundle.facts else "insufficient"
        packet_trace = [
            {
                **trace,
                "status": "insufficient_geometry",
                "reason": reason,
            }
            if isinstance(trace, dict) and trace.get("step") == "sufficiency"
            else trace
            for trace in packet.query_trace
        ]
        packet_trace.append({
            "step": "spatial_result_status",
            "status": final_status,
            "reason": reason,
            "missing_code": missing_code,
            "candidate_total": packet.candidate_total,
            "candidate_offset": packet.candidate_offset,
        })
        result.evidence_packet = packet.model_copy(update={
            "sufficiency": final_status,
            "missing_evidence": list(dict.fromkeys([
                *packet.missing_evidence,
                missing_code,
            ]))[:12],
            "query_trace": packet_trace[-24:],
        })
    result = result.model_copy(update={
        "evidence_bundle": apply_fact_quality(result.evidence_bundle),
    })
    coverage_decision = evaluate_sufficiency(request, result)
    result = result.model_copy(update={
        "coverage": build_evidence_coverage(
            request,
            result,
            coverage_decision,
            source_families_queried=tuple(item.value for item in plan.retrievers),
            query_trace=tuple(
                trace
                for trace in [*retrieval_status, *external_trace]
                if isinstance(trace, dict)
            ),
            source_scope="project_wide" if project_wide_query else "scoped",
        ),
    })
    _EVIDENCE_CACHE[cache_key] = result
    _EVIDENCE_CACHE.move_to_end(cache_key)
    try:
        from app.core.settings import EVIDENCE_CACHE_MAXSIZE

        while len(_EVIDENCE_CACHE) > max(1, EVIDENCE_CACHE_MAXSIZE):
            _EVIDENCE_CACHE.popitem(last=False)
    except Exception:
        while len(_EVIDENCE_CACHE) > 128:
            _EVIDENCE_CACHE.popitem(last=False)
    return result


async def retrieve_dimension_context(
    dimension_key: str,
    config: Any,
    state: Mapping[str, Any],
    *,
    trace_sink: dict[str, Any] | None = None,
    excluded_fact_refs: Iterable[str] | None = None,
) -> tuple[str, Any | None]:
    """Return the bounded evidence projection for one stage dimension."""

    from app.infrastructure.evidence_runtime.dimension_runtime import run_rag

    return await run_rag(
        dimension_key,
        config,
        dict(state),
        trace_sink=trace_sink,
        excluded_fact_refs=excluded_fact_refs,
    )


async def retrieve_targeted_evidence(
    dimension_key: str,
    config: Any,
    state: Mapping[str, Any],
    *,
    query: str,
    required_facts: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Run a bounded evidence follow-up through the same facade."""

    from app.infrastructure.evidence_runtime.dimension_runtime import (
        run_targeted_evidence,
    )

    return await run_targeted_evidence(
        dimension_key,
        config,
        dict(state),
        query=query,
        required_facts=required_facts,
    )


def render_evidence_prompt_section(
    bundle: EvidenceBundle,
    cognition: SpatialCognitionEvidence | None = None,
    packet: EvidencePacket | None = None,
    coverage: EvidenceCoverage | None = None,
    *,
    allowed_l1_fact_ids: set[str] | frozenset[str] | None = None,
) -> str:
    """Render an ExplorationResult as a unified markdown prompt section.

    Replaces the old _optimize_semantics + _build_explore_brief output.
    """
    lines = [
        "## EXPLORE 证据",
        "**证据使用规则**:",
        "- report/L1-L2-L3 正文、专业 RAG 和外源文本只提供规划背景或待核实线索，不产生空间位置。",
        "- typed L1 spatial fact 只提供语义到地点的可审计绑定；KG 提供实体身份与拓扑；bundle feature ref 才是权威几何入口。",
        "- 只能使用下方已经返回的候选和 opaque bundle ref；禁止从名称、数量、道路宽度或报告文字自行生成 BSM、坐标、WKT、地块或关系。",
    "- ambiguity=multiple 或 unresolved 时不得写成唯一选址；必须保留候选/缺口并把定位交给 GROUND。",
    ]

    def _lineage_ref_allowed(value: object) -> bool:
        ref = str(value or "").strip()
        return (
            not ref.startswith("l1:fact:")
            or allowed_l1_fact_ids is None
            or ref in allowed_l1_fact_ids
        )

    if coverage is not None:
        lines.append("")
        lines.append(
            f"**证据覆盖**: stop_reason={coverage.stop_reason}; "
            f"sufficient={str(coverage.sufficient).lower()}; "
            f"source_scope={coverage.source_scope}"
        )
        if coverage.unresolved_requirements:
            lines.append(
                "- 未解决 requirement IDs："
                + "、".join(coverage.unresolved_requirements[:12])
            )
        for item in coverage.requirement_coverage[:12]:
            lines.append(
                f"- requirement={item.requirement_id}; status={item.status}; "
                f"locator_complete={str(item.locators_complete).lower()}"
            )

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

    planning_background = [
        fact for fact in bundle.facts
        if fact.evidence_role == "planning_background"
        or fact.fields.get("evidence_role") == "planning_background"
        or fact.fact_type in {"professional_text", "planning_text", "rag_context"}
    ]
    parcel_facts = [
        fact
        for fact in bundle.facts
        if fact.fact_type == "bundle_parcel_identity"
    ]
    spatial_facts = [
        fact
        for fact in bundle.facts
        if fact not in planning_background and fact not in parcel_facts
    ]
    if planning_background:
        lines.append("")
        lines.append("**规划语义背景（仅辅助决策，不产生空间位置）**:")
        for fact in planning_background[:8]:
            source_kind = fact.source_kind or fact.fields.get("source_kind", "")
            source_ref = next(
                (
                    str(ref).strip()
                    for ref in (fact.source_refs or [])
                    if _lineage_ref_allowed(ref)
                ),
                "",
            )
            label = f"来源={source_kind}" if source_kind else "来源=未标注"
            label += f"; 作用={fact.evidence_role or fact.fields.get('evidence_role', 'planning_background')}"
            label += f"; 空间粒度={fact.spatial_granularity}"
            if source_ref:
                label += f"; ref={source_ref}"
            lines.append(f"- [{label}] {fact.statement}")
        if len(planning_background) > 8:
            lines.append(
                f"- 背景证据共 {len(planning_background)} 条，本次显示 8 条；"
                "未显示内容仍受同一检索结果约束，不能据此推断未显示事实不存在。"
            )
    if parcel_facts:
        lines.append("")
        lines.append(
            "**规划候选地块（Bundle 源地块，可在 SELECT 按目标面积生成子几何）**:"
        )
        for fact in parcel_facts[:12]:
            spatial_refs = list(dict.fromkeys(
                str(value).strip()
                for value in fact.spatial_refs
                if str(value or "").strip()
            ))[:2]
            source_area = str(fact.fields.get("source_area_ha") or "").strip()
            area_label = f"; 源面积={source_area}ha" if source_area else ""
            ref_label = f"; bundle_ref={spatial_refs[0]}" if spatial_refs else ""
            lines.append(
                f"- [来源=bundle; 作用=location_binding; 空间粒度=feature; "
                f"规划用途=candidate_site{area_label}{ref_label}] {fact.statement}"
            )
        if len(parcel_facts) > 12:
            lines.append(
                f"- 规划候选地块证据共 {len(parcel_facts)} 条，本次显示 12 条；"
                "其余地块仍需通过候选分页或同一 Bundle ref 继续读取。"
            )
    if spatial_facts:
        lines.append("")
        lines.append("**空间事实与定位依据**:")
        for fact in spatial_facts[:12]:
            source_kind = fact.source_kind or fact.fields.get("source_kind", "")
            label = f"来源={source_kind}; " if source_kind else ""
            role = fact.evidence_role or fact.fields.get("evidence_role", "unclassified")
            spatial_refs = list(dict.fromkeys(
                str(value).strip()
                for value in fact.spatial_refs
                if str(value or "").strip()
            ))[:4]
            ref_label = f"; spatial_ref={'、'.join(spatial_refs)}" if spatial_refs else ""
            lines.append(
                f"- [{label}作用={role}; 空间粒度={fact.spatial_granularity}; "
                f"规划用途={fact.planning_use}{ref_label}] {fact.statement}"
            )
        if len(spatial_facts) > 12:
            lines.append(
                f"- 空间事实共 {len(spatial_facts)} 条，本次显示 12 条；"
                "候选身份和几何仍只能使用下方 Bundle/EvidenceGraph ref。"
            )

    if packet is not None:
        lines.append("")
        lines.append("**EvidenceGraph 空间候选与拓扑（可用于定位/约束，不直接提供执行几何）**:")
        candidate_start = packet.candidate_offset
        candidate_returned = len(packet.candidate_refs)
        candidate_end = candidate_start + candidate_returned
        candidate_range = (
            f"{candidate_start + 1}-{candidate_end}"
            if candidate_returned
            else "空页"
        )
        has_unseen_candidates = (
            packet.next_candidate_offset is not None
            or candidate_end < packet.candidate_total
        )
        display_ambiguity = packet.ambiguity_status
        if has_unseen_candidates:
            display_ambiguity = "multiple" if candidate_returned else "unresolved"
        lines.append(
            f"- 状态：sufficiency={packet.sufficiency}; ambiguity={display_ambiguity}; "
            f"candidate_count={candidate_returned}; "
            f"candidate_total={packet.candidate_total}; "
            f"candidate_range={candidate_range}; "
            f"candidate_offset={candidate_start}; "
            f"candidate_limit={packet.candidate_limit}; "
            f"candidates_truncated={packet.candidates_truncated}; "
            f"relation_count={len(packet.relation_evidence)}"
        )
        if packet.next_candidate_offset is not None:
            lines.append(
                "- 候选分页：当前页不是完整候选集，"
                f"has_more=true; next_candidate_offset={packet.next_candidate_offset}。"
            )
            lines.append(
                "- 分页动作：必须继续调用 query_evidence_graph 或 "
                "query_facility_bsms，并传入上述 next_candidate_offset 和相同的 "
                f"candidate_limit，直到 next_candidate_offset=null；不得把当前页写成唯一结果。"
            )
        elif candidate_end < packet.candidate_total:
            lines.append(
                "- 候选分页：当前页没有覆盖全部候选，但没有可用的下一页，"
                "has_more=false；这是证据缺口，不得把当前页写成唯一结果。"
            )
        else:
            lines.append(
                "- 候选分页：当前页已覆盖检索返回的全部候选，"
                "has_more=false; next_candidate_offset=null。"
            )
        if packet.missing_evidence:
            lines.append(
                "- 未闭合证据：" + "；".join(packet.missing_evidence[:6])
            )
        candidate_status_lines = []
        for trace in packet.query_trace:
            if not isinstance(trace, dict):
                continue
            if trace.get("step") != "candidate_generation_status":
                continue
            statuses = ",".join(
                str(value).strip()
                for value in (trace.get("statuses") or [])
                if str(value).strip()
            )
            reasons = "；".join(
                str(value).strip()
                for value in (trace.get("reasons") or [])
                if str(value).strip()
            )
            candidate_status_lines.append(
                f"statuses={statuses or 'unknown'}"
                + (f"; reasons={reasons}" if reasons else "")
            )
        if candidate_status_lines:
            lines.append(
                "- 候选生成诊断（不等于候选为空）："
                + "；".join(candidate_status_lines[-4:])
            )
        diagnostic_lines = []
        for trace in packet.query_trace:
            if not isinstance(trace, dict):
                continue
            if trace.get("step") not in {
                "retriever",
                "context_hydration",
                "evidence_graph_prefetch",
                "rag_source",
                "source_semantic_runtime",
                "source_semantic_overlay",
                "external_rag",
                "external_policy",
                "external_exception",
            }:
                continue
            status = str(trace.get("status") or "")
            diagnostics = trace.get("diagnostics") or []
            codes = [
                str(item.get("code") or "")
                for item in diagnostics
                if isinstance(item, dict) and item.get("code")
            ]
            detail = f"{trace.get('step')}={status}"
            if codes:
                detail += f"({','.join(codes[:4])})"
            error = str(trace.get("error") or trace.get("reason") or "").strip()
            failure = trace.get("failure")
            if isinstance(failure, dict):
                failure_code = str(failure.get("code") or "").strip()
                failure_message = str(failure.get("message") or "").strip()
                if failure_code:
                    detail += f"[{failure_code}]"
                if failure_message and not error:
                    error = failure_message
            if error:
                detail += f":{error[:180]}"
            diagnostic_lines.append(detail)
        if diagnostic_lines:
            lines.append("- 运行诊断：" + "；".join(diagnostic_lines[-6:]))
        if packet.candidate_refs:
            for ref in packet.candidate_refs:
                identity = ref.identity
                descriptor = " / ".join(
                    value
                    for value in (
                        str(identity.canonical_name or "").strip(),
                        str(identity.entity_type or identity.role or "").strip(),
                    )
                    if value
                ) or "未命名要素"
                aliases = list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in (identity.aliases or [])
                        if str(value).strip()
                    )
                )[:8]
                relation_refs = list(
                    dict.fromkeys(
                        str(value).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                        for value in (ref.relation_refs or [])
                        if str(value).strip()
                    )
                )[:8]
                related_parcels = list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in (ref.related_parcel_bsms or [])
                        if str(value).strip()
                    )
                )[:12]
                # Only canonical durable L1 fact identities belong in the
                # L1_facts label.  Packet lineage may also contain report,
                # source-feature, or legacy display refs; exposing those next
                # to a selectable-looking label lets a planning model mistake
                # provenance for source_fact_refs.
                l1_refs = list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in (ref.l1_fact_refs or [])
                        if (
                            str(value).strip().startswith("l1:fact:")
                            and (
                                allowed_l1_fact_ids is None
                                or str(value).strip() in allowed_l1_fact_ids
                            )
                        )
                    )
                )[:8]
                provenance_refs = list(
                    dict.fromkeys(
                        str(value).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                        for value in (ref.provenance_refs or [])
                        if str(value).strip()
                    )
                )[:8]
                lines.append(
                    f"- [来源=bundle; 作用=location_binding; 空间粒度=feature; "
                    f"role={identity.role or identity.entity_type or 'unknown'}; "
                    f"source_layer={identity.source_layer or 'unknown'}; "
                    f"geometry_authority={ref.geometry_authority}] {descriptor}; "
                    f"aliases={'、'.join(aliases) or 'none'}; "
                    f"feature_BSM={identity.bundle_feature_bsm}; "
                    f"source_BSM={identity.source_bsm or 'none'}; "
                    f"related_parcels={','.join(related_parcels) or 'none'}; "
                    f"bundle_ref={ref.geometry_ref or 'none'}; "
                    f"KG_relations={','.join(relation_refs) or 'none'}; "
                    f"L1_facts={','.join(l1_refs) or 'none'} "
                    "(lineage-only; not selectable source_fact_refs); "
                    f"provenance={','.join(provenance_refs) or 'none'}; "
                    f"source_authority={float(ref.source_authority_score or 0.0):.4f}; "
                    f"semantic_match={float(ref.semantic_match_score or 0.0):.4f}; "
                    f"spatial_support={float(ref.spatial_support_score or 0.0):.4f}; "
                    f"retrieval_score={float(ref.retrieval_score or 0.0):.4f}; "
                    f"selection_confidence={ref.selection_confidence if ref.selection_confidence is not None else 'unselected'}"
                )
        if packet.relation_evidence:
            for relation in packet.relation_evidence[:8]:
                subject = relation.subject.identity.bundle_feature_bsm
                object_ref = relation.object.identity.bundle_feature_bsm
                metric = ""
                if relation.metric_value is not None:
                    metric = f"; metric={relation.metric_value}{relation.metric_unit or ''}"
                lines.append(
                    f"- [来源=kg; 作用=spatial_topology; 空间粒度=relation] "
                    f"{subject} --{relation.predicate}--> {object_ref}{metric}"
                )
        lines.append(
            f"- [来源=graph_metadata; 作用=provenance; 空间粒度=scope] "
            f"bundle_snapshot={packet.bundle_snapshot_digest or 'unavailable'}; "
            f"kg_version={packet.kg_version or 'unavailable'}; "
            f"l1_snapshot={packet.l1_snapshot_ref or 'unavailable'}"
        )

    if bundle.sources:
        source_groups: dict[tuple[str, str, str], list[EvidenceSource]] = {}
        for source in bundle.sources:
            key = (
                str(source.source_type or "未标注"),
                str(source.evidence_role or "unclassified"),
                str(source.authority or "unclassified"),
            )
            source_groups.setdefault(key, []).append(source)
        source_summaries: list[str] = []
        for (source_type, evidence_role, authority), sources in source_groups.items():
            references = ",".join(
                str(source.reference or "未提供")
                for source in sources[:4]
                if _lineage_ref_allowed(source.reference)
            ) or "未提供"
            if len(sources) > 4:
                references += f",…共{len(sources)}条"
            supports = list(dict.fromkeys(
                support
                for source in sources
                for support in (source.supports or [])
                if str(support).strip()
            ))[:4]
            source_summaries.append(
                f"{source_type}[作用={evidence_role};权威={authority};"
                f"数量={len(sources)};支持={','.join(supports) or '未声明'};"
                f"代表引用={references}]"
            )
        lines.append("**证据来源覆盖**: " + "；".join(source_summaries))

    if bundle.unresolved:
        lines.append("**待查问题**: " + "; ".join(bundle.unresolved[:3]))

    if bundle.conflicts:
        lines.append("**证据关系审计（不得混算）**:")
        for conflict in bundle.conflicts[:8]:
            refs = "、".join(conflict.fact_refs[:2])
            lines.append(f"- [{conflict.relation}] {conflict.reason}; refs={refs}")

    return "\n".join(lines)


def _gate_request_from_pending(
    pending_request: Any,
    *,
    session_id: str,
    stage: str,
) -> ExplorationRequest:
    """Convert a gate-owned pending request without adding retrieval policy."""

    if isinstance(pending_request, dict):
        ctx = pending_request.get("context") or {}
        required_fact = ctx.get("required_fact")
        required_facts = (
            required_fact
            if isinstance(required_fact, list)
            else [required_fact]
            if required_fact
            else []
        )
        return ExplorationRequest(
            run_id=session_id,
            request_type=pending_request.get("request_type", "evidence_gap"),
            query=(
                ctx.get("message")
                or ctx.get("reason")
                or "; ".join(str(item) for item in required_facts)
            ),
            context_refs=list(ctx.get("source_refs") or ctx.get("source_input_refs") or []),
            evidence_gaps_to_resolve=list(ctx.get("gaps") or ([ctx["gap_id"]] if ctx.get("gap_id") else [])),
            dimension_key=(
                ctx.get("retrieval_dimension")
                or ctx.get("producer_dimension")
                or ctx.get("dimension", "")
            ),
            stage=stage,
            query_purpose="gap_resolution",
            questions=list(ctx.get("questions") or []),
            required_facts=required_facts,
            entity_scope=list(ctx.get("entity_scope") or []),
        )

    ctx = getattr(pending_request, "context", {}) or {}
    return ExplorationRequest(
        run_id=session_id,
        request_type=getattr(pending_request, "request_type", "evidence_gap"),
        query=(
            ctx.get("message")
            or ctx.get("reason")
            or "; ".join(str(item) for item in (ctx.get("required_facts") or []))
        ),
        context_refs=list(ctx.get("source_refs") or ctx.get("source_input_refs") or []),
        evidence_gaps_to_resolve=list(
            ctx.get("gaps") or ([ctx["gap_id"]] if ctx.get("gap_id") else [])
        ),
        dimension_key=(
            ctx.get("retrieval_dimension")
            or ctx.get("producer_dimension")
            or ctx.get("dimension", "")
        ),
        stage=stage,
        query_purpose="gap_resolution",
        questions=list(ctx.get("questions") or []),
        required_facts=list(ctx.get("required_facts") or []),
        entity_scope=list(ctx.get("entity_scope") or []),
    )


def _gate_unresolved_statements(result: ExplorationResult) -> list[str]:
    """Return only requirement statements that can become follow-up queries."""

    coverage = result.coverage
    statements: list[str] = []
    if coverage is not None:
        requirements_by_id = {
            item.requirement_id: item.statement
            for item in coverage.requirements
        }
        statements.extend(
            requirements_by_id[item]
            for item in coverage.unresolved_requirements
            if item in requirements_by_id and str(requirements_by_id[item]).strip()
        )
    # Older/custom retrievers may not return coverage yet.  Packet missing
    # evidence remains a diagnostic fallback, but opaque error codes are not
    # promoted into natural-language subqueries.
    if not statements and result.evidence_packet is not None:
        statements.extend(
            str(item).strip()
            for item in result.evidence_packet.missing_evidence
            if str(item).strip() and ":" not in str(item)
        )
    if not statements:
        statements.extend(
            str(item).strip()
            for item in result.evidence_bundle.unresolved
            if str(item).strip() and ":" not in str(item)
        )
    return list(dict.fromkeys(statements))


def _append_gate_trace(
    result: ExplorationResult,
    trace: dict[str, Any],
) -> ExplorationResult:
    """Attach orchestration evidence to both packet and coverage traces."""

    packet = result.evidence_packet
    if packet is not None:
        packet = packet.model_copy(update={
            "query_trace": [*packet.query_trace, trace][-24:],
        })
    coverage = result.coverage
    if coverage is not None:
        coverage = coverage.model_copy(update={
            "query_trace": [*coverage.query_trace, trace][-24:],
        })
    return result.model_copy(update={
        "evidence_packet": packet,
        "coverage": coverage,
    })


def _gate_request_key(request: ExplorationRequest) -> str:
    """Stable key used to prevent a gap loop from repeating one subquery."""

    return request_fingerprint(request)


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
    import os

    external_port = None
    external_provider_owned = False
    external_enabled = str(
        os.getenv("EVIDENCE_EXTERNAL_FOR_LLM", "false")
    ).strip().lower() in {"1", "true", "yes", "on"}
    if external_enabled:
        try:
            from app.infrastructure.search.provider_registry import (
                get_active_external_provider,
                get_configured_external_provider,
            )

            external_port = get_active_external_provider()
            if external_port is None:
                external_port = get_configured_external_provider()
                external_provider_owned = True
        except Exception as exc:  # noqa: BLE001 - explicit opt-in remains typed
            logger.warning(
                "[retrieve_evidence_for_gate] external provider setup failed: %s",
                exc,
            )
            from app.infrastructure.search import UnavailableExternalSearchAdapter

            external_port = UnavailableExternalSearchAdapter()
            external_provider_owned = True

    queue: list[tuple[ExplorationRequest, int]] = [
        (
            _gate_request_from_pending(
                item,
                session_id=session_id,
                stage=gate_decision.get("stage", ""),
            ),
            0,
        )
        for item in pending
    ]
    queued_keys = {_gate_request_key(request) for request, _ in queue}
    queue_index = 0

    try:
        while queue_index < len(queue) and len(results) < _GATE_GAP_MAX_REQUESTS:
            request, depth = queue[queue_index]
            queue_index += 1
            try:
                external_policy = None
                if external_port is not None:
                    from app.infrastructure.evidence_runtime.context_hydration import build_external_evidence_policy

                    external_policy = build_external_evidence_policy(
                        request.dimension_key
                    )
                result = await retrieve_evidence(
                    request,
                    session_id,
                    village_name,
                    external_port=external_port,
                    external_policy=external_policy,
                )
                unresolved = _gate_unresolved_statements(result)
                coverage_stop = (
                    str(result.coverage.stop_reason)
                    if result.coverage is not None
                    else ""
                )
                trace: dict[str, Any] = {
                    "step": "evidence_gap_loop",
                    "attempt": len(results) + 1,
                    "depth": depth,
                    "request": request.query,
                }
                if unresolved and coverage_stop not in {"budget_exhausted", "human_required"}:
                    follow_up = request.model_copy(update={
                        "request_type": "evidence_gap",
                        "query": "；".join(unresolved),
                        "query_purpose": "gap_resolution",
                        "questions": [],
                        "required_facts": unresolved,
                        "evidence_gaps_to_resolve": unresolved,
                        "requirements": [],
                    })
                    follow_up_key = _gate_request_key(follow_up)
                    if depth < _GATE_GAP_MAX_DEPTH and follow_up_key not in queued_keys:
                        queued_keys.add(follow_up_key)
                        queue.append((follow_up, depth + 1))
                        trace.update({
                            "status": "follow_up_requested",
                            "missing_subqueries": unresolved,
                        })
                    elif depth >= _GATE_GAP_MAX_DEPTH:
                        trace.update({
                            "status": "stopped",
                            "reason": "bounded_depth",
                            "missing_subqueries": unresolved,
                        })
                    else:
                        trace.update({
                            "status": "stopped",
                            "reason": "repeated_request",
                            "missing_subqueries": unresolved,
                        })
                elif unresolved:
                    trace.update({
                        "status": "stopped",
                        "reason": coverage_stop or "terminal_coverage",
                        "missing_subqueries": unresolved,
                    })
                else:
                    trace.update({"status": "sufficient"})
                result = _append_gate_trace(result, trace)
                results.append(result)
            except Exception as e:
                logger.warning("[retrieve_evidence_for_gate] failed for %s: %s", request.request_type, e)
    finally:
        if external_provider_owned and external_port is not None:
            close = getattr(external_port, "close", None)
            if callable(close):
                try:
                    outcome = close()
                    if hasattr(outcome, "__await__"):
                        await outcome
                except Exception as exc:  # noqa: BLE001 - cleanup is best effort
                    logger.warning(
                        "[retrieve_evidence_for_gate] external provider cleanup failed: %s",
                        exc,
                    )

    if results and queue_index < len(queue):
        # Keep the request budget observable when multiple pending requests or
        # chained gaps exceed the gate-level cap.
        results[-1] = _append_gate_trace(results[-1], {
            "step": "evidence_gap_loop",
            "status": "stopped",
            "reason": "request_budget",
            "max_requests": _GATE_GAP_MAX_REQUESTS,
            "remaining_requests": len(queue) - queue_index,
        })

    if results:
        _GATE_EVIDENCE_CACHE.setdefault(session_id, []).extend(results)
        # Keep only the latest bounded gate evidence to avoid prompt growth on
        # repeated retries.  The cache key of the canonical request still
        # includes all request fields and active artifact versions.
        _GATE_EVIDENCE_CACHE[session_id] = _GATE_EVIDENCE_CACHE[session_id][-8:]
    return results


def clear_session_evidence_cache(session_id: str) -> None:
    """Release cached evidence and gate results when a session is deleted."""
    if not session_id:
        return
    stale = [key for key in _EVIDENCE_CACHE if key and key[0] == session_id]
    for key in stale:
        _EVIDENCE_CACHE.pop(key, None)
    _GATE_EVIDENCE_CACHE.pop(session_id, None)
    try:
        from app.infrastructure.evidence_runtime.retrievers.rag_retriever import clear_rag_logs

        clear_rag_logs(session_id)
    except Exception:
        pass


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
    "retrieve_dimension_context",
    "retrieve_targeted_evidence",
    "render_evidence_prompt_section",
    "retrieve_evidence_for_gate",
    "retrieve_evidence_for_gate_sync",
    "gate_evidence_digest",
    "clear_session_evidence_cache",
]
