"""Provider-aware Instructor clients for typed LLM contracts."""

from __future__ import annotations

import instructor
import httpx
import os
from openai import (
    AsyncOpenAI,
    OpenAI,
)

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_cached_clients: dict[tuple[str, str], instructor.Instructor] = {}
_cached_async_clients: dict[tuple[str, str], instructor.AsyncInstructor] = {}


def _provider_connection() -> tuple[str, str, str]:
    """Return provider name, API key, and base URL without exposing the key."""
    from app.core import settings
    from app.infrastructure.llm.factory import LLMProvider, get_provider

    provider = get_provider()
    if provider is LLMProvider.MINIMAX:
        name, api_key, base_url = "minimax", settings.MINIMAX_API_KEY, settings.MINIMAX_API_BASE
    elif provider is LLMProvider.OPENCODE_GO:
        name, api_key, base_url = "opencode-go", settings.OPENCODE_GO_API_KEY, settings.OPENCODE_GO_API_BASE
    else:
        name, api_key, base_url = provider.value, settings.DASHSCOPE_API_KEY, settings.DASHSCOPE_API_BASE
    if not api_key:
        raise ValueError(f"API key not set for {name} Instructor client")
    return name, api_key, base_url


def get_instructor_client() -> instructor.Instructor:
    """Create or return the Instructor client for the active provider."""
    provider_name, api_key, base_url = _provider_connection()
    cache_key = (provider_name, base_url)
    cached = _cached_clients.get(cache_key)
    if cached is not None:
        return cached

    base_client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=_provider_max_retries(),
        timeout=_provider_timeout(),
        http_client=_http_client(async_client=False),
    )
    client = instructor.from_openai(base_client, mode=instructor.Mode.TOOLS)
    _cached_clients[cache_key] = client
    logger.debug(
        "[Instructor] Client created (provider=%s, base_url=%s)",
        provider_name,
        base_url,
    )
    return client


def get_async_instructor_client() -> instructor.AsyncInstructor:
    """Create or return the async Instructor client for the active provider.

    Structured calls run inside LangGraph's event loop.  Keeping the OpenAI
    transport asynchronous avoids consuming a worker thread per in-flight
    provider request and makes the configured concurrency budget observable at
    the actual HTTP boundary.
    """
    provider_name, api_key, base_url = _provider_connection()
    cache_key = (provider_name, base_url)
    cached = _cached_async_clients.get(cache_key)
    if cached is not None:
        return cached

    base_client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        max_retries=_provider_max_retries(),
        timeout=_provider_timeout(),
        http_client=_http_client(async_client=True),
    )
    client = instructor.from_openai(base_client, mode=instructor.Mode.TOOLS)
    _cached_async_clients[cache_key] = client
    logger.debug(
        "[Instructor] Async client created (provider=%s, base_url=%s)",
        provider_name,
        base_url,
    )
    return client


def _provider_max_retries() -> int:
    """Return the transport retry budget, separate from Instructor re-asks."""
    # Transport retries duplicate a long-running non-streaming request.  A
    # workflow-level resume is the auditable retry boundary; keep the HTTP
    # client single-shot unless deployment explicitly opts in.
    return max(0, int(os.getenv("LLM_PROVIDER_MAX_RETRIES", "0")))


def _provider_timeout() -> float:
    from app.core.settings import LLM_STREAM_TIMEOUT

    return float(os.getenv("LLM_PROVIDER_REQUEST_TIMEOUT", str(LLM_STREAM_TIMEOUT)))


def _http_client(*, async_client: bool) -> httpx.Client | httpx.AsyncClient:
    """Build a bounded keep-alive pool for the configured provider budget."""
    from app.core.settings import LLM_MAX_CONCURRENT

    request_timeout = _provider_timeout()
    max_connections = max(
        4,
        int(os.getenv("LLM_HTTP_MAX_CONNECTIONS", str(LLM_MAX_CONCURRENT + 2))),
    )
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max(2, min(max_connections, LLM_MAX_CONCURRENT)),
    )
    timeout = httpx.Timeout(
        request_timeout,
        connect=min(15.0, request_timeout),
        read=request_timeout,
        write=request_timeout,
        pool=request_timeout,
    )
    # Use plain httpx clients so the deployment's HTTP(S)_PROXY/NO_PROXY
    # environment is honored.  OpenAI's Default*HttpxClient installs a custom
    # transport for socket options; in this environment that disables proxy
    # auto-detection and makes opencode.ai appear to hang on direct TCP.
    client_type = httpx.AsyncClient if async_client else httpx.Client
    return client_type(limits=limits, timeout=timeout, trust_env=True)


def get_structured_model(model: str | None = None) -> str:
    """Resolve the model id used for typed structured calls."""
    from app.core import settings
    from app.infrastructure.llm.factory import LLMProvider, get_provider

    if model:
        return model.removeprefix("opencode-go/")
    provider = get_provider()
    if provider is LLMProvider.MINIMAX:
        return settings.MINIMAX_MODEL
    if provider is LLMProvider.OPENCODE_GO:
        return settings.OPENCODE_GO_MODEL.removeprefix("opencode-go/")
    return settings.FLASH_MODEL_NAME


def get_flash_model() -> str:
    """Backward-compatible alias for lightweight structured callers."""
    return get_structured_model()
