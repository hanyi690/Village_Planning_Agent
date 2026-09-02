"""Deterministic construction of the immutable Evidence acquisition plan."""

from __future__ import annotations

import hashlib
import json

from app.contracts.evidence.evidence_contracts import ExplorationRequest
from app.contracts.evidence.policy_contracts import resolve_policy
from app.contracts.evidence.query_plan_contracts import (
    EvidenceBudget,
    EvidencePageStrategy,
    EvidenceProviderRoute,
    EvidenceQueryPlanV1,
)
from app.infrastructure.evidence_runtime.retriever_router import RetrieverKind, route_request


_ROUTE_METADATA: dict[RetrieverKind, tuple[str, str, str]] = {
    RetrieverKind.LOCAL_TEXT: ("local_text", "source_record", "source_evidence"),
    RetrieverKind.RAG: ("rag", "rag", "semantic_text"),
    RetrieverKind.REPORT: ("report", "report", "report_evidence"),
    RetrieverKind.KG: ("current_world", "world_model", "world_model_query"),
    RetrieverKind.DATA_CATALOG: ("data_catalog", "data", "local_spatial_evidence"),
    RetrieverKind.ARTIFACT: ("artifact", "artifact", "artifact_evidence"),
    RetrieverKind.INTEGRITY: ("integrity", "data", "integrity_check"),
    RetrieverKind.EXTERNAL: ("external", "external", "external_provider"),
}


def request_fingerprint(request: ExplorationRequest) -> str:
    """Return the request-only digest used as the plan's semantic input."""

    payload = request.model_dump(mode="json")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _terms(request: ExplorationRequest) -> list[str]:
    values = [
        request.query.strip(),
        *request.questions,
        *request.required_facts,
        *request.evidence_gaps_to_resolve,
        *(item.statement for item in request.requirements if item.required),
    ]
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value).split())
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:8]


def _route_ref(retriever: RetrieverKind, query: str, scope: tuple[str, ...]) -> str:
    raw = json.dumps(
        {"retriever": retriever.value, "query": query, "scope": scope},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"evidence.route.{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def build_query_plan(
    request: ExplorationRequest,
    *,
    project_wide: bool = False,
) -> EvidenceQueryPlanV1:
    """Build the formal immutable plan while retaining route-level execution data."""

    terms = _terms(request)
    base_query = "；".join(terms) or request.dimension_key or request.request_type
    required = tuple(dict.fromkeys([
        *request.required_facts,
        *request.questions,
        *(item.statement for item in request.requirements if item.required),
    ]))
    scope = tuple(dict.fromkeys(request.entity_scope))
    source_refs = tuple(dict.fromkeys(request.context_refs))
    required_policies = {
        str(item.policy_ref).casefold()
        for item in request.requirements
        if item.required
    }
    acquisition_core = bool(required_policies.intersection({
        "road_identity.v1",
        "location_identity_support.v1",
        "facility_existence.v1",
    }))
    frozen_external_required = any(
        item.required
        and any(
            str(family).casefold() in {"external", "external_map_cache", "map_cache"}
            for family in item.source_families
        )
        for item in request.requirements
    )
    routes: list[EvidenceProviderRoute] = []
    for kind in route_request(request, project_wide=project_wide):
        provider, source_family, capability = _ROUTE_METADATA[kind]
        routes.append(
            EvidenceProviderRoute(
                route_ref=_route_ref(kind, base_query, scope),
                provider=provider,
                retriever=kind.value,
                source_family=source_family,
                capability=capability,
                query=base_query,
                entity_scope=scope,
                required_facts=required,
                source_refs=source_refs,
                required_for_acquisition=(
                    (
                        kind in {RetrieverKind.DATA_CATALOG, RetrieverKind.KG}
                        or (kind == RetrieverKind.EXTERNAL and frozen_external_required)
                    )
                    if acquisition_core
                    else kind in {
                        RetrieverKind.DATA_CATALOG,
                        RetrieverKind.KG,
                        RetrieverKind.LOCAL_TEXT,
                    } or (kind == RetrieverKind.EXTERNAL and frozen_external_required)
                ),
            )
        )
    policy_refs = tuple(dict.fromkeys(
        f"{policy.policy_ref}.v{policy.policy_version}"
        for policy in (
            resolve_policy(item.policy_ref)
            for item in request.requirements
            if item.policy_ref
        )
    ))
    policy_ref = policy_refs[0] if policy_refs else "source_semantic_support.v1"
    policy_version = policy_ref.rsplit(".v", 1)[1] if ".v" in policy_ref else "1"
    return EvidenceQueryPlanV1(
        requirement_refs=tuple(item.requirement_ref for item in request.requirements),
        normalized_query=base_query,
        subject_refs=scope,
        scope=scope,
        provider_routes=tuple(routes),
        page_strategy=EvidencePageStrategy(
            mode=(
                "cursor"
                if any(item.retriever == RetrieverKind.EXTERNAL.value for item in routes)
                else "single_page"
            ),
            page_size=min(max(request.candidate_limit, 1), 1000),
            hard_page_limit=1,
        ),
        dedupe_key=request_fingerprint(request),
        budget=EvidenceBudget(budget_class="local"),
        completion_condition="required_routes_complete",
        policy_ref=policy_ref,
        policy_version=policy_version,
        policy_refs=policy_refs or (policy_ref,),
    )


__all__ = ["build_query_plan", "request_fingerprint"]
