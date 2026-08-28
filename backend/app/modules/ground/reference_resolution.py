"""GROUND reference-resolution boundary.

This module owns both spatial entry points:

* L1 semantic ``LocationMention`` -> source-backed entity binding; and
* post-L3 ``SpatialReferenceSpec`` -> planning candidate resolution.

The first entry point is deliberately independent of TARGET_PROJECTION.  L1
mentions are already useful spatial work items before a planning intent exists.
The resolver may use an LLM only as a closed-set selector; all identities,
feature references and geometry references still come from the current source
context and are validated by the spatial runtime.
"""

from __future__ import annotations

from typing import Any

from app.contracts.evidence.identity_contracts import (
    GroundedEntityBinding,
    infer_geometry_granularity,
)
from app.contracts.ground.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
    normalize_spatial_role,
)
from app.infrastructure.evidence_runtime.identity.binding_store import BindingStore
from app.infrastructure.evidence_runtime.identity.observation_store import ObservationStore
from app.spatial.grounding.resolver import SpatialResolver


_ROLE_SCOPES = {
    "facility": ("facilities", "parcels"),
    "landmark": ("facilities", "parcels"),
    "road": ("roads", "parcels"),
    "water": ("waters", "parcels"),
    "hazard": ("hazards", "facilities"),
    "project": ("facilities", "parcels"),
    "area": ("zones", "parcels"),
    "natural_village": ("parcels", "facilities"),
    "administrative_village": ("parcels", "facilities"),
    "settlement": ("parcels", "facilities"),
}


def _value(item: Any, field: str, default: str = "") -> str:
    if isinstance(item, dict):
        return str(item.get(field, default) or "").strip()
    return str(getattr(item, field, default) or "").strip()


def _scope_values(mention: Any) -> list[str]:
    values: list[str] = []
    for scope in list(getattr(mention, "scopes", None) or []):
        value = _value(scope, "normalized_name") or _value(scope, "name")
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _relation_values(mention: Any) -> list[str]:
    raw = (
        mention.get("related_mentions", [])
        if isinstance(mention, dict)
        else getattr(mention, "related_mentions", None)
    ) or []
    return list(dict.fromkeys(
        str(value).strip()
        for value in raw
        if str(value).strip()
    ))


def _mention_spec(mention: Any, observation_ref: str, context: Any) -> SpatialReferenceSpec:
    """Compile one semantic mention into a runtime-owned spatial query.

    Only the query semantics are copied from L1.  Runtime identities and
    source lineage are supplied here by the current context; no provider ID,
    coordinate, BSM or geometry is accepted from the mention.
    """

    name = _value(mention, "normalized_name") or _value(mention, "mention")
    role = normalize_spatial_role(_value(mention, "role", "unknown"))
    scopes = _scope_values(mention)
    relations = _relation_values(mention)
    semantic_terms = list(dict.fromkeys([
        name,
        *scopes,
        _value(mention, "spatial_hint"),
        *relations,
    ]))
    semantic_terms = [value for value in semantic_terms if value][:8]
    snapshot = str(getattr(context, "l1_snapshot_ref", "") or "").strip()
    bundle_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    ).strip()
    return SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": name}),
        semantic_terms=semantic_terms,
        retrieval_scopes=list(_ROLE_SCOPES.get(role, ("facilities", "roads", "waters", "parcels"))),
        target_id=observation_ref,
        spec_id=f"l1-ground:{observation_ref}",
        source_snapshot_ref=snapshot,
        source_snapshot_digest=bundle_digest,
        l1_fact_refs=[
            value
            for value in (
                _value(mention, "fact_id"),
                *list(getattr(mention, "evidence_refs", None) or []),
            )
            if value
        ],
        unresolved_reason="l1_location_mention",
    )


def _candidate_identity(candidate: Any) -> str:
    return str(getattr(candidate, "entity_ref", "") or "").strip()


def _candidate_bsms(candidate: Any) -> set[str]:
    return {
        str(value).strip()
        for value in (
            getattr(candidate, "source_bsms", None) or [],
            getattr(candidate, "feature_bsm", ""),
            getattr(candidate, "source_bsm", ""),
        )
        for value in (value if isinstance(value, (list, tuple, set)) else [value])
        if str(value).strip()
    }


