"""External search adapters for the centralized evidence runtime."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from app.contracts.workflow.repair import (
    ExternalSearchRequest,
    ExternalSearchResult,
    SearchFailure,
)

EXA_PROVIDER_NAME = "exa"
EXA_DEFAULT_ENDPOINT = "https://api.exa.ai/search"

class UnavailableExternalSearchAdapter:
    """Typed no-network fallback when deployment has no external provider."""

    version = "external-unavailable-v1"

    async def search(self, request: ExternalSearchRequest) -> ExternalSearchResult:
        return ExternalSearchResult(
            provider="unconfigured",
            request_id=hashlib.sha1(
                str(request.idempotency_key or "").encode("utf-8")
            ).hexdigest()[:12],
            resolved_search_mode=str(request.search_mode or "light"),
            retrieval_status="unavailable",
            failure=SearchFailure(
                code="provider_unavailable",
                message="no external evidence provider is configured",
                retryable=False,
                local_fallback_allowed=True,
            ),
        )


class ExaHTTPExternalSearchAdapter:
    """Bounded Exa HTTP adapter behind the provider-neutral search port.

    The adapter owns its client unless one is injected by the deployment.  It
    never turns a remote result into a geometry, BSM, or KG entity; callers
    receive text evidence only.  ``close`` is explicit so the application
    lifespan can reclaim sockets when a worker is stopped or resumed.
    """

    version = "exa-http-v1"

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = EXA_DEFAULT_ENDPOINT,
        timeout_s: float = 8.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not str(api_key or "").strip():
            raise ValueError("Exa API key is required")
        self.api_key = str(api_key).strip()
        self.endpoint = str(endpoint or EXA_DEFAULT_ENDPOINT).strip()
        self.timeout_s = max(1.0, min(float(timeout_s), 30.0))
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_s),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        self._owns_client = client is None

    async def search(self, request: ExternalSearchRequest) -> ExternalSearchResult:
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "query": str(request.query_purpose or "external_evidence")[:800],
            "numResults": max(1, min(int(request.result_limit or 5), 5)),
            "contents": {
                "highlights": {
                    "maxCharacters": 1200,
                }
            },
        }
        domains = [str(item).strip() for item in request.allowed_domains if str(item).strip()]
        if domains:
            payload["includeDomains"] = domains[:8]
        try:
            response = await self._client.post(
                self.endpoint,
                headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            records = self._records(body)
            status = "success" if records else "empty"
            return ExternalSearchResult(
                provider=EXA_PROVIDER_NAME,
                request_id=self._request_id(request),
                resolved_search_mode=str(request.search_mode or "light"),
                result_records=records,
                retrieval_status=status,
                latency_ms=self._latency_ms(started),
                cost={"provider": EXA_PROVIDER_NAME, "result_count": len(records)},
                failure=None if records else SearchFailure(
                    code="no_results",
                    message="Exa returned no usable text results",
                    retryable=False,
                    local_fallback_allowed=True,
                ),
            )
        except httpx.TimeoutException as exc:
            return self._failure(request, "timeout", "provider_timeout", str(exc), True, started)
        except httpx.HTTPStatusError as exc:
            status_code = int(exc.response.status_code)
            if status_code in {401, 403}:
                return self._failure(
                    request,
                    "failed",
                    "provider_unauthorized",
                    f"Exa HTTP {status_code}",
                    False,
                    started,
                )
            if status_code == 429:
                return self._failure(
                    request,
                    "failed",
                    "provider_rate_limited",
                    "Exa HTTP 429",
                    True,
                    started,
                )
            return self._failure(
                request,
                "failed",
                "unexpected",
                f"Exa HTTP {status_code}",
                status_code >= 500,
                started,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return self._failure(request, "failed", "unexpected", str(exc), True, started)

    def _records(self, body: Any) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        records: list[dict[str, Any]] = []
        for item in list(body.get("results") or [])[:5]:
            if not isinstance(item, dict):
                continue
            highlights = item.get("highlights") or []
            if isinstance(highlights, list):
                text = "\n".join(str(value).strip() for value in highlights if str(value).strip())
            else:
                text = str(highlights or item.get("text") or "").strip()
            if not text:
                text = str(item.get("text") or "").strip()
            if not text:
                continue
            records.append(
                {
                    "text": text[:1200],
                    "source": str(item.get("title") or item.get("url") or EXA_PROVIDER_NAME),
                    "url": str(item.get("url") or ""),
                    "published_at": str(item.get("publishedDate") or ""),
                    "confidence": 0.5,
                }
            )
        return records

    def _request_id(self, request: ExternalSearchRequest) -> str:
        return hashlib.sha1(
            str(request.idempotency_key or "").encode("utf-8")
        ).hexdigest()[:12]

    def _latency_ms(self, started: float) -> int:
        return max(0, int((time.perf_counter() - started) * 1000))

    def _failure(
        self,
        request: ExternalSearchRequest,
        status: str,
        code: str,
        message: str,
        retryable: bool,
        started: float,
    ) -> ExternalSearchResult:
        return ExternalSearchResult(
            provider=EXA_PROVIDER_NAME,
            request_id=self._request_id(request),
            resolved_search_mode=str(request.search_mode or "light"),
            retrieval_status=status,
            latency_ms=self._latency_ms(started),
            failure=SearchFailure(
                code=code,
                message=message[:500],
                retryable=retryable,
                local_fallback_allowed=True,
            ),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = [
    "EXA_DEFAULT_ENDPOINT",
    "EXA_PROVIDER_NAME",
    "ExaHTTPExternalSearchAdapter",
    "UnavailableExternalSearchAdapter",
]
