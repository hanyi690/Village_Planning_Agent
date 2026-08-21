"""Optional external evidence retriever.

External results are deliberately text-only.  This adapter cannot create a
bundle feature, BSM, entity, topology relation, or execution geometry.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.contracts.workflow.repair import ExternalSearchRequest, SearchFailure
from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "external-v1"


def _failure_code(exc: Exception) -> str:
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "provider_timeout"
    if "budget" in text or "cost" in text:
        return "budget_exceeded"
    return "unexpected"


async def retrieve_from_external(
    session_id: str,
    *,
    provider: Any,
    policy: ExternalSearchPolicy,
    dimension_key: str = "",
    query: str = "",
    entity_scope: Iterable[str] = (),
    required_facts: Iterable[str] = (),
    source_refs: Iterable[str] = (),
) -> tuple[list[EvidenceFact], list[EvidenceSource], dict[str, Any]]:
    """Run one bounded, policy-gated external request."""
    decision = policy.evaluate(dimension_key, query)
    trace: dict[str, Any] = {
        "step": "external_policy",
        "allowed": decision.allowed,
        "code": str(decision.code),
    }
    if not decision.allowed:
        trace.update({
            "status": "blocked",
            "reason": decision.reason,
        })
        return [], [], trace

    request = ExternalSearchRequest(
        query_purpose=query or dimension_key or "external_evidence",
        entity_scope=[str(item) for item in entity_scope if str(item).strip()][:8],
        search_mode="light",
        result_limit=5,
        content_mode="summary",
        parent_refs=[str(item) for item in source_refs if str(item).strip()][:8],
        idempotency_key=f"{session_id}:{dimension_key}:{query}",
    )
    try:
        result = await provider.search(request)
    except Exception as exc:  # noqa: BLE001 - provider is an injected boundary
        trace.update(
            {
                "status": "failed",
                "failure": SearchFailure(
                    code=_failure_code(exc),
                    message=str(exc),
                    retryable=True,
                    local_fallback_allowed=False,
                ).model_dump(mode="json"),
            }
        )
        logger.warning("[external_retriever] provider failed: %s", exc)
        return [], [], trace

    status = str(getattr(result, "retrieval_status", "unresolved") or "unresolved")
    trace.update(
        {
            "status": status,
            "provider": str(getattr(result, "provider", "") or ""),
            "request_id": str(getattr(result, "request_id", "") or ""),
        }
    )
    if status != "success":
        failure = getattr(result, "failure", None)
        if failure is not None:
            trace["failure"] = failure.model_dump(mode="json")
        return [], [], trace

    provider_name = str(getattr(result, "provider", "external") or "external")
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    for index, record in enumerate(list(getattr(result, "result_records", []) or [])[:5]):
        if not isinstance(record, dict):
            continue
        text = str(record.get("text") or record.get("content") or "").strip()
        if not text:
            continue
        source = str(record.get("source") or record.get("url") or provider_name)
        url = str(record.get("url") or "")
        reference = f"external:{provider_name}:{index}:{source}"
        facts.append(
            EvidenceFact(
                statement=text[:1200],
                confidence=max(0.0, min(1.0, float(record.get("confidence", 0.5) or 0.5))),
                source_refs=[value for value in (source, url) if value],
                fact_type="external_claim",
                evidence_span=text[:400],
                source_locator=url or source,
                support_relation="external_reference",
                status="needs_review",
                evidence_role="external_context",
                source_kind="external_search",
                spatial_granularity="none",
                planning_use="context",
            )
        )
        sources.append(
            EvidenceSource(
                source_type="external",
                reference=reference,
                confidence=facts[-1].confidence,
            )
        )
    trace["claim_count"] = len(facts)
    return facts, sources, trace


__all__ = ["RETRIEVER_VERSION", "retrieve_from_external"]