def _binding_from_resolution(
    base: GroundedEntityBinding,
    mention: Any,
    resolved: Any,
    graph_result: Any,
) -> GroundedEntityBinding:
    candidates = list(getattr(graph_result, "candidates", None) or [])
    resolved_bsms = {
        str(value).strip()
        for value in (
            list(getattr(resolved, "final_bsms", None) or [])
            + list(getattr(resolved, "feature_bsms", None) or [])
        )
        if str(value).strip()
    }
    geometry_refs = list(getattr(resolved, "reference_geometries", None) or [])
    resolved_source_refs = {
        str(value).strip()
        for geometry in geometry_refs
        for value in (
            getattr(geometry, "source_ref", ""),
            getattr(geometry, "source_feature_id", ""),
        )
        if str(value).strip()
    }
    matching = [
        candidate
        for candidate in candidates
        if (
            _candidate_bsms(candidate) & resolved_bsms
            or _candidate_identity(candidate) in resolved_source_refs
            or str(getattr(candidate, "source_feature_id", "") or "").strip()
            in resolved_source_refs
        )
    ]
    if not matching and len(resolved_bsms) == 1:
        matching = [candidate for candidate in candidates if _candidate_bsms(candidate)]
    candidate_refs = list(dict.fromkeys(
        _candidate_identity(candidate)
        for candidate in candidates
        if _candidate_identity(candidate)
    ))
    evidence_refs = list(dict.fromkeys(
        str(ref).strip()
        for candidate in candidates
        for ref in (getattr(candidate, "evidence_refs", None) or [])
        if str(ref).strip()
    ))
    relation_refs = list(dict.fromkeys(
        str(ref).strip()
        for candidate in candidates
        for ref in (getattr(candidate, "relation_refs", None) or [])
        if str(ref).strip()
    ))
    source_feature_ids = list(dict.fromkeys(
        str(getattr(candidate, "source_feature_id", "") or "").strip()
        for candidate in (matching or candidates)
        if str(getattr(candidate, "source_feature_id", "") or "").strip()
    ))
    selected = (
        matching[0]
        if len(matching) == 1 and len(resolved_bsms) <= 1 and len(geometry_refs) <= 1
        else None
    )
    search_scope = getattr(resolved, "search_scope", None)
    if selected is not None:
        status = "exact_feature"
        entity_ref = _candidate_identity(selected)
        source_bsms = sorted(_candidate_bsms(selected) & resolved_bsms) or sorted(_candidate_bsms(selected))
        geometry_ref = (
            str(getattr(selected, "geometry_ref", "") or "").strip()
            or str(getattr(geometry_refs[0], "source_ref", "") or "").strip()
            or None
        )
        confidence = float(getattr(selected, "score", 0.0) or getattr(resolved, "confidence", 0.0) or 0.0)
    elif resolved_bsms or geometry_refs:
        status = "feature_set" if len(resolved_bsms) > 1 or len(matching) > 1 else "name_only"
        entity_ref = ""
        source_bsms = sorted(resolved_bsms)
        geometry_ref = None
        confidence = float(getattr(resolved, "confidence", 0.0) or 0.0)
    elif search_scope is not None:
        status = "inferred_scope"
        entity_ref = ""
        source_bsms = []
        geometry_ref = None
        confidence = float(getattr(search_scope, "confidence", 0.0) or 0.0)
    elif candidates:
        status = "ambiguous" if str(getattr(graph_result, "status", "")) == "ambiguous" else "name_only"
        entity_ref = ""
        source_bsms = []
        geometry_ref = None
        confidence = max((float(getattr(item, "score", 0.0) or 0.0) for item in candidates), default=0.0)
    else:
        status = "unresolved"
        entity_ref = ""
        source_bsms = []
        geometry_ref = None
        confidence = 0.0
    reason = str(
        getattr(resolved, "uncertainty_reason", "")
        or getattr(graph_result, "unresolved_reason", "")
        or ("resolved_from_current_evidence" if entity_ref else "no_current_source_candidate")
    )
    trace = list(getattr(graph_result, "query_trace", None) or [])
    trace.extend(
        list(dict(getattr(resolved, "provenance", {}) or {}).get("query_trace", []) or [])
    )
    trace.append({
        "step": "ground_l1_mention_resolution",
        "mention_ref": base.mention_ref,
        "candidate_count": len(candidates),
        "resolved_bsm_count": len(resolved_bsms),
        "status": status,
    })
    return base.model_copy(update={
        "canonical_entity_ref": entity_ref,
        "status": status,
        "geometry_granularity": (
            "settlement" if status == "inferred_scope" else infer_geometry_granularity(
                geometry_ref,
                entity_ref=entity_ref,
                source_bsms=source_bsms,
            )
        ),
        "geometry_ref": geometry_ref,
        "source_feature_ids": source_feature_ids,
        "source_bsms": source_bsms,
        "candidate_refs": candidate_refs,
        "evidence_refs": evidence_refs,
        "relation_evidence_refs": relation_refs,
        "confidence": confidence,
        "uncertainty_reason": reason,
        "query_trace": trace[-32:],
        "search_scope": search_scope,
    })


