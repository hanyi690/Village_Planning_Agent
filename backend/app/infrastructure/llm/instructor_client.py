"""Provider-aware Instructor clients for typed LLM contracts."""

from __future__ import annotations

import instructor
import httpx
import os
import inspect
from openai import (
    AsyncOpenAI,
    OpenAI,
)

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_cached_clients: dict[tuple[str, str, str], instructor.Instructor] = {}
_cached_async_clients: dict[tuple[str, str, str], instructor.AsyncInstructor] = {}


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


def _structured_mode(provider_name: str) -> instructor.Mode:
    """Choose the provider-compatible protocol for typed output.

    MiniMax exposes function tools on its OpenAI-compatible API.  Prefer that
    protocol for typed calls so the provider receives the response model as a
    function-parameter schema instead of merely receiving a free-form JSON
    instruction.  Deployments can still opt into JSON/markdown-JSON explicitly
    for a model that does not support tool calls.
    """
    configured = os.getenv("LLM_STRUCTURED_MODE", "").strip().lower()
    if configured in {"tools", "tool", "function", "function_call", "function_calling"}:
        return instructor.Mode.TOOLS
    if configured in {"json", "json_mode", "json-schema", "json_schema"}:
        return instructor.Mode.JSON
    if configured in {"md_json", "markdown_json", "markdown-json"}:
        return instructor.Mode.MD_JSON
    if provider_name in {"minimax", "minimaxai", "mini-max"}:
        return instructor.Mode.TOOLS
    return instructor.Mode.TOOLS


def get_instructor_client() -> instructor.Instructor:
    """Create or return the Instructor client for the active provider."""
    provider_name, api_key, base_url = _provider_connection()
    mode = _structured_mode(provider_name)
    cache_key = (provider_name, base_url, mode.value)
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
    client = instructor.from_openai(base_client, mode=mode)
    _cached_clients[cache_key] = client
    logger.debug(
        "[Instructor] Client created (provider=%s, mode=%s, base_url=%s)",
        provider_name,
        mode.value,
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
    mode = _structured_mode(provider_name)
    cache_key = (provider_name, base_url, mode.value)
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
    client = instructor.from_openai(base_client, mode=mode)
    _cached_async_clients[cache_key] = client
    logger.debug(
        "[Instructor] Async client created (provider=%s, mode=%s, base_url=%s)",
        provider_name,
        mode.value,
        base_url,
    )
    return client


async def close_cached_clients() -> None:
    """Close and clear provider clients at application/test lifecycle end.

    Instructor keeps the OpenAI transport on the wrapper and the wrapper's
    ``close`` method owns the underlying HTTP connection pool.  Closing the
    wrapper, rather than reaching into the transport, keeps this boundary
    valid across Instructor versions and prevents provider pools from keeping
    acceptance processes alive after the graph and database have shut down.
    """
    async_clients = list(_cached_async_clients.values())
    sync_clients = list(_cached_clients.values())
    _cached_async_clients.clear()
    _cached_clients.clear()

    for client in async_clients:
        close = getattr(client, "close", None)
        if not callable(close):
            continue
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 - continue closing other pools
            logger.warning("[Instructor] Async client close failed: %s", exc)

    for client in sync_clients:
        close = getattr(client, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except Exception as exc:  # noqa: BLE001 - continue closing other pools
            logger.warning("[Instructor] Sync client close failed: %s", exc)


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
    budgets = [LLM_MAX_CONCURRENT]
    for name in (
        "L1_LLM_MAX_CONCURRENT",
        "L2_LLM_MAX_CONCURRENT",
        "L3_LLM_MAX_CONCURRENT",
        "GROUND_LLM_MAX_CONCURRENT",
    ):
        try:
            budgets.append(int(os.getenv(name, "0")))
        except (TypeError, ValueError):
            continue
    provider_budget = max(1, max(budgets))
    default_connections = max(8, provider_budget * 2 + 4)
    max_connections = max(
        4,
        int(os.getenv("LLM_HTTP_MAX_CONNECTIONS", str(default_connections))),
    )
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max(2, min(max_connections, provider_budget)),
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
