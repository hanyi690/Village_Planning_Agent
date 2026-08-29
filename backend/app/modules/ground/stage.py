"""GROUND stage service: resolve projected spatial references to evidence."""

from __future__ import annotations

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


def _to_typed(data: Any, cls: type) -> Any:
    if data is None or isinstance(data, cls):
        return data
    if isinstance(data, dict):
        try:
            return cls(**data)
        except Exception:
            return data
    return data


def _complete_ground_stage(
    state: Dict[str, Any],
    *,
    output_refs: Dict[str, Any],
    gate: Any,
    context: Any,
    retry_patch: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    patch = stage_completion_patch(
        state,
        "ground",
        output_refs=output_refs,
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )
    return patch


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
        "village": ["parcels", "hazards", "facilities"],
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


def _ground_fact_reference_errors(
    request: Any,
    *,
    fact_catalog: Any,
) -> list[str]:
    """Validate every L1 fact reference before it enters formal GROUND.

    TARGET_PROJECTION receives a closed set per L3 dimension, while GROUND
    receives the complete immutable L1 snapshot.  This is the second, stage
    boundary check: it verifies that a replayed or hand-assembled projection
    still points at the current snapshot and never turns a stale ID into
    geometry lineage.
    """
    from app.workflow.validation.l1_fact_catalog import validate_l1_fact_references

    errors: list[str] = []
    for field_name, values in (
        (
            "semantic_spec.l1_fact_refs",
            list(getattr(getattr(request, "semantic_spec", None), "l1_fact_refs", None) or []),
        ),
        (
            "component_fact_refs",
            list(getattr(request, "component_fact_refs", None) or []),
        ),
    ):
        result = validate_l1_fact_references(values, catalog=fact_catalog)
        if result.accepted:
            continue
        details: list[str] = []
        if result.extra_ids:
            details.append("unknown=" + ",".join(result.extra_ids))
        if result.duplicate_ids:
            details.append("duplicate=" + ",".join(result.duplicate_ids))
        if not details:
            details.append("catalog_unusable")
        errors.append(f"{field_name}:" + ";".join(details))
    return errors


def _park_grounding_request(request: Any, reasons: list[str]) -> Any:
    """Rebuild one request as pending without retaining a stale fingerprint."""
    from app.contracts.target_projection.p1_closure import GroundingRequest

    payload = (
        request.model_dump(mode="python")
        if hasattr(request, "model_dump")
        else dict(request)
    )
    payload.update({
        "request_id": "",
        "status": "pending",
        "defer_reason": ";".join(dict.fromkeys(reasons)),
        "request_fingerprint": "",
    })
    return GroundingRequest.model_validate(payload)


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


def _merge_ground_packet_maps(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Merge one GROUND evidence wave into the current candidate packets.

    A later wave is allowed to add candidate identities, relation evidence and
    source spans.  It never overwrites a previous packet with a single page or
    turns a missing page into an empty successful result.
    """

    merged = dict(current or {})
    for target_id, packet in dict(incoming or {}).items():
        if packet is None:
            continue
        previous = merged.get(target_id)
        merged[target_id] = (
            _merge_ground_evidence_packets([previous, packet])
            if previous is not None
            else packet
        )
    return merged


def _ground_retry_target_ids(result: Any) -> set[str]:
    """Return targets whose current grounding is not yet closed.

    Candidate-only and ambiguous domains are deliberately included: they have
    a usable recall result, but a new relation/source/geometry packet may make
    them resolvable.  The list is target-scoped so one unresolved item does not
    cause the whole GROUND input to be queried repeatedly.
    """

    target_ids: set[str] = set()
    for issue in list(getattr(result, "unresolved", None) or []):
        target_id = str(getattr(issue, "related_artifact_id", "") or "").strip()
        if target_id:
            target_ids.add(target_id)
    problem = getattr(result, "problem", None)
    for collection_name in ("target_domains", "candidate_domains"):
        for domain in list(getattr(problem, collection_name, None) or []):
            if str(getattr(domain, "status", "unresolved") or "unresolved") == "resolved":
                continue
            target_id = str(getattr(domain, "target_id", "") or "").strip()
            if target_id:
                target_ids.add(target_id)
    return target_ids


def _ground_target_statuses(result: Any) -> dict[str, str]:
    """Return the latest typed status for every target touched by GROUND."""

    statuses: dict[str, str] = {}
    problem = getattr(result, "problem", None)
    for collection_name in ("target_domains", "candidate_domains"):
        for domain in list(getattr(problem, collection_name, None) or []):
            target_id = str(getattr(domain, "target_id", "") or "").strip()
            if not target_id:
                continue
            status = str(getattr(domain, "status", "unresolved") or "unresolved")
            if statuses.get(target_id) == "resolved":
                continue
            statuses[target_id] = status
    for issue in list(getattr(result, "unresolved", None) or []):
        target_id = str(getattr(issue, "related_artifact_id", "") or "").strip()
        if target_id and statuses.get(target_id) != "resolved":
            statuses[target_id] = "unresolved"
    return statuses


def _round_requirements(
    requirements_by_target: dict[str, list[Any]] | None,
    round_index: int,
) -> dict[str, list[Any]]:
    """Make each supplemental EvidenceFacade query a new, auditable request."""

    if round_index <= 0:
        return dict(requirements_by_target or {})
    output: dict[str, list[Any]] = {}
    for target_id, requirements in dict(requirements_by_target or {}).items():
        output[target_id] = [
            requirement.model_copy(update={
                "statement": (
                    f"{requirement.statement}; GROUND补充定位轮次={round_index}；"
                    "重新检查当前源中的候选、关系和空间引用，"
                    "仅返回可验证的来源证据，不生成新身份或几何"
                ),
            })
            if hasattr(requirement, "model_copy")
            else requirement
            for requirement in requirements
        ]
    return output


async def _retrieve_ground_evidence_packets(
    context: Any,
    specs: list[Any],
    requirements_by_target: dict[str, list[Any]] | None = None,
    *,
    round_index: int = 0,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Fetch bounded packets and retain every retrieval error.

    The packet is a bounded EvidenceGraph view. The resolver remains the
    single grounding authority when a packet is absent; absence is recorded
    so a provider or graph error cannot disappear as an empty candidate set.
    """
    session_id = str(getattr(context, "session_id", "") or "").strip()
    if not session_id or getattr(context, "evidence_graph", None) is None:
        return {}, []
    from app.contracts.evidence.requirement_contracts import EvidenceRequirement
    from app.modules.evidence.application import EvidenceApplication, EvidenceContext

    work: list[tuple[str, Any, str, list[str]]] = []
    for spec in list(specs or []):
        target_id = str(getattr(spec, "target_id", "") or "").strip()
        query, scopes = _ground_packet_query(context, spec)
        if target_id and query:
            work.append((target_id, spec, query, scopes))
    if not work:
        return {}, []

    semaphore = asyncio.Semaphore(4)
    round_requirements = _round_requirements(requirements_by_target, round_index)

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
                    requirements = list(
                        round_requirements.get(target_id, [])
                    )
                    if not requirements:
                        requirements = [
                            EvidenceRequirement(
                                requirement_id=(
                                    f"{session_id}:ground:{target_id}:r{round_index}"
                                ),
                                request_id=f"{session_id}:ground:r{round_index}",
                                producer_stage="GROUND",
                                statement=(
                                    f"{query}; GROUND补充定位轮次={round_index}；"
                                    "重新检查当前源中的候选、关系和空间引用，"
                                    "仅返回可验证的来源证据，不生成新身份或几何"
                                ),
                                kind="spatial",
                                source_families=("bundle", "kg"),
                                scope=tuple(scopes),
                                spatial_granularity="feature",
                                allowed_inference="exact",
                                evidence_role="grounding_candidate_resolution",
                                success_condition="返回可验证的空间候选和来源定位",
                            )
                        ]
                    result = await EvidenceApplication().retrieve(
                        requirements,
                        EvidenceContext(
                            session_id=session_id,
                            village_name=str(getattr(context, "village_name", "") or ""),
                            run_id=f"{session_id}:ground:r{round_index}",
                            stage="GROUND",
                            dimension_key="location",
                            purpose=f"grounding_candidate_resolution:round:{round_index}",
                            request_type="spatial_lookup",
                        ),
                        spatial_spec=_spec,
                        candidate_offset=offset,
                        candidate_limit=64,
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


async def _retrieve_ground_gap_evidence(
    context: Any,
    evidence_requests: list[str] | None,
) -> list[Any]:
    """Resolve retry requests through the typed Evidence business facade."""

    requests = list(dict.fromkeys(
        " ".join(str(item).split())
        for item in (evidence_requests or [])
        if " ".join(str(item).split())
    ))[:8]
    session_id = str(getattr(context, "session_id", "") or "").strip()
    if not session_id or not requests:
        return []

    from app.contracts.evidence.requirement_contracts import EvidenceRequirement
    from app.contracts.ground.grounding_contracts import SpatialQueryEvidence
    from app.modules.evidence.application import EvidenceApplication, EvidenceContext

    request_targets = [
        statement.partition("target_id=")[2].partition(";")[0].strip()
        for statement in requests
    ]
    requirements = [
        EvidenceRequirement(
            requirement_id=f"{session_id}:ground:gap:{index}",
            request_id=f"{session_id}:ground:gap",
            producer_stage="GROUND",
            statement=statement,
            kind="claim",
            source_families=("report", "bundle", "kg", "gis", "rag", "external"),
            scope=("facilities", "parcels", "roads", "waters", "zones"),
            allowed_inference="exact",
            evidence_role="grounding_gap_resolution",
            success_condition="返回可追溯的证据 locator 或明确的不可用原因",
            metadata={
                "target_id": target_id
                if target_id and target_id != "unresolved"
                else "",
                "recovery_scope": "ground_target",
            },
        )
        for index, (statement, target_id) in enumerate(zip(requests, request_targets))
    ]
    try:
        result = await EvidenceApplication().retrieve(
            requirements,
            EvidenceContext(
                session_id=session_id,
                village_name=str(getattr(context, "village_name", "") or ""),
                run_id=f"{session_id}:ground:gap",
                stage="GROUND",
                dimension_key="location",
                purpose="grounding_gap_resolution",
                request_type="evidence_gap",
            ),
        )
    except Exception as exc:  # noqa: BLE001 - retry remains structured
        logger.warning("[workflow:ground] typed gap retrieval failed: %s", exc)
        return [
            SpatialQueryEvidence(
                query_type="evidence:gap_failure",
                query_params={"error": f"{type(exc).__name__}: {exc}"},
                result_count=0,
                result_refs=[],
                target_id=target_id if target_id != "unresolved" else "",
            )
            for target_id in request_targets
        ]

    bundle = getattr(result, "evidence_bundle", None)
    refs: list[str] = []
    for fact in list(getattr(bundle, "facts", None) or []):
        refs.extend(
            str(value).strip()
            for value in (
                *(getattr(fact, "source_refs", None) or []),
                *(getattr(fact, "spatial_refs", None) or []),
                getattr(fact, "source_locator", ""),
            )
            if str(value or "").strip()
        )
    coverage = getattr(result, "coverage", None)
    for claim in list(getattr(coverage, "claims", None) or []):
        refs.extend(
            str(value).strip()
            for value in (
                *(getattr(claim, "source_refs", None) or []),
                *(getattr(claim, "locators", None) or []),
            )
            if str(value or "").strip()
        )
    refs = list(dict.fromkeys(refs))[:64]
    return [
        SpatialQueryEvidence(
            query_type="evidence:gap_resolution",
            query_params={
                "request": statement,
                "fact_count": len(getattr(bundle, "facts", None) or []),
                "coverage": str(getattr(coverage, "stop_reason", "") or ""),
                "unresolved": list(getattr(bundle, "unresolved", None) or [])[:8],
            },
            result_count=len(refs),
            result_refs=refs,
            target_id=target_id if target_id != "unresolved" else "",
        )
        for statement, target_id in zip(requests, request_targets)
    ]


async def ground_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """GROUND node: specs + context -> GroundingResult + gate."""
    from app.modules.ground.application import ground_aggregate
    from app.modules.ground.validation import evaluate_ground_gate
    from app.contracts.target_projection.parse_result_contracts import IntentCompilationResult
    from app.contracts.ground.spatial_reference_contracts import SpatialReferenceSpec

    retry_patch = _retry_patch(state, "ground")
    context = await _require_context(state)
    from app.spatial.grounding.call_budget import get_ground_llm_budget

    ground_llm_budget = get_ground_llm_budget(
        context,
        scope_key=f"workflow:{state.get('session_id') or ''}",
    )
    compilation = _load_ref_artifact(state, "target_projection", IntentCompilationResult)
    # A checkpoint replay can re-enter GROUND after the stage already committed
    # its immutable result.  Reusing that result is part of the replay
    # contract: rerunning grounding would regenerate runtime timestamps and
    # may repeat retrieval/LLM work even though the target projection is
    # unchanged.  The parent-digest check keeps this optimization fail-closed
    # when a new projection is present.
    if not retry_patch and compilation is not None:
        refs = dict(state.get("artifact_refs") or {})
        cached_ref = refs.get("grounding_result")
        projection_ref = refs.get("target_projection")
        cached_parents = (
            cached_ref.get("parent_digests", {})
            if isinstance(cached_ref, dict)
            else getattr(cached_ref, "parent_digests", {})
        )
        cached_projection_digest = (
            projection_ref.get("digest")
            if isinstance(projection_ref, dict)
            else getattr(projection_ref, "digest", "")
        )
        if (
            cached_ref
            and cached_projection_digest
            and cached_parents.get("target_projection") == cached_projection_digest
        ):
            from app.contracts.ground.grounding_contracts import GroundingResult

            cached_result = _load_ref_artifact(
                state,
                "grounding_result",
                GroundingResult,
            )
            if cached_result is not None:
                cached_gate = state.get("ground_gate")
                if cached_gate is not None:
                    output_refs = {"grounding_result": cached_ref}
                    if refs.get("planning_task_graph"):
                        output_refs["planning_task_graph"] = refs["planning_task_graph"]
                    output_refs["target_projection"] = projection_ref
                    logger.info(
                        "[workflow:ground] reusing committed result for unchanged target projection"
                    )
                    return _complete_ground_stage(
                        state,
                        output_refs=output_refs,
                        gate=cached_gate,
                        context=context,
                    )

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

    projection_ref = (state.get("artifact_refs") or {}).get("target_projection")
    specs = [
        _to_typed(item, SpatialReferenceSpec)
        for item in (
            *list(getattr(compilation, "spatial_reference_specs", None) or []),
            *list(getattr(compilation, "pending_grounding_specs", None) or []),
        )
    ]
    # GroundingRequest is the formal admission authority.  Keep this check at
    # the GROUND boundary as well as in TARGET compilation so replayed or
    # hand-assembled artifacts cannot turn a pending request into a candidate.
    requests_by_target = {
        str(getattr(request, "target_ref", "") or ""): request
        for request in (
            *list(getattr(compilation, "grounding_requests", None) or []),
            *list(getattr(compilation, "pending_grounding_requests", None) or []),
        )
        if str(getattr(request, "target_ref", "") or "").strip()
    }
    from app.workflow.validation.l1_fact_catalog import build_l1_fact_catalog

    # ``_require_context`` hydrates this list from the exact L1 snapshot
    # referenced by the checkpoint.  GROUND validates against the complete
    # snapshot (not a dimension-local prompt catalog), because a physical
    # project may carry lineage from several L3 dimensions.
    fact_catalog = build_l1_fact_catalog(
        getattr(context, "l1_fact_records", None) or []
    )
    grounding_specs = []
    admitted_requests = []
    parked_fact_requests = []
    fact_reference_issues: list[tuple[str, list[str]]] = []
    for spec in specs:
        request = requests_by_target.get(str(getattr(spec, "target_id", "") or ""))
        if request is None:
            continue
        request_status = str(getattr(request, "status", "pending") or "pending")
        initial_pending_intake = (
            request_status == "pending"
            and str(getattr(spec, "unresolved_reason", "") or "")
            == "pending_grounding"
            and bool(str(getattr(spec, "source_snapshot_ref", "") or "").strip())
            and bool(str(getattr(spec, "source_snapshot_digest", "") or "").strip())
        )
        if request_status != "ready" and not initial_pending_intake:
            continue
        authority_fields = (
            "source_snapshot_ref",
            "source_snapshot_digest",
            "source_binding_ref",
            "source_feature_digest",
        )
        if any(
            str(getattr(request, field, "") or "")
            != str(getattr(spec, field, "") or "")
            for field in authority_fields
        ):
            logger.warning(
                "[workflow:ground] source authority mismatch; parking target=%s",
                getattr(spec, "target_id", ""),
            )
            continue
        fact_errors = _ground_fact_reference_errors(
            request,
            fact_catalog=fact_catalog,
        )
        if fact_errors:
            target_ref = str(
                getattr(request, "target_ref", "")
                or getattr(spec, "target_id", "")
                or ""
            ).strip()
            parked_fact_requests.append(
                _park_grounding_request(request, [
                    "l1_fact_reference_not_in_current_snapshot",
                    *fact_errors,
                ])
            )
            fact_reference_issues.append((target_ref, fact_errors))
            logger.warning(
                "[workflow:ground] stale/invalid L1 fact reference; parking target=%s errors=%s",
                target_ref,
                fact_errors,
            )
            continue
        grounding_specs.append(spec)
        admitted_requests.append(request)
    # Pending claim intake may enter the bounded candidate/evidence resolver
    # only when it is bound to the current L1 snapshot.  The request remains
    # pending and cannot become an executable target at this boundary.
    if getattr(compilation, "pending_grounding_requests", None):
        logger.info(
            "[workflow:ground] parked pending grounding requests=%d",
            len(compilation.pending_grounding_requests),
        )

    evidence = []
    if retry_patch:
        prior_gate = state.get("ground_gate")
        requests = getattr(prior_gate, "evidence_requests", None)
        if requests is None and isinstance(prior_gate, dict):
            requests = prior_gate.get("evidence_requests")
        try:
            evidence = await _retrieve_ground_gap_evidence(context, requests or None)
        except Exception as exc:
            logger.warning("[workflow:ground] gap evidence retrieval failed: %s", exc)
    intent_graph = getattr(compilation, "intent_graph", None)
    target_metadata = _target_metadata_from_compilation(compilation, intent_graph)
    from app.modules.evidence.requirements import requirements_from_target_projection

    target_requirements = requirements_from_target_projection(compilation)
    requirements_by_target: dict[str, list[Any]] = {}
    for requirement in target_requirements:
        target_id = str(requirement.metadata.get("target_id", "") or "").strip()
        if target_id:
            requirements_by_target.setdefault(target_id, []).append(requirement)
    evidence_packets: dict[str, Any] = {}
    packet_diagnostics: list[dict[str, str]] = []
    ground_reasoning: dict[str, dict[str, Any]] = {}
    ground_iterations: list[dict[str, Any]] = []
    if grounding_specs:
        from app.core.llm_config import get_llm_settings
        from app.modules.ground.reasoning import (
            prioritize_ground_targets,
            reason_ground_candidates,
        )

        max_rounds = max(
            1,
            min(
                int(get_llm_settings().ground_max_recovery_rounds or 1),
                3,
            ),
        )
        previous_packet_signature: tuple[Any, ...] | None = None
        previous_target_statuses: dict[str, str] = {}
        retry_target_ids: set[str] = {
            str(getattr(spec, "target_id", "") or "").strip()
            for spec in grounding_specs
            if str(getattr(spec, "target_id", "") or "").strip()
        }
        for round_index in range(max_rounds):
            active_specs = [
                spec
                for spec in grounding_specs
                if round_index == 0
                or str(getattr(spec, "target_id", "") or "").strip()
                in retry_target_ids
            ]
            if not active_specs:
                break
            round_packets, round_diagnostics = await _retrieve_ground_evidence_packets(
                context,
                active_specs,
                requirements_by_target,
                round_index=round_index,
            )
            evidence_packets = _merge_ground_packet_maps(
                evidence_packets,
                round_packets,
            )
            priority_advice = await prioritize_ground_targets(
                active_specs,
                round_packets,
                budget=ground_llm_budget,
                round_index=round_index + 1,
            )
            priority_order = {
                target_id: index
                for index, target_id in enumerate(
                    priority_advice.get("ordered_target_ids", [])
                )
            }
            original_order = {
                id(spec): index for index, spec in enumerate(grounding_specs)
            }
            ordered_specs = sorted(
                grounding_specs,
                key=lambda spec: (
                    priority_order.get(
                        str(getattr(spec, "target_id", "") or "").strip(),
                        len(priority_order) + 1,
                    ),
                    original_order.get(id(spec), len(grounding_specs)),
                ),
            )
            packet_diagnostics.extend(round_diagnostics)
            result = ground_aggregate(
                ordered_specs,
                context,
                intent_graph=intent_graph,
                target_metadata=target_metadata,
                evidence_packets=evidence_packets,
                ground_llm_budget=ground_llm_budget,
            )
            ground_reasoning = await reason_ground_candidates(
                result,
                grounding_specs,
                budget=ground_llm_budget,
                round_index=round_index + 1,
            )
            target_statuses = _ground_target_statuses(result)
            retry_target_ids = _ground_retry_target_ids(result)
            packet_signature = tuple(
                (
                    target_id,
                    tuple(
                        _packet_ref_key(ref)
                        for ref in list(
                            getattr(packet, "candidate_refs", None) or []
                        )
                    ),
                    tuple(
                        str(getattr(item, "relation_id", "") or "")
                        for item in list(
                            getattr(packet, "relation_evidence", None) or []
                        )
                    ),
                    tuple(getattr(packet, "source_spans", None) or []),
                    tuple(getattr(packet, "missing_evidence", None) or []),
                )
                for target_id, packet in sorted(evidence_packets.items())
            )
            ground_iterations.append({
                "round": round_index + 1,
                "active_target_ids": sorted({
                    str(getattr(spec, "target_id", "") or "").strip()
                    for spec in active_specs
                    if str(getattr(spec, "target_id", "") or "").strip()
                }),
                "packet_target_count": len(round_packets),
                "packet_candidate_count": sum(
                    len(getattr(packet, "candidate_refs", None) or [])
                    for packet in round_packets.values()
                ),
                "llm_decision_count": len(ground_reasoning),
                "llm_priority_count": len(priority_advice.get("decisions", {})),
                "llm_priority": {
                    target_id: {
                        "priority": str(decision.get("priority", "low") or "low"),
                        "reason": str(decision.get("reason", "") or ""),
                        "input_digest": str(decision.get("input_digest", "") or ""),
                    }
                    for target_id, decision in sorted(
                        priority_advice.get("decisions", {}).items()
                    )
                },
                "llm_decisions": {
                    target_id: {
                        "status": str(decision.get("status", "") or ""),
                        "selected_candidate_id": str(
                            decision.get("selected_candidate_id", "") or ""
                        ),
                        "reason": str(decision.get("reason", "") or ""),
                        "input_digest": str(decision.get("input_digest", "") or ""),
                    }
                    for target_id, decision in sorted(ground_reasoning.items())
                },
                "target_statuses": dict(sorted(target_statuses.items())),
                "became_resolvable_target_ids": sorted(
                    target_id
                    for target_id, status in target_statuses.items()
                    if status == "resolved"
                    and previous_target_statuses.get(target_id) != "resolved"
                ),
                "unresolved_target_ids": sorted(retry_target_ids),
                "new_packet_content": packet_signature != previous_packet_signature,
            })
            if not retry_target_ids:
                break
            if (
                round_index > 0
                and packet_signature == previous_packet_signature
            ):
                ground_iterations[-1]["stop_reason"] = "evidence_wave_unchanged"
                break
            previous_packet_signature = packet_signature
            previous_target_statuses = target_statuses
        if evidence_packets:
            logger.info(
                "[workflow:ground] canonical evidence packets=%d rounds=%d",
                len(evidence_packets),
                len(ground_iterations),
            )
    else:
        from app.contracts.ground.grounding_contracts import GroundingResult

        result = GroundingResult()
    if ground_iterations:
        from app.contracts.ground.grounding_contracts import SpatialQueryEvidence

        result.spatial_query_evidence.extend(
            SpatialQueryEvidence(
                query_type="ground_resolution_iteration",
                query_params={
                    "round": int(item.get("round", 0) or 0),
                    "active_target_ids": list(item.get("active_target_ids", []) or []),
                    "packet_target_count": int(item.get("packet_target_count", 0) or 0),
                    "packet_candidate_count": int(item.get("packet_candidate_count", 0) or 0),
                    "llm_decision_count": int(item.get("llm_decision_count", 0) or 0),
                    "llm_priority_count": int(item.get("llm_priority_count", 0) or 0),
                    "llm_priority": dict(item.get("llm_priority", {}) or {}),
                    "llm_decisions": dict(item.get("llm_decisions", {}) or {}),
                    "target_statuses": dict(item.get("target_statuses", {}) or {}),
                    "became_resolvable_target_ids": list(
                        item.get("became_resolvable_target_ids", []) or []
                    ),
                    "unresolved_target_ids": list(item.get("unresolved_target_ids", []) or []),
                    "new_packet_content": bool(item.get("new_packet_content", False)),
                    "stop_reason": str(item.get("stop_reason", "") or ""),
                },
                result_count=int(item.get("packet_candidate_count", 0) or 0),
                result_refs=[],
                target_id="",
            )
            for item in ground_iterations
        )
    if packet_diagnostics:
        from app.contracts.ground.grounding_contracts import SpatialQueryEvidence

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

    # Reattach request lineage after deterministic packet resolution.
    result.grounding_requests = list(admitted_requests)
    result.pending_grounding_requests = [
        *list(getattr(compilation, "pending_grounding_requests", None) or []),
        *parked_fact_requests,
    ]
    if fact_reference_issues:
        from app.contracts.artifacts.contract_meta import StageIssue

        result.unresolved.extend(
            StageIssue(
                stage="ground",
                severity="error",
                code="L1_FACT_REFERENCE_NOT_IN_CURRENT_SNAPSHOT",
                message=(
                    "GROUND rejected L3 lineage outside the current canonical L1 snapshot"
                ),
                detail="; ".join(errors),
                related_artifact_id=target_ref or None,
            )
            for target_ref, errors in fact_reference_issues
        )

    if evidence and hasattr(result, "spatial_query_evidence"):
        result.spatial_query_evidence.extend(evidence)
        for item in evidence:
            target_id = str(getattr(item, "target_id", "") or "").strip()
            if not target_id:
                continue
            refs = [ref for ref in item.result_refs if ref]
            if not refs:
                continue
            for candidate in (getattr(result, "candidates", None) or []):
                candidate_target_id = str(
                    getattr(candidate, "target_ref", None)
                    or getattr(candidate, "project_ref", None)
                    or ""
                ).strip()
                if candidate_target_id != target_id:
                    continue
                if hasattr(candidate, "evidence_refs"):
                    candidate.evidence_refs.extend(refs)
    if ground_reasoning:
        from app.contracts.ground.grounding_contracts import SpatialQueryEvidence

        result.spatial_query_evidence.extend(
            SpatialQueryEvidence(
                query_type="llm_closed_set_candidate_selection",
                query_params={
                    "status": str(decision.get("status", "")),
                    "reason": str(decision.get("reason", "") or ""),
                    "input_digest": str(decision.get("input_digest", "") or ""),
                    "candidate_set_digest": str(
                        decision.get("candidate_set_digest", "") or ""
                    ),
                },
                result_count=1 if decision.get("selected_candidate_id") else 0,
                result_refs=(
                    [str(decision["selected_candidate_id"])]
                    if decision.get("selected_candidate_id")
                    else []
                ),
                target_id=str(target_id),
            )
            for target_id, decision in sorted(ground_reasoning.items())
        )
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
        from app.modules.ground.iterative_resolution import execute_planning_task_graph

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
    patch = _complete_ground_stage(
        state,
        output_refs=output_refs,
        gate=gate,
        context=context,
        retry_patch=retry_patch,
    )
    return patch


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


__all__ = ["ground_node"]
