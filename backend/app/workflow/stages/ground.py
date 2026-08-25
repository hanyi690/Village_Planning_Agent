"""GROUND stage service: resolve projected spatial references to evidence."""

from __future__ import annotations

import os
import asyncio
from typing import Any, Dict, Optional

from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import persist_stage_artifact
from app.workflow.stages.support import (
    _adopt_context,
    _load_ref_artifact,
    _require_context,
    _retry_patch,
    stage_completion_patch,
)

logger = get_logger(__name__)


def _ground_llm_disabled() -> bool:
    return str(os.getenv("GROUND_LLM_ENABLED", "false")).strip().lower() not in {
        "1", "true", "yes", "on"
    } or any(
        str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}
        for name in ("DISABLE_GROUND_LLM", "DISABLE_GROUND_REPORT_LLM")
    )


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


def _ground_packet_query(context: Any, spec: Any) -> tuple[str, list[str]]:
    labels: list[str] = []
    semantic_terms: list[str] = []
    requested_scopes: list[str] = []
    kinds: set[str] = set()

    def collect(node: Any) -> None:
        reference = getattr(node, "reference", None)
        if reference is not None:
            filters = getattr(reference, "filter", None) or {}
            label = str(
                filters.get("label_contains")
                or getattr(reference, "name", "")
                or ""
            ).strip()
            if label and label not in {"全村", "全村域", "村域"}:
                labels.append(label)
            kind = str(getattr(reference, "kind", "") or "").strip()
            if kind:
                kinds.add(kind)
        for value in getattr(node, "semantic_terms", None) or []:
            term = str(value or "").strip()
            if term:
                semantic_terms.append(term)
        for value in getattr(node, "retrieval_scopes", None) or []:
            scope = str(value or "").strip().casefold()
            if scope:
                requested_scopes.append(scope)
        for child in getattr(node, "children", None) or []:
            collect(child)

    collect(spec)
    labels = list(dict.fromkeys(labels))
    semantic_terms = list(dict.fromkeys(semantic_terms))
    query_terms = list(dict.fromkeys([*labels, *semantic_terms]))
    if not query_terms:
        return "", []
    village = str(getattr(context, "village_name", "") or "").strip()
    query = " ".join(value for value in (village, *query_terms) if value)
    scopes_by_kind = {
        "entity_type": ["facilities", "roads", "waters", "parcels"],
        "layer_group": ["facilities", "roads", "waters", "parcels"],
        "place_name": ["facilities", "roads", "waters", "parcels"],
        "bsm": ["parcels", "facilities", "roads", "waters"],
        # A natural village may have no standalone polygon/name feature.  In
        # that case address-bearing hazard/facility points are legitimate
        # spatial anchors whose related Bundle parcels can seed a coarse
        # village scope.  Retrieval keeps all of them; GROUND marks the result
        # inferred rather than pretending the point is a village boundary.
        "village": ["parcels", "hazards", "facilities", "annotations"],
    }
    scopes: list[str] = list(requested_scopes)
    for kind in kinds:
        scopes.extend(scopes_by_kind.get(
            kind.casefold(),
            ["facilities", "roads", "waters", "parcels"],
        ))
    return query, list(dict.fromkeys(scopes or [
        "facilities", "hazards", "roads", "waters", "parcels", "zones",
    ]))


def _packet_ref_key(ref: Any) -> str:
    identity = getattr(ref, "identity", None)
    return str(
        getattr(identity, "bundle_feature_bsm", "")
        or getattr(identity, "source_feature_id", "")
        or getattr(ref, "geometry_ref", "")
        or "|".join(getattr(ref, "entity_refs", None) or [])
    ).strip()


