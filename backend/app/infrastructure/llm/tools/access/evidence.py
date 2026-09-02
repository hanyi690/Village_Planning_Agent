"""Candidate-only evidence tools for the LLM.

The LLM can inspect bounded evidence and request verified bundle geometry by
feature reference.  It cannot create or overwrite a BSM, entity, relation, or
geometry record.
"""

from __future__ import annotations

from typing import Any, Annotated, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from app.contracts.evidence.evidence_contracts import (
    ExplorationRequest,
    ExplorationResult,
)
from .shared import budget_check, tool_reply


def _pagination_metadata(
    packet: Any,
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Expose a deterministic continuation request to the planning LLM."""
    next_offset = packet.next_candidate_offset
    next_request = None
    if next_offset is not None:
        next_request = {
            "tool": tool_name,
            "arguments": {
                **arguments,
                "candidate_offset": next_offset,
                "candidate_limit": packet.candidate_limit,
            },
        }
    return {
        "candidate_offset": packet.candidate_offset,
        "candidate_limit": packet.candidate_limit,
        "returned_count": len(packet.candidate_refs),
        "candidate_total": packet.candidate_total,
        "has_more": next_offset is not None,
        "next_candidate_offset": next_offset,
        "next_request": next_request,
    }


async def _context_for_session(session_id: str, village_name: str = "") -> Any | None:
    try:
        from app.infrastructure.evidence_runtime.context_hydration import prepare_evidence_context

        return await prepare_evidence_context(
            session_id,
            village_name=village_name,
            include_reports=True,
        )
    except Exception:
        return None


async def query_evidence_graph_impl(
    session_id: str,
    query: str,
    village_name: str = "",
    candidate_offset: int = 0,
    candidate_limit: int = 12,
) -> dict[str, Any]:
    result = await _unified_evidence_for_query(
        session_id,
        query,
        village_name,
        candidate_offset=candidate_offset,
        candidate_limit=candidate_limit,
    )
    if result is None or result.evidence_packet is None:
        return {"success": False, "error": "session evidence context unavailable"}
    payload = result.evidence_packet.model_dump(mode="json")
    payload["evidence_bundle"] = result.evidence_bundle.model_dump(mode="json")
    payload["spatial_cognition"] = (
        result.spatial_cognition.model_dump(mode="json")
        if result.spatial_cognition is not None
        else None
    )
    context = await _context_for_session(session_id, village_name)
    mode = str(getattr(context, "world_model_mode", "off") or "off").strip().lower()
    if mode in {"prefer_v2", "v2_only"}:
        payload["geometry_policy"] = (
            "geometry is DATA-catalog-authoritative; use only returned opaque "
            "resource_ref/representation_ref/geometry_ref values and let GROUND "
            "resolve the selected representation"
        )
    elif mode == "shadow":
        payload["geometry_policy"] = (
            "shadow mode: legacy Bundle geometry is returned for comparison only; "
            "new decisions must carry DATA resource/representation refs"
        )
    else:
        payload["geometry_policy"] = (
            "legacy compatibility mode: geometry may be read from a returned "
            "Bundle feature ref; new code should prefer DATA refs"
        )
    payload["pagination"] = _pagination_metadata(
        result.evidence_packet,
        tool_name="query_evidence_graph",
        arguments={
            "session_id": session_id,
            "query": query,
            "village_name": village_name,
        },
    )
    return budget_check(payload, hard_limit=6000)


async def _unified_evidence_for_query(
    session_id: str,
    query: str,
    village_name: str,
    *,
    entity_scope: list[str] | None = None,
    required_facts: list[str] | None = None,
    candidate_offset: int = 0,
    candidate_limit: int = 12,
) -> ExplorationResult | None:
    """Use the same multi-source retrieval boundary as HTTP and workflow code."""
    context = await _context_for_session(session_id, village_name)
    if context is None:
        return None
    from app.modules.evidence.application import (
        extract_spatial_query_spec,
        retrieve_evidence,
    )

    spatial_spec, parser_trace = await extract_spatial_query_spec(
        context,
        query,
        scope_key="llm-tool-evidence-query",
    )
    result = await retrieve_evidence(
        ExplorationRequest(
            run_id=session_id,
            request_type="spatial_lookup",
            query=query,
            stage="GROUND",
            dimension_key="location",
            entity_scope=list(entity_scope or []),
            required_facts=list(required_facts or []),
            query_purpose="fact_check",
            candidate_offset=max(0, int(candidate_offset or 0)),
            candidate_limit=min(64, max(1, int(candidate_limit or 12))),
        ),
        session_id,
        village_name=village_name,
        spatial_spec=spatial_spec,
    )
    if result.evidence_packet is not None:
        result.evidence_packet.query_trace.append(parser_trace)
    return result


@tool
async def query_evidence_graph(
    session_id: str = "",
    query: str = "",
    village_name: str = "",
    candidate_offset: int = 0,
    candidate_limit: int = 12,
    state: Annotated[Optional[dict[str, Any]], InjectedState()] = None,
) -> str:
    """查询有界证据图：L1 范围、设施 BSM、KG 实体和拓扑关系。

    若返回 pagination.has_more=true，必须按 pagination.next_request 继续查询，
    直到 has_more=false；当前页不得视为完整候选集。
    """
    if not session_id and state:
        session_id = str(state.get("session_id", "") or "")
    return tool_reply(
        await query_evidence_graph_impl(
            session_id,
            query,
            village_name,
            candidate_offset=candidate_offset,
            candidate_limit=candidate_limit,
        )
    )


async def query_facility_bsms_impl(
    session_id: str,
    village_name: str,
    label: str,
    role: str = "facility",
    candidate_offset: int = 0,
    candidate_limit: int = 12,
) -> dict[str, Any]:
    query = f"{village_name}{label}的BSM".strip()
    result = await _unified_evidence_for_query(
        session_id,
        query,
        village_name,
        entity_scope=[{
            "facility": "facilities",
            "landmark": "facilities",
            "hazard": "hazards",
            "road": "roads",
            "water": "waters",
            "parcel": "parcels",
            "zone": "zones",
        }.get((role or "facility").strip().casefold(), "facilities")],
        required_facts=["BSM"],
        candidate_offset=candidate_offset,
        candidate_limit=candidate_limit,
    )
    if result is None or result.evidence_packet is None:
        return {"success": False, "error": "session evidence context unavailable"}
    packet = result.evidence_packet
    refs = list(packet.candidate_refs or [])
    candidate_end = packet.candidate_offset + len(refs)
    has_unseen_candidates = (
        packet.next_candidate_offset is not None
        or candidate_end < packet.candidate_total
    )
    status = (
        "ambiguous"
        if refs and (len(refs) != 1 or has_unseen_candidates)
        else "resolved"
        if len(refs) == 1 and not has_unseen_candidates
        else "unresolved"
    )
    payload = {
            "success": True,
            "status": status,
            "mention": label,
            "unresolved_reason": (
                "candidate_page_incomplete"
                if has_unseen_candidates
                else "" if status == "resolved" else status
            ),
            "candidate_total": packet.candidate_total,
            "candidate_offset": packet.candidate_offset,
            "candidate_limit": packet.candidate_limit,
            "candidates_truncated": packet.candidates_truncated,
            "next_candidate_offset": packet.next_candidate_offset,
            "pagination": _pagination_metadata(
                packet,
                tool_name="query_facility_bsms",
                arguments={
                    "session_id": session_id,
                    "village_name": village_name,
                    "label": label,
                    "role": role,
                },
            ),
            "query_trace": packet.query_trace[-12:],
            "evidence_bundle": result.evidence_bundle.model_dump(mode="json"),
            "candidates": [
                {
                    "entity_ref": candidate.entity_refs[0] if candidate.entity_refs else "",
                    "canonical_name": candidate.identity.canonical_name or label,
                    "aliases": candidate.identity.aliases[:12],
                    "entity_type": candidate.identity.entity_type or role,
                    "role": candidate.identity.role or role,
                    "feature_bsm": candidate.identity.bundle_feature_bsm,
                    "geometry_ref": candidate.geometry_ref,
                    "source_feature_id": candidate.identity.source_feature_id,
                    "source_layer": candidate.identity.source_layer,
                    "anchor_bsms": [],
                    "related_parcel_bsms": candidate.related_parcel_bsms[:24],
                    "relation_refs": candidate.relation_refs[:12],
                    "evidence_refs": candidate.provenance_refs[:12],
                    "retrieval_score": candidate.retrieval_score,
                    "source_authority_score": candidate.source_authority_score,
                    "semantic_match_score": candidate.semantic_match_score,
                    "spatial_support_score": candidate.spatial_support_score,
                    "external_support_score": candidate.external_support_score,
                    "selection_confidence": candidate.selection_confidence,
                }
                for candidate in refs
            ],
        }
    return budget_check(payload)


@tool
async def query_facility_bsms(
    session_id: str = "",
    village_name: str = "",
    label: str = "",
    role: str = "facility",
    candidate_offset: int = 0,
    candidate_limit: int = 12,
    state: Annotated[Optional[dict[str, Any]], InjectedState()] = None,
) -> str:
    """按村域和设施名称查询已验证的设施 BSM，不接受 LLM 自造身份。

    若返回 pagination.has_more=true，必须按 pagination.next_request 继续查询，
    直到 has_more=false；当前页不得视为完整候选集。
    """
    if not session_id and state:
        session_id = str(state.get("session_id", "") or "")
    return tool_reply(
        await query_facility_bsms_impl(
            session_id,
            village_name,
            label,
            role,
            candidate_offset=candidate_offset,
            candidate_limit=candidate_limit,
        )
    )


async def data_geometry_by_ref_impl(
    session_id: str,
    geometry_ref: str,
) -> dict[str, Any]:
    """Resolve one opaque DATA geometry ref for V2 LLM inspection.

    The model cannot submit a new coordinate or field selector.  The ref must
    already occur in the normalized catalog snapshot (source, resource,
    representation, or geometry identity); GROUND remains the execution
    authority and re-resolves it before producing a planned layer.
    """
    context = await _context_for_session(session_id)
    catalog = getattr(context, "data_resource_catalog", None) if context else None
    ref = str(geometry_ref or "").strip()
    if catalog is None or not ref:
        return {"success": False, "error": "DATA catalog or geometry_ref unavailable"}
    snapshot = getattr(catalog, "snapshot", None)
    try:
        from app.data.admission import (
            assert_current_world_catalog,
            build_admission_index,
        )

        assert_current_world_catalog(snapshot)
        admission_index = build_admission_index(snapshot)
    except (TypeError, ValueError):
        return {
            "success": False,
            "error": "DATA catalog current-world admission is not valid",
        }
    features = list(getattr(snapshot, "features", ()) or ())
    representations = list(getattr(snapshot, "representations", ()) or ())
    allowed = set()
    bare_counts: dict[str, int] = {}
    for feature in features:
        source_ref = str(getattr(feature, "source_feature_ref", "") or "")
        bare_counts[source_ref] = bare_counts.get(source_ref, 0) + 1
    for feature in features:
        feature_key = (
            str(getattr(feature, "dataset_ref", "") or ""),
            str(getattr(feature, "source_feature_ref", "") or ""),
        )
        if feature_key not in admission_index.feature_keys:
            continue
        resource_ref = (
            f"resource:{feature_key[0]}:{feature_key[1]}"
        )
        allowed.update(
            str(value).strip()
            for value in (
                feature_key[1] if bare_counts.get(feature_key[1]) == 1 else "",
                resource_ref,
            )
            if str(value or "").strip()
        )
    for representation in representations:
        if str(getattr(representation, "representation_ref", "") or "") not in admission_index.representation_refs:
            continue
        allowed.update(
            str(value).strip()
            for value in (
                getattr(representation, "representation_ref", ""),
                getattr(representation, "resource_ref", ""),
                getattr(representation, "geometry_ref", ""),
            )
            if str(value or "").strip()
        )
    if ref not in allowed:
        return {"success": False, "error": "geometry_ref is not present in DATA catalog", "geometry_ref": ref}
    geometry = catalog.resolve_geometry(
        resource_ref=ref,
        geometry_ref=ref,
        representation_ref=ref,
    )
    if geometry is None:
        return {"success": False, "error": "DATA ref has no executable geometry", "geometry_ref": ref}
    return budget_check(
        {
            "success": True,
            "geometry_ref": ref,
            "geometry_authority": "data_resource_catalog",
            "geometry": geometry,
        },
        hard_limit=6000,
    )


@tool
async def data_geometry_by_ref(
    session_id: str = "",
    geometry_ref: str = "",
    state: Annotated[Optional[dict[str, Any]], InjectedState()] = None,
) -> str:
    """仅按 EvidencePacket 已返回的 DATA opaque ref 读取几何。"""
    if not session_id and state:
        session_id = str(state.get("session_id", "") or "")
    return tool_reply(await data_geometry_by_ref_impl(session_id, geometry_ref))


__all__ = [
    "query_evidence_graph",
    "query_evidence_graph_impl",
    "query_facility_bsms",
    "query_facility_bsms_impl",
    "data_geometry_by_ref",
    "data_geometry_by_ref_impl",
]
