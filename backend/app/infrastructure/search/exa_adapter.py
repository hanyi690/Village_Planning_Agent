"""Structured fake ExternalSearchPort adapter (no real Exa SDK, no network)."""

from __future__ import annotations

import hashlib

from app.contracts.ports.external_search import ExternalSearchPort
from app.contracts.workflow.repair import (
    ExternalSearchRequest,
    ExternalSearchResult,
    SearchFailure,
)
from app.evidence.model.base import JsonObject

PROVIDER_NAME = "fake-exa"

DEFAULT_CORPUS: list[JsonObject] = [
    {
        "content": "常驻人口约 800 人，户籍人口 1200 人",
        "source": "fake-gazetteer",
        "url": "https://example.invalid/population",
        "published_at": "2026-01-01",
        "confidence": 0.8,
        "domain": "statistics",
        "category": "population",
        "keywords": ["人口", "population"],
    },
    {
        "content": "主导产业为农产品加工与乡村旅游",
        "source": "fake-industry-report",
        "url": "https://example.invalid/industry",
        "published_at": "2026-02-01",
        "confidence": 0.7,
        "domain": "economics",
        "category": "industry",
        "keywords": ["产业", "industry"],
    },
    {
        "content": "村内主要道路为两车道，对外连通省道",
        "source": "fake-transport-notes",
        "url": "https://example.invalid/transport",
        "published_at": "2026-01-15",
        "confidence": 0.6,
        "domain": "planning",
        "category": "transport",
        "keywords": ["道路", "transport", "交通"],
    },
    {
        "content": "生活用水来自村内集中供水站",
        "source": "fake-water-notes",
        "url": "https://example.invalid/water",
        "published_at": "2026-01-20",
        "confidence": 0.6,
        "domain": "planning",
        "category": "water",
        "keywords": ["供水", "water"],
    },
]


class FakeExternalSearchAdapter:
    """Deterministic offline substitute for the future real Exa adapter.

    Success, ``empty``, ``provider_unavailable``, ``timeout`` and
    ``budget_exceeded`` outcomes are typed ``ExternalSearchResult`` values
    selected from constructor config plus request fields; no exceptions are
    raised for gated or failed searches.
    """

    def __init__(
        self,
        enabled_domains: list[str] | None = None,
        enabled_categories: list[str] | None = None,
        max_cost: float | None = None,
        provider_unavailable: bool = False,
        simulate_timeout: bool = False,
        corpus: list[JsonObject] | None = None,
    ) -> None:
        self.enabled_domains = list(enabled_domains or [])
        self.enabled_categories = list(enabled_categories or [])
        self.max_cost = max_cost
        self.provider_unavailable = provider_unavailable
        self.simulate_timeout = simulate_timeout
        self.corpus = list(corpus if corpus is not None else DEFAULT_CORPUS)

    async def search(self, request: ExternalSearchRequest) -> ExternalSearchResult:
        """Return a typed success or typed failure, never a bare exception."""
        if self.provider_unavailable:
            return self._failure(request, "unavailable", "provider_unavailable", "provider offline", True)
        if self.simulate_timeout:
            return self._failure(request, "timeout", "provider_timeout", "provider timed out", True)

        cost = self._estimated_cost(request)
        if self.max_cost is not None and cost > self.max_cost:
            return self._failure(
                request,
                "budget_exceeded",
                "budget_exceeded",
                f"estimated cost {cost:.3f} exceeds max {self.max_cost:.3f}",
                True,
            )

        allowed = self._allowable_records(request)
        if allowed is None:
            return self._failure(request, "empty", "empty", "no enabled domains or categories configured", False)
        if not allowed:
            return self._failure(request, "empty", "empty", "requested domains/categories not allowed", False)

        records = self._match(request, allowed)
        if not records:
            return self._failure(request, "empty", "empty", "no matching records", False)

        limit = int(request.result_limit or 0)
        return ExternalSearchResult(
            provider=PROVIDER_NAME,
            request_id=self._request_id(request),
            resolved_search_mode=str(request.search_mode or "light"),
            result_records=records[:limit] if limit > 0 else records,
            retrieval_status="success",
            latency_ms=self._latency_ms(request),
            cost={"estimated_cost": round(cost, 3), "provider": PROVIDER_NAME},
        )

    def _allowable_records(self, request: ExternalSearchRequest) -> list[JsonObject] | None:
        domains = self.enabled_domains
        categories = self.enabled_categories
        if not domains and not categories:
            return None
        requested_domains = list(request.allowed_domains or [])
        requested_categories = list(request.allowed_categories or [])
        if requested_domains and not any(domain in domains for domain in requested_domains):
            return []
        if requested_categories and not any(category in categories for category in requested_categories):
            return []
        allowed = []
        for record in self.corpus:
            if domains and str(record.get("domain", "")) not in domains:
                continue
            if categories and str(record.get("category", "")) not in categories:
                continue
            allowed.append(record)
        return allowed

    def _match(self, request: ExternalSearchRequest, records: list[JsonObject]) -> list[JsonObject]:
        query = str(request.query_purpose or "").lower()
        scope = [str(item).lower() for item in (request.entity_scope or [])]
        if not query and not scope:
            return list(records)
        matched = []
        for record in records:
            keywords = [str(keyword).lower() for keyword in (record.get("keywords") or [])]
            if not keywords:
                continue
            if query and any(keyword in query for keyword in keywords):
                matched.append(record)
                continue
            if scope and any(any(keyword in item for keyword in keywords) for item in scope):
                matched.append(record)
        return matched

    def _estimated_cost(self, request: ExternalSearchRequest) -> float:
        budget = dict(request.budget or {})
        if budget.get("estimated_cost") is not None:
            try:
                return float(budget["estimated_cost"])
            except (TypeError, ValueError):
                pass
        return 0.01 * len(str(request.query_purpose or ""))

    def _request_id(self, request: ExternalSearchRequest) -> str:
        key = str(request.idempotency_key or "")
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]

    def _latency_ms(self, request: ExternalSearchRequest) -> int:
        return 20 + (len(str(request.query_purpose or "")) * 7) % 80

    def _failure(
        self,
        request: ExternalSearchRequest,
        status: str,
        code: str,
        message: str,
        retryable: bool,
    ) -> ExternalSearchResult:
        return ExternalSearchResult(
            provider=PROVIDER_NAME,
            request_id=self._request_id(request),
            resolved_search_mode=str(request.search_mode or "light"),
            retrieval_status=status,
            latency_ms=self._latency_ms(request),
            cost={"estimated_cost": round(self._estimated_cost(request), 3), "provider": PROVIDER_NAME},
            failure=SearchFailure(
                code=code,
                message=message,
                retryable=retryable,
                local_fallback_allowed=True,
            ),
        )


__all__ = ["DEFAULT_CORPUS", "FakeExternalSearchAdapter", "PROVIDER_NAME"]
