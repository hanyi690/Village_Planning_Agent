"""Application-scoped external search provider lifecycle."""

from __future__ import annotations

from typing import Any

_active_external_provider: Any | None = None


def get_configured_external_provider(categories: list[str] | None = None) -> Any:
    import os

    mode = str(os.getenv('EVIDENCE_EXTERNAL_PROVIDER', 'disabled') or '').strip().lower()
    if mode == 'fake':
        from app.infrastructure.search import FakeExternalSearchAdapter

        return FakeExternalSearchAdapter(
            enabled_domains=['statistics', 'economics', 'planning'],
            enabled_categories=[
                str(item).strip()
                for item in (categories or ['population', 'industry', 'transport', 'water'])[:8]
                if str(item).strip()
            ],
        )
    if mode == 'exa' and str(os.getenv('EXA_API_KEY', '') or '').strip():
        from app.infrastructure.search import ExaHTTPExternalSearchAdapter

        try:
            timeout_s = float(os.getenv('EXA_TIMEOUT_S', '8'))
        except (TypeError, ValueError):
            timeout_s = 8.0
        return ExaHTTPExternalSearchAdapter(
            str(os.getenv('EXA_API_KEY')).strip(),
            endpoint=os.getenv('EXA_ENDPOINT', 'https://api.exa.ai/search'),
            timeout_s=timeout_s,
        )
    from app.infrastructure.search import UnavailableExternalSearchAdapter

    return UnavailableExternalSearchAdapter()


def configure_external_provider(app: Any) -> Any:
    global _active_external_provider
    provider = get_configured_external_provider()
    app.state.evidence_external_provider = provider
    _active_external_provider = provider
    return provider


async def close_external_provider(app: Any) -> None:
    global _active_external_provider
    provider = getattr(getattr(app, 'state', None), 'evidence_external_provider', None)
    close = getattr(provider, 'close', None)
    try:
        if close is not None:
            result = close()
            if hasattr(result, '__await__'):
                await result
    finally:
        _active_external_provider = None


def get_active_external_provider() -> Any | None:
    return _active_external_provider


__all__ = [
    'close_external_provider',
    'configure_external_provider',
    'get_active_external_provider',
    'get_configured_external_provider',
]
