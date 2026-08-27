"""POST /sessions/{session_id}/evidence/query transport."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.v1.contracts import EvidenceQueryRequest, EvidenceQueryResponse
from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.infrastructure.logging import get_logger


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])
logger = get_logger(__name__)


@router.post(
    "/sessions/{session_id}/evidence/query",
    response_model=EvidenceQueryResponse,
)
async def query_session_evidence(
    session_id: str,
    request: EvidenceQueryRequest,
    transport_request: Request = None,
) -> EvidenceQueryResponse:
    """Answer a spatial question through one bounded evidence boundary.

    The endpoint is read-only from the user's perspective.  It may hydrate
    the in-process session context, but the response is composed from the
    report/L1, session KG, bundle and optional external retrieval pipeline;
    geometry remains bundle-authoritative and is returned only as a feature
    reference inside ``EvidencePacket``.
    """
    from app.evidence.retrieval.context_hydration import prepare_evidence_context
    from app.evidence.retrieval.evidence_service import retrieve_evidence

    external_port = None
    owned_external_provider = False
    try:
        context = await prepare_evidence_context(
            session_id,
            village_name=request.village_name,
            include_reports=True,
            refresh=False,
        )

        village_name = request.village_name or str(
            getattr(context, "village_name", "") or ""
        )
        exploration_request = ExplorationRequest(
            run_id=session_id,
            request_type=request.request_type,
            query=request.query,
            context_refs=list(request.context_refs),
            stage=request.stage,
            dimension_key=request.dimension_key,
            query_purpose=request.query_purpose,
            questions=list(request.questions),
            required_facts=list(request.required_facts),
            entity_scope=list(request.entity_scope),
            candidate_offset=request.candidate_offset,
            candidate_limit=request.candidate_limit,
        )
        spatial_spec = None
        spatial_parse_trace: dict[str, object] | None = None
        if request.request_type == "spatial_lookup" or request.entity_scope:
            from app.evidence.retrieval.evidence_service import (
                extract_spatial_query_spec,
            )

            spatial_spec, spatial_parse_trace = await extract_spatial_query_spec(
                context,
                request.query,
            )
        external_port = None
        external_policy = None
        if request.include_external:
            from app.infrastructure.search.provider_registry import get_configured_external_provider
            from app.evidence.retrieval.context_hydration import build_external_evidence_policy

            app_state = getattr(
                getattr(transport_request, "app", None),
                "state",
                None,
            )
            external_port = getattr(app_state, "evidence_external_provider", None)
            if external_port is None:
                external_port = get_configured_external_provider(request.external_categories)
                owned_external_provider = True
            external_policy = build_external_evidence_policy(
                request.dimension_key,
                request.external_categories,
            )
        result = await retrieve_evidence(
            exploration_request,
            session_id,
            village_name=village_name,
            external_port=external_port,
            external_policy=external_policy,
            spatial_spec=spatial_spec,
        )
        packet = result.evidence_packet
        evidence_bundle = result.evidence_bundle
        if packet is not None:
            if spatial_parse_trace is not None:
                packet.query_trace.append(spatial_parse_trace)
        return EvidenceQueryResponse(
            session_id=session_id,
            request=request.query,
            evidence_bundle=evidence_bundle,
            spatial_cognition=result.spatial_cognition,
            evidence_packet=packet,
        )
    except Exception as exc:  # noqa: BLE001 - transport boundary
        raise HTTPException(
            status_code=503,
            detail=f"evidence query unavailable: {exc}",
        ) from exc
    finally:
        if owned_external_provider and external_port is not None:
            close = getattr(external_port, "close", None)
            if callable(close):
                try:
                    result = close()
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:  # noqa: BLE001 - cleanup is best effort
                    logger.warning(
                        "[evidence.query] external provider cleanup failed: %s",
                        exc,
                    )


__all__ = ["query_session_evidence", "router"]