def _merge_ground_evidence_packets(packets: list[Any], *, next_offset: int | None = None) -> Any:
    """Merge retrieval pages without dropping semantic or topology evidence."""
    if not packets:
        return None
    first = packets[0]
    candidates: list[Any] = []
    seen_candidates: set[str] = set()
    relations: list[Any] = []
    seen_relations: set[str] = set()
    source_spans: list[str] = []
    external_refs: list[str] = []
    l1_scope_refs: list[str] = []
    missing_evidence: list[str] = []
    query_trace: list[dict[str, Any]] = []

    def append_unique(values: list[Any], incoming: Any) -> None:
        for value in incoming or []:
            text = str(value).strip()
            if text and text not in values:
                values.append(text)

    for packet in packets:
        for ref in list(getattr(packet, "candidate_refs", None) or []):
            key = _packet_ref_key(ref)
            if key and key not in seen_candidates:
                seen_candidates.add(key)
                candidates.append(ref)
        for relation in list(getattr(packet, "relation_evidence", None) or []):
            key = str(getattr(relation, "relation_id", "") or "").strip()
            if key and key not in seen_relations:
                seen_relations.add(key)
                relations.append(relation)
        append_unique(source_spans, getattr(packet, "source_spans", None))
        append_unique(external_refs, getattr(packet, "external_refs", None))
        append_unique(l1_scope_refs, getattr(packet, "l1_scope_refs", None))
        append_unique(missing_evidence, getattr(packet, "missing_evidence", None))
        query_trace.extend(list(getattr(packet, "query_trace", None) or []))

    candidate_total = max(
        len(candidates),
        *(int(getattr(packet, "candidate_total", 0) or 0) for packet in packets),
    )
    complete = next_offset is None
    sufficiency_rank = {"insufficient": 0, "partial": 1, "sufficient": 2}
    sufficiency = min(
        (str(getattr(packet, "sufficiency", "insufficient") or "insufficient")
         for packet in packets),
        key=lambda value: sufficiency_rank.get(value, 0),
    )
    if len(candidates) > 1:
        ambiguity_status = "multiple"
    elif candidates and complete and sufficiency != "insufficient":
        ambiguity_status = "resolved"
    else:
        ambiguity_status = str(
            getattr(first, "ambiguity_status", "unresolved") or "unresolved"
        )
    return first.model_copy(
        update={
            "candidate_refs": candidates,
            "candidate_total": candidate_total,
            "candidate_offset": 0,
            "candidate_limit": max(
                int(getattr(packet, "candidate_limit", 12) or 12)
                for packet in packets
            ),
            "candidates_truncated": not complete,
            "next_candidate_offset": next_offset,
            "relation_evidence": relations,
            "source_spans": source_spans,
            "external_refs": external_refs,
            "l1_scope_refs": l1_scope_refs,
            "ambiguity_status": ambiguity_status,
            "sufficiency": sufficiency,
            "missing_evidence": missing_evidence,
            "query_trace": query_trace,
        }
    )