def resolve_l1_location_mentions(
    context: Any,
    *,
    ground_llm_budget: dict[str, Any] | None = None,
    evidence_packets: dict[str, Any] | None = None,
    max_rounds: int = 2,
) -> list[GroundedEntityBinding]:
    """Resolve every L1 location work item against current source evidence.

    The loop is deliberately bounded and resumable.  A resolved mention is
    placed on ``context.grounded_bindings`` so later mention queries may use it
    as a scope/anchor; unresolved and ambiguous items remain explicit and are
    never converted into executable candidates.
    """

    mentions = list(getattr(context, "location_mentions", None) or [])
    if not mentions:
        return []
    base_bindings = BindingStore.from_context(context)
    observations = ObservationStore.from_location_mentions(mentions)
    context.evidence_observations = observations
    bindings_by_ref = {binding.mention_ref: binding for binding in base_bindings}
    resolver = SpatialResolver(context, ground_llm_budget=ground_llm_budget)
    rounds = max(1, min(int(max_rounds or 1), 3))
    for round_index in range(rounds):
        changed = False
        for mention, observation in zip(mentions, observations):
            name = _value(mention, "normalized_name") or _value(mention, "mention")
            base = bindings_by_ref.get(observation.observation_id)
            if base is None:
                continue
            if round_index and base.status in {"exact_feature", "feature_set", "inferred_scope"}:
                continue
            spec = _mention_spec(mention, observation.observation_id, context)
            try:
                packet = (evidence_packets or {}).get(observation.observation_id)
                resolved = resolver.resolve_spec(spec, evidence_packet=packet)
                graph_result = resolver.evidence_graph.resolve_mention(
                    name,
                    role=_value(mention, "role", "unknown"),
                    hints=" ".join([
                        *_scope_values(mention),
                        _value(mention, "spatial_hint"),
                        *_relation_values(mention),
                    ]),
                )
                updated = _binding_from_resolution(base, mention, resolved, graph_result)
                if packet is not None:
                    packet_trace = {
                        "step": "ground_l1_evidence_facade",
                        "observation_ref": observation.observation_id,
                        "candidate_count": len(
                            getattr(packet, "candidate_refs", None) or []
                        ),
                        "candidate_total": int(
                            getattr(packet, "candidate_total", 0) or 0
                        ),
                        "candidate_offset": int(
                            getattr(packet, "candidate_offset", 0) or 0
                        ),
                        "ambiguity_status": str(
                            getattr(packet, "ambiguity_status", "unresolved")
                            or "unresolved"
                        ),
                        "sufficiency": str(
                            getattr(packet, "sufficiency", "insufficient")
                            or "insufficient"
                        ),
                        "missing_evidence": list(
                            getattr(packet, "missing_evidence", None) or []
                        )[:8],
                    }
                    updated = updated.model_copy(update={
                        "query_trace": [
                            *list(updated.query_trace or []),
                            packet_trace,
                        ][-32:],
                    })
            except Exception as exc:  # noqa: BLE001 - keep the work item auditable
                updated = base.model_copy(update={
                    "status": "unresolved",
                    "uncertainty_reason": f"ground_resolution_error:{type(exc).__name__}",
                    "query_trace": [
                        *list(base.query_trace or []),
                        {"step": "ground_l1_mention_resolution_error", "round": round_index + 1},
                    ][-32:],
                })
            if updated != base:
                changed = True
            bindings_by_ref[observation.observation_id] = updated
        context.grounded_bindings = list(bindings_by_ref.values())
        if not changed:
            break
    return [bindings_by_ref[key] for key in sorted(bindings_by_ref)]


__all__ = ["SpatialResolver", "resolve_l1_location_mentions"]
