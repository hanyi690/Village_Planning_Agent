"""Read-only adapter from frozen external observations into Evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.contracts.evidence.external_observation_contracts import ExternalObservationSnapshot
from app.contracts.evidence.query_plan_contracts import EvidenceProviderRoute, EvidenceQueryPlanV1
from app.infrastructure.evidence_runtime.acquisition_executor import (
    AcquisitionRouteExecutor,
    AcquisitionRouteResult,
)


@dataclass(frozen=True)
class FrozenCacheReadResult:
    """Facts plus the typed current cache-read route result."""

    route_result: AcquisitionRouteResult
    facts: tuple[EvidenceFact, ...] = ()
    sources: tuple[EvidenceSource, ...] = ()
    trace: dict[str, Any] | None = None


def _origin_completeness(snapshot: ExternalObservationSnapshot) -> str:
    statuses = {
        str(item.status).upper()
        for item in snapshot.provider_attempts
    }
    if not statuses:
        return "unknown"
    if statuses.intersection({
        "PARTIAL",
        "FAILED_RETRYABLE",
        "FAILED_PERMANENT",
        "QUOTA_EXHAUSTED",
        "TIMEOUT",
        "AUTH_FAILED",
        "FAILED",
    }):
        return "incomplete"
    if statuses.issubset({"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"}):
        return "complete"
    return "unknown"


def materialize_frozen_cache_result(
    context: Any,
    plan: EvidenceQueryPlanV1,
    route: EvidenceProviderRoute,
    *,
    facts: Iterable[EvidenceFact],
    sources: Iterable[EvidenceSource],
    trace: dict[str, Any] | None = None,
) -> AcquisitionRouteResult:
    """Convert an already-read frozen snapshot into a typed route result."""

    facts = tuple(facts)
    sources = tuple(sources)
    snapshot = getattr(context, "external_observation_snapshot", None)
    if not isinstance(snapshot, ExternalObservationSnapshot):
        return AcquisitionRouteExecutor(plan).complete_route(
            route,
            status="NOT_ATTEMPTED",
            reason_code="frozen_cache_unavailable",
            attempt_kind="frozen_cache",
            provider_override="frozen_cache",
            metadata={"origin_completeness": "unknown"},
        )
    executor = AcquisitionRouteExecutor(plan)
    return executor.complete_route(
        route,
        status="SUCCESS_NONEMPTY" if facts or sources else "SUCCESS_EMPTY",
        facts=facts,
        sources=sources,
        reason_code="frozen_cache_read_complete",
        attempt_kind="frozen_cache",
        provider_override="frozen_cache",
        metadata={
            "origin_completeness": _origin_completeness(snapshot),
            "cache_snapshot_ref": snapshot.snapshot_id,
            "cache_digest": snapshot.digest,
            "cache_only": True,
            "trace_status": str((trace or {}).get("status") or ""),
        },
    )


def read_frozen_external_cache(
    context: Any,
    plan: EvidenceQueryPlanV1,
    route: EvidenceProviderRoute,
    *,
    query: str = "",
    entity_scope: Iterable[str] = (),
    limit: int = 32,
) -> FrozenCacheReadResult:
    """Read the cache and return facts plus explicit frozen-cache lineage."""

    from app.infrastructure.evidence_runtime.retrievers.cached_map_retriever import (
        retrieve_from_cached_map,
    )

    facts, sources, trace = retrieve_from_cached_map(
        context,
        query=query,
        entity_scope=entity_scope,
        limit=limit,
    )
    return FrozenCacheReadResult(
        route_result=materialize_frozen_cache_result(
            context,
            plan,
            route,
            facts=facts,
            sources=sources,
            trace=trace,
        ),
        facts=tuple(facts),
        sources=tuple(sources),
        trace=trace,
    )


__all__ = [
    "FrozenCacheReadResult",
    "materialize_frozen_cache_result",
    "read_frozen_external_cache",
]