async def _retrieve_ground_evidence_packets(
    context: Any,
    specs: list[Any],
    requirements_by_target: dict[str, list[Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Fetch bounded packets and retain every retrieval error.

    The packet is a bounded EvidenceGraph view. The resolver remains the
    single grounding authority when a packet is absent; absence is recorded
    so a provider or graph error cannot disappear as an empty candidate set.
    """
    session_id = str(getattr(context, "session_id", "") or "").strip()
    if not session_id or getattr(context, "evidence_graph", None) is None:
        return {}, []
    from app.contracts.evidence.evidence_contracts import ExplorationRequest
    from app.evidence.retrieval.evidence_service import retrieve_evidence

    work: list[tuple[str, Any, str, list[str]]] = []
    for spec in list(specs or []):
        target_id = str(getattr(spec, "target_id", "") or "").strip()
        query, scopes = _ground_packet_query(context, spec)
        if target_id and query:
            work.append((target_id, spec, query, scopes))
    if not work:
        return {}, []

    semaphore = asyncio.Semaphore(4)

    async def retrieve_one(target_id: str, _spec: Any, query: str, scopes: list[str]):
        async with semaphore:
            packets: list[Any] = []
            offset = 0
            seen_offsets: set[int] = set()
            try:
                while True:
                    if offset in seen_offsets:
                        return target_id, _merge_ground_evidence_packets(
                            packets, next_offset=offset
                        ), {
                            "target_id": target_id,
                            "status": "failed",
                            "error": "candidate_pagination_repeated_offset",
                        }
                    seen_offsets.add(offset)
                    result = await retrieve_evidence(
                        ExplorationRequest(
                            run_id=session_id,
                            request_type="spatial_lookup",
                            query=query,
                            stage="GROUND",
                            dimension_key="location",
                            query_purpose="gap_resolution",
                            entity_scope=scopes,
                            candidate_offset=offset,
                            candidate_limit=64,
                            requirements=list(
                                (requirements_by_target or {}).get(target_id, [])
                            ),
                        ),
                        session_id,
                        village_name=str(getattr(context, "village_name", "") or ""),
                        spatial_spec=_spec,
                        # GROUND's packet prefetch is local-only.  External text
                        # evidence remains an explicit EXPLORE decision.
                        external_port=None,
                    )
                    packet = getattr(result, "evidence_packet", None)
                    if packet is None:
                        if packets:
                            return target_id, _merge_ground_evidence_packets(
                                packets, next_offset=offset
                            ), {
                                "target_id": target_id,
                                "status": "failed",
                                "error": "candidate_pagination_page_unavailable",
                            }
                        break
                    packets.append(packet)
                    next_page = getattr(packet, "next_candidate_offset", None)
                    if next_page is None:
                        return target_id, _merge_ground_evidence_packets(packets), {}
                    offset = int(next_page)
                    if len(packets) >= 16:
                        return target_id, _merge_ground_evidence_packets(
                            packets, next_offset=offset
                        ), {
                            "target_id": target_id,
                            "status": "partial",
                            "error": "candidate_pagination_safety_limit",
                        }
            except Exception as exc:  # noqa: BLE001 - preserve typed retrieval audit
                logger.warning("[workflow:ground] packet prefetch failed: %s", exc)
                return target_id, _merge_ground_evidence_packets(
                    packets, next_offset=offset if packets else None
                ), {
                    "target_id": target_id,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
        if packets:
            return target_id, _merge_ground_evidence_packets(packets), {
                "target_id": target_id,
                "status": "empty",
                "error": "evidence_packet_has_no_candidate_refs",
            }
        return target_id, None, {
            "target_id": target_id,
            "status": "empty",
            "error": "evidence_packet_unavailable",
        }

    pairs = await asyncio.gather(*(retrieve_one(*item) for item in work))
    return (
        {
            target_id: packet
            for target_id, packet, _diagnostic in pairs
            if packet is not None
        },
        [diagnostic for _target_id, _packet, diagnostic in pairs if diagnostic],
    )


async def ground_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    from app.domain.ground.aggregate import ground_aggregate, retrieve_evidence
    from app.domain.ground.gate import evaluate_ground_gate
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.spatial.spatial_reference_contracts import SpatialReferenceSpec

    retry_patch = _retry_patch(state, "ground")
    context = await _require_context(state)
    from app.spatial.grounding.call_budget import get_ground_llm_budget

    ground_llm_budget = get_ground_llm_budget(
        context,
        scope_key=f"workflow:{state.get('session_id') or ''}",
    )
    compilation = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    report_result = None

    # L1 接地锚点显式消费（设计 §5.1）：grounded_anchors 是 L1 后接地推理产物，
    # 挂到 context 供 ground_aggregate 做实体级候选/证据（同名同坐标=同实体）。
    grounded_anchors = []
    try:
        if (state.get("artifact_refs") or {}).get("grounded_anchors"):
            from app.contracts.spatial.grounding_contracts import GroundedAnchor
            from app.infrastructure.artifacts.runtime import load_artifact

            payload = load_artifact(state, "grounded_anchors")
            if isinstance(payload, list):
                grounded_anchors = [
                    a if isinstance(a, GroundedAnchor) else GroundedAnchor(**a)
                    for a in payload if isinstance(a, dict)
                ]
        if grounded_anchors:
            context.grounded_anchors = grounded_anchors
            logger.info(
                "[workflow:ground] consuming %d L1 grounded anchors",
                len(grounded_anchors),
            )
    except Exception as exc:  # noqa: BLE001 - 锚点缺失不阻断 GROUND
        logger.warning("[workflow:ground] grounded anchors load failed: %s", exc)

    try:
        if (state.get("artifact_refs") or {}).get("l1_bindings"):
            from app.contracts.evidence.identity_contracts import GroundedEntityBindingSnapshot
            from app.infrastructure.artifacts.runtime import load_artifact

            binding_snapshot = load_artifact(
                state,
                "l1_bindings",
                GroundedEntityBindingSnapshot,
            )
            if binding_snapshot is not None:
                context.grounded_bindings = list(binding_snapshot.bindings)
                logger.info(
                    "[workflow:ground] consuming %d L1 entity bindings",
                    len(context.grounded_bindings),
                )
    except Exception as exc:  # noqa: BLE001 - binding absence must not block GROUND
        logger.warning("[workflow:ground] L1 binding load failed: %s", exc)

    # =====================================================================
    # The complete GROUND flow: Phase 1 - L1 spatial inventory from the
    # report (every place name + spatial cue + facility->village text +
    # external neighbor POIs); Phase 2 - matching against KG geometry
    # (collective village partition + per-role LLM evidence assignment).
    # Every report-named entity that has any KG geometry is located here;
    # the enriched gazetteer feeds EvidenceGraph used by spec
    # resolution below.  Nothing is ever fabricated; evidence-less names
    # stay explicitly unresolved.
    # =====================================================================
    try:
        from app.spatial.grounding.report_grounder import ground_report
        from app.spatial.grounding.report_grounder import create_grounding_llm

        facts = list(getattr(context, "location_facts", []) or [])
        disable_report_llm = _ground_llm_disabled()
        if (
            facts
            and getattr(context, "gazetteer", None) is not None
            and not disable_report_llm
        ):
            session_id = str(state.get("session_id", "") or "")
            report_result = await ground_report(
                context,
                facts,
                await _context_report_text_async(context),
                llm=create_grounding_llm(),
                session_id=session_id,
                budget=ground_llm_budget,
            )
            if report_result.grounded:
                from app.infrastructure.kg.adapters.gazetteer_adapter import KGGazetteerAdapter

                if getattr(context, "ports", None) is not None:
                    context.ports.gazetteer = KGGazetteerAdapter(context.gazetteer)
                logger.info("[workflow:ground] %s", report_result.summary())
            if getattr(report_result, "reviews", None):
                logger.info(
                    "[workflow:ground] %d low-confidence locations queued for human review",
                    len(report_result.reviews),
                )
    except Exception as exc:  # noqa: BLE001 - grounding must never break GROUND
        logger.warning("[workflow:ground] report grounding failed: %s", exc)
    projection_ref = (state.get("artifact_refs") or {}).get("target_projection")
    specs = [
        _to_typed(item, SpatialReferenceSpec)
        for item in (getattr(compilation, "spatial_reference_specs", None) or [])
    ]
    pending_grounding_specs = [
        _to_typed(item, SpatialReferenceSpec)
        for item in (getattr(compilation, "pending_grounding_specs", None) or [])
    ]
    # Pending spatial claims are not formal projection specs, but they are
    # typed GROUND work items.  Keep them separate for audit while executing
    # them through the same resolver/aggregate path exactly once.
    grounding_specs = [*specs, *pending_grounding_specs]

    # GROUND may derive additional anchors for its local grounding computation,
    # but TARGET_PROJECTION remains immutable.  Grounding facts belong in the
    # GroundingResult/GroundedPlanningProblem artifact, not in the L3 intent.
    try:
        from app.contracts.workflow.parse_contracts import SpatialPlanningIntent

        intent = _to_typed(
            getattr(compilation, "typed_intent", None) or compilation,
            SpatialPlanningIntent,
        )
        if intent is not None:
            from app.spatial.grounding.resolver import SpatialResolver

            resolver = SpatialResolver(
                context,
                ground_llm_budget=ground_llm_budget,
            )
            village_cluster_map = (
                {}
                if _ground_llm_disabled()
                else await _village_cluster_map_for_context(
                    context,
                    intent,
                    budget=ground_llm_budget,
                )
            )
            # Keep the evidence-constrained village -> Bundle cluster mapping
            # available to the spec resolver.  ``resolve_anchors`` mutates the
            # typed intent for downstream consumers, but TARGET_PROJECTION is
            # intentionally immutable and GROUND resolves the original specs;
            # without this context bridge the mapping would never affect the
            # actual spatial candidate search.
            context.village_cluster_map = dict(village_cluster_map or {})
            resolved_anchors = resolver.resolve_anchors(
                intent,
                village_cluster_map=village_cluster_map,
            )
            if resolved_anchors > 0:
                logger.info(
                    "[workflow:ground] local intent anchors resolved: %d entities; projection remains immutable",
                    resolved_anchors,
                )
    except Exception as exc:  # noqa: BLE001 - anchor enrichment must not break GROUND
        logger.warning("[workflow:ground] intent anchor resolution failed: %s", exc)
    evidence = []
    if retry_patch:
        prior_gate = state.get("ground_gate")
        requests = getattr(prior_gate, "evidence_requests", None)
        if requests is None and isinstance(prior_gate, dict):
            requests = prior_gate.get("evidence_requests")
        try:
            evidence = await retrieve_evidence(context, requests or None)
        except Exception as exc:
            logger.warning("[workflow:ground] retrieve_evidence failed: %s", exc)
    intent_graph = getattr(compilation, "intent_graph", None)
    target_metadata = _target_metadata_from_compilation(compilation, intent_graph)
    from app.evidence.retrieval.requirements import requirements_from_target_projection

    target_requirements = requirements_from_target_projection(compilation)
    requirements_by_target: dict[str, list[Any]] = {}
    for requirement in target_requirements:
        target_id = str(requirement.metadata.get("target_id", "") or "").strip()
        if target_id:
            requirements_by_target.setdefault(target_id, []).append(requirement)
    evidence_packets, packet_diagnostics = await _retrieve_ground_evidence_packets(
        context, grounding_specs, requirements_by_target
    )
    if evidence_packets:
        logger.info(
            "[workflow:ground] canonical evidence packets=%d",
            len(evidence_packets),
        )
    result = ground_aggregate(
        grounding_specs,
        context,
        intent_graph=intent_graph,
        target_metadata=target_metadata,
        evidence_packets=evidence_packets,
        ground_llm_budget=ground_llm_budget,
    )
    if packet_diagnostics:
        from app.contracts.spatial.grounding_contracts import SpatialQueryEvidence

        result.spatial_query_evidence.extend(
            SpatialQueryEvidence(
                query_type="evidence_packet_retrieval",
                query_params={
                    "status": diagnostic.get("status", "unknown"),
                    "error": diagnostic.get("error", ""),
                },
                result_count=0,
                result_refs=[],
                target_id=diagnostic.get("target_id", ""),
            )
            for diagnostic in packet_diagnostics
        )

    # GROUND flash-LLM mention enhancement: for specs that could not bind any
    # BSM, ask the flash model to segment the raw prose into concrete locatable
    # mentions, then re-resolve through the same EvidenceGraph.  The model
    # only supplies text; BSMs still come from the index/gazetteer/bundle.
    # Results are cached per content hash so resume/replay does not repeat the
    # call.  On any failure the deterministic result is kept unchanged.
    try:
        enhanced = (
            {}
            if _ground_llm_disabled()
            else await _flash_enhance_unresolved(
                compilation,
                result,
                state,
                budget=ground_llm_budget,
            )
        )
        if enhanced:
            re_result = ground_aggregate(
                grounding_specs,
                context,
                mention_enhancements=enhanced,
                intent_graph=intent_graph,
                target_metadata=target_metadata,
                evidence_packets=evidence_packets,
                ground_llm_budget=ground_llm_budget,
            )
            # Only adopt the enhanced result when it strictly reduces the
            # unresolved count; otherwise keep the deterministic baseline.
            if len(re_result.unresolved) < len(result.unresolved):
                result = re_result
    except Exception as exc:  # noqa: BLE001 - enhancement must never break GROUND
        logger.warning("[workflow:ground] flash mention enhancement failed: %s", exc)

    if evidence and hasattr(result, "spatial_query_evidence"):
        result.spatial_query_evidence.extend(evidence)
        refs = [ref for item in evidence for ref in item.result_refs if ref]
        if refs:
            for candidate in (getattr(result, "candidates", None) or []):
                if hasattr(candidate, "evidence_refs"):
                    candidate.evidence_refs.extend(refs)
    gate = evaluate_ground_gate(result, expected_spec_count=len(grounding_specs))
    candidate_domains = getattr(getattr(result, "problem", None), "candidate_domains", [])
    logger.info(
        "[workflow:ground] typed candidate domains=%d candidates=%d",
        len(candidate_domains or []),
        len(getattr(result, "candidates", None) or []),
    )
    logger.info(
        "[workflow:ground] llm_budget scope=%s reserved=%d completed=%d failed=%d remaining=%d",
        ground_llm_budget.get("scope_key", ""),
        int(ground_llm_budget.get("reserved", 0) or 0),
        int(ground_llm_budget.get("completed", 0) or 0),
        int(ground_llm_budget.get("failed", 0) or 0),
        int(ground_llm_budget.get("remaining", 0) or 0),
    )
    ref = persist_stage_artifact(state, "ground", "GroundingResult", result)
    output_refs = {"grounding_result": ref}
    task_graph = getattr(compilation, "planning_task_graph", None)
    if task_graph is not None:
        from app.domain.ground.task_graph_executor import execute_planning_task_graph

        executed_task_graph = execute_planning_task_graph(
            task_graph,
            grounded_problem=getattr(result, "problem", None),
            artifact_refs={
                **dict(state.get("artifact_refs") or {}),
                "grounding_result": ref,
            },
        )
        task_graph_state = dict(state)
        task_graph_state["artifact_refs"] = dict(state.get("artifact_refs") or {})
        task_graph_state["artifact_refs"]["grounding_result"] = ref
        task_graph_ref = persist_stage_artifact(
            task_graph_state,
            "ground",
            "PlanningTaskGraph",
            executed_task_graph,
        )
        output_refs["planning_task_graph"] = task_graph_ref
        logger.info(
            "[workflow:ground] executed planning tasks=%d statuses=%s",
            len(executed_task_graph.tasks),
            {
                status: sum(1 for task in executed_task_graph.tasks if task.status == status)
                for status in sorted({task.status for task in executed_task_graph.tasks})
            },
        )
    if projection_ref:
        output_refs["target_projection"] = projection_ref
    patch = stage_completion_patch(
        state,
        "ground",
        output_refs=output_refs,
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )
    if report_result is not None and getattr(report_result, "reviews", None):
        patch["ground_human_reviews"] = [
            {
                "name": r.name,
                "role": r.role,
                "recommended_bsms": list(r.recommended_bsms),
                "recommended_geometry_ref": r.recommended_geometry_ref,
                "confidence": r.confidence,
                "reason": r.reason,
                "status": r.status,
            }
            for r in report_result.reviews
        ]
    return patch


async def _flash_enhance_unresolved(
    compilation: Any,
    result: Any,
    state: Dict[str, Any],
    *,
    budget: Optional[Dict[str, Any]] = None,
) -> Dict[str, list[str]]:
    """Ask the flash LLM to segment raw prose for unresolved specs.

    Returns ``{target_id: [mention, ...]}`` or ``{}`` when there is nothing to
    enhance, the model is unavailable, or every call failed.  The mention
    cache is persisted under the session run directory so LangGraph replay /
    resume does not repeat flash calls for the same text.
    """
    if not getattr(result, "unresolved", None):
        return {}
    unresolved_target_ids = {
        str(getattr(issue, "related_artifact_id", "") or "")
        for issue in result.unresolved
    }
    unresolved_target_ids.discard("")
    if not unresolved_target_ids:
        return {}

    raw_by_target: Dict[str, str] = {}
    intent = getattr(compilation, "typed_intent", None) or {}
    if isinstance(intent, dict):
        target_lists = [
            intent.get("zone_targets") or [],
            intent.get("facilities") or [],
            intent.get("development_axes") or [],
            intent.get("road_targets") or [],
            intent.get("linear_targets") or [],
            intent.get("site_area_targets") or [],
        ]
    else:
        target_lists = [
            getattr(intent, "zone_targets", None) or [],
            getattr(intent, "facilities", None) or [],
            getattr(intent, "development_axes", None) or [],
            getattr(intent, "road_targets", None) or [],
            getattr(intent, "linear_targets", None) or [],
            getattr(intent, "site_area_targets", None) or [],
        ]
    for target_list in target_lists:
        for target in target_list or []:
            target_id = str(getattr(target, "target_id", "") or "")
            if target_id not in unresolved_target_ids:
                continue
            semantic = getattr(target, "semantic", None) or {}
            raw = ""
            if isinstance(semantic, dict):
                raw = " ".join(
                    str(part or "")
                    for part in (
                        semantic.get("raw_text", ""),
                        semantic.get("spatial_hint", ""),
                        semantic.get("natural_language_description", ""),
                    )
                ).strip()
            else:
                raw = " ".join(
                    str(part or "")
                    for part in (
                        getattr(semantic, "raw_text", ""),
                        getattr(semantic, "spatial_hint", ""),
                        getattr(semantic, "natural_language_description", ""),
                    )
                ).strip()
            if raw:
                raw_by_target[target_id] = raw

    if not raw_by_target:
        return {}

    from app.infrastructure.paths import run_tmp_root, session_run_dir
    from app.spatial.grounding.flash_mention_extractor import MentionCache, extract_mentions

    run_root = None
    try:
        run_root = run_tmp_root()
    except Exception:  # noqa: BLE001
        run_root = None
    cache_path = None
    if run_root is not None:
        cache_path = (run_root / "ground-mention-cache.json").resolve()
    cache = MentionCache(cache_path)
    enhanced: Dict[str, list[str]] = {}
    for target_id, raw in raw_by_target.items():
        mentions = await extract_mentions(raw, cache=cache, budget=budget)
        candidates = [
            m.mention for m in mentions if m.mention and len(m.mention) >= 2
        ]
        if candidates:
            enhanced[target_id] = list(dict.fromkeys(candidates))
    return enhanced


async def _village_cluster_map_for_context(
    context: Any,
    intent: Any,
    *,
    budget: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pre-resolve natural-village -> residential-cluster mapping (cached).

    Bundle-derived clusters give road/facility anchors for named villages that
    are absent from the KG gazetteer.  The flash mapping is cached under the
    run root so LangGraph replay/resume does not repeat the model call.
    """
    try:
        workspace = getattr(context, "workspace", None)
        if workspace is None:
            return {}
        names = await _settlement_mentions_for_cluster_mapping(context, intent)
        if not names:
            return {}
        parcels = list(workspace.current_parcels() or [])
        if not parcels:
            return {}
        from app.spatial.grounding.village_cluster_mapper import (
            build_village_clusters,
            collect_spatial_anchor_evidence,
            map_villages,
        )

        clusters = build_village_clusters(parcels)
        if not clusters:
            return {}
        from app.infrastructure.paths import run_tmp_root, session_run_dir
        from app.spatial.grounding.flash_mention_extractor import (
            create_flash_llm_safe,
        )

        cache = None
        try:
            cache = session_run_dir(str(getattr(context, "session_id", "") or "ground")) / "village-cluster-map.json"
        except Exception:
            cache = None
        report_text = await _context_report_text_async(context)
        llm = create_flash_llm_safe()
        spatial_evidence = collect_spatial_anchor_evidence(context, names)
        snapshot = getattr(workspace, "snapshot", None)
        landuse_collection = (
            snapshot.collection("landuse_current_geojson") if snapshot else None
        )
        return await map_villages(
            clusters,
            names,
            report_text=report_text,
            cache=cache,
            llm=llm,
            source_artifact_ref=(
                f"bundle-snapshot:{snapshot.snapshot_id}" if snapshot else ""
            ),
            source_artifact_digest=(
                str(
                    getattr(landuse_collection, "digest", "")
                    or getattr(snapshot, "digest", "")
                )
                if snapshot
                else ""
            ),
            budget=budget,
            spatial_evidence=spatial_evidence,
        )
    except Exception as exc:  # noqa: BLE001 - cluster mapping must never break GROUND
        logger.warning("[workflow:ground] village cluster mapping failed: %s", exc)
        return {}


async def _context_report_text_async(context: Any) -> str:
    """Read report正文 through the evidence/report storage boundary."""
    from app.evidence.retrieval.retrievers.report_retriever import load_report_corpus

    return await load_report_corpus(
        str(getattr(context, "session_id", "") or ""),
        context=context,
    )


def _target_metadata_from_compilation(
    compilation: Any,
    intent_graph: Any,
) -> Dict[str, Dict[str, str]]:
    """Expose target output semantics to GROUND without parsing free text."""

    metadata: Dict[str, Dict[str, str]] = {}
    nodes = getattr(intent_graph, "nodes", None)
    if nodes:
        for node in nodes:
            target_id = str(getattr(node, "target_id", "") or "")
            target_kind = str(getattr(node, "target_kind", "unknown") or "unknown")
            if target_id:
                metadata[target_id] = {
                    "target_kind": target_kind,
                    "expected_output_kind": _expected_output_for_target_kind(target_kind),
                }

    intent = getattr(compilation, "typed_intent", None)
    for field_name, target_kind, expected_output_kind in (
        ("zone_targets", "zone", "polygon"),
        ("facilities", "facility", "point"),
        ("development_axes", "axis", "line"),
        ("road_targets", "road", "line"),
        ("linear_targets", "linear", "line"),
        ("site_area_targets", "site_area", "polygon"),
    ):
        targets = intent.get(field_name, []) if isinstance(intent, dict) else getattr(intent, field_name, [])
        for target in list(targets or []):
            target_id = str(
                target.get("target_id", "") if isinstance(target, dict)
                else getattr(target, "target_id", "")
            )
            if target_id:
                metadata.setdefault(
                    target_id,
                    {
                        "target_kind": target_kind,
                        "expected_output_kind": expected_output_kind,
                    },
                )
    for claim in list(getattr(compilation, "pending_grounding_claims", None) or []):
        category = str(getattr(claim, "suggested_category", "") or "")
        target_kind = {
            "facility": "facility",
            "road": "road",
            "axis": "axis",
            "zone": (
                "zone"
                if str(getattr(claim, "materialization_role", "") or "")
                == "land_use_assignment"
                else "site_area"
            ),
            "site_area": "site_area",
            "restoration": "site_area",
            "protection": "site_area",
        }.get(category, "action")
        target_id = str(getattr(claim, "claim_id", "") or "").strip()
        if target_id and target_kind != "action":
            metadata.setdefault(
                target_id,
                {
                    "target_kind": target_kind,
                    "expected_output_kind": str(
                        getattr(claim, "suggested_output_kind", "") or "unknown"
                    ),
                },
            )
    return metadata


def _expected_output_for_target_kind(target_kind: str) -> str:
    return {
        "facility": "point",
        "road": "line",
        "linear": "line",
        "axis": "line",
        "zone": "polygon",
        "site_area": "polygon",
        "action": "action",
    }.get(target_kind, "unknown")


async def _settlement_mentions_for_cluster_mapping(
    context: Any,
    intent: Any,
) -> list[str]:
    """Collect settlement names from typed facts and one cached flash pass."""

    names: list[str] = []
    settlement_types = {
        "AdministrativeVillage",
        "ResidentialCluster",
        "administrative_village",
        "residential_cluster",
        "village",
    }
    for fact in list(getattr(context, "location_facts", []) or []):
        kind = str(
            getattr(fact, "entity_type", "")
            or getattr(fact, "place_type", "")
            or getattr(fact, "role", "")
            or ""
        )
        name = str(
            getattr(fact, "normalized_name", "")
            or getattr(fact, "name", "")
            or ""
        ).strip()
        if name and kind in settlement_types:
            names.append(name)

    texts: list[str] = []
    fields = (
        "zone_targets",
        "facilities",
        "development_axes",
        "road_targets",
        "linear_targets",
        "site_area_targets",
    )
    for field in fields:
        targets = intent.get(field, []) if isinstance(intent, dict) else getattr(intent, field, [])
        for target in list(targets or []):
            semantic = target.get("semantic", {}) if isinstance(target, dict) else getattr(target, "semantic", None)
            for attr in ("raw_text", "spatial_hint", "natural_language_description"):
                value = semantic.get(attr, "") if isinstance(semantic, dict) else getattr(semantic, attr, "")
                if value:
                    texts.append(str(value))
            for attr in ("location_hint", "connects"):
                value = target.get(attr) if isinstance(target, dict) else getattr(target, attr, None)
                if isinstance(value, list):
                    texts.extend(str(item) for item in value if item)
                elif value:
                    texts.append(str(value))

    combined = "\n".join(texts)[:5000]
    if combined:
        from app.infrastructure.paths import run_tmp_root, session_run_dir
        from app.spatial.grounding.flash_mention_extractor import MentionCache, extract_mentions

        cache = MentionCache(run_tmp_root() / "settlement-mention-cache.json")
        for mention in await extract_mentions(combined, cache=cache):
            if mention.role == "village" and mention.mention:
                names.append(mention.mention)
    return list(dict.fromkeys(names))


__all__ = ["ground_node"]
