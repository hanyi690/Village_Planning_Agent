"""
Unified LLM Factory for Village Planning Agent

Supports OpenAI (including DeepSeek), ZhipuAI (GLM), MiniMax, and OpenCode Go.
Provider is determined by LLM_PROVIDER environment variable or explicit parameter.
Includes automatic LangSmith tracing support.
"""

import asyncio
import os
from enum import Enum
from typing import Optional, Any, List, Dict

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _provider_http_clients() -> dict[str, Any]:
    """Build the bounded official OpenAI transports used by ChatOpenAI.

    LangChain accepts separate sync and async clients.  Reusing the same
    transport policy as Instructor keeps connection limits, pool timeout, and
    provider retry boundaries consistent across both call paths.
    """
    from app.infrastructure.llm.instructor_client import _http_client

    return {
        "http_client": _http_client(async_client=False),
        "http_async_client": _http_client(async_client=True),
    }

# Global LLM semaphore (lazy init).
#
# LangGraph's ``max_concurrency`` limits graph task scheduling, but it is not
# an HTTP boundary guarantee for every Send/resume path.  The structured
# client therefore uses this single provider-call gate as the authoritative
# in-flight request budget.  Keep the gate loop-local because test runners and
# application reloads can create more than one asyncio event loop.
_llm_semaphore: Optional[asyncio.Semaphore] = None
_llm_semaphore_loop: Optional[asyncio.AbstractEventLoop] = None
_llm_semaphore_budget: Optional[int] = None
_scoped_llm_semaphores: dict[tuple[asyncio.AbstractEventLoop, str, int], asyncio.Semaphore] = {}


async def get_llm_semaphore(
    max_concurrent: Optional[int] = None,
    *,
    scope: str = "default",
) -> asyncio.Semaphore:
    """Return the loop-local provider-call semaphore.

    The function intentionally has no await before initialization.  A single
    event-loop turn cannot interleave, so this avoids a second asyncio lock
    whose ownership can become invalid after a loop replacement.  If the
    configured budget changes, a new gate is created for subsequent calls;
    already-running calls retain the old gate until they finish.
    """
    loop = asyncio.get_running_loop()
    if max_concurrent is None:
        from app.core.settings import LLM_MAX_CONCURRENT

        max_concurrent = LLM_MAX_CONCURRENT
    budget = max(1, int(max_concurrent))
    if scope != "default":
        key = (loop, str(scope), budget)
        semaphore = _scoped_llm_semaphores.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(budget)
            _scoped_llm_semaphores[key] = semaphore
            logger.info(
                "[LLM] Scoped provider-call semaphore created: scope=%s max_concurrent=%d",
                scope,
                budget,
            )
        return semaphore

    global _llm_semaphore, _llm_semaphore_loop, _llm_semaphore_budget
    if (
        _llm_semaphore is None
        or _llm_semaphore_loop is not loop
        or _llm_semaphore_budget != budget
    ):
        _llm_semaphore = asyncio.Semaphore(budget)
        _llm_semaphore_loop = loop
        _llm_semaphore_budget = budget
        logger.info("[LLM] Provider-call semaphore created: max_concurrent=%d", budget)
    return _llm_semaphore


class LLMProvider(Enum):
    """LLM Provider enumeration"""
    OPENAI = "openai"
    ZHIPUAI = "zhipuai"
    MINIMAX = "minimax"
    OPENCODE_GO = "opencode-go"


def get_provider(explicit_provider: Optional[str] = None) -> LLMProvider:
    """
    Get the LLM provider from explicit setting or environment variable.
    """
    from app.core.settings import LLM_PROVIDER

    provider_name = explicit_provider or LLM_PROVIDER

    if provider_name in ("deepseek", "openai"):
        return LLMProvider.OPENAI
    elif provider_name == "zhipuai":
        return LLMProvider.ZHIPUAI
    elif provider_name in ("minimax", "minimaxai", "mini-max"):
        return LLMProvider.MINIMAX
    elif provider_name in ("opencode-go", "opencode_go", "opencodego"):
        return LLMProvider.OPENCODE_GO
    else:
        logger.warning(f"Unknown provider '{provider_name}', falling back to OpenAI")
        return LLMProvider.OPENAI


def get_api_key(provider: LLMProvider) -> str:
    """Get the API key for the specified provider from environment variables."""
    if provider == LLMProvider.ZHIPUAI:
        key = os.getenv("ZHIPUAI_API_KEY")
        if not key:
            raise ValueError("ZHIPUAI_API_KEY not found in environment.")
        return key
    elif provider == LLMProvider.MINIMAX:
        key = os.getenv("MINIMAX_API_KEY")
        if not key:
            raise ValueError("MINIMAX_API_KEY not found in environment.")
        return key
    elif provider == LLMProvider.OPENCODE_GO:
        key = os.getenv("OPENCODE_GO_API_KEY")
        if not key:
            raise ValueError("OPENCODE_GO_API_KEY not found in environment.")
        return key
    else:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not found in environment.")
        return key


def _merge_callbacks(user_callbacks: Optional[List[Any]] = None) -> List[Any]:
    """Merge user-provided callbacks with LangSmith callbacks"""
    all_callbacks = []
    if user_callbacks:
        all_callbacks.extend(user_callbacks)

    try:
        from app.infrastructure.llm.tracing import get_langsmith_manager
        langsmith_manager = get_langsmith_manager()
        if langsmith_manager.is_enabled():
            langsmith_callbacks = langsmith_manager.get_callbacks()
            if langsmith_callbacks:
                all_callbacks.extend(langsmith_callbacks)
    except Exception as e:
        logger.debug(f"[LLM Factory] Could not get LangSmith callbacks: {e}")

    return all_callbacks


def _create_openai_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    streaming: bool = False,
    **kwargs
) -> Any:
    """Create an OpenAI LLM instance."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        from langchain_community.chat_models import ChatOpenAI

    api_key = get_api_key(LLMProvider.OPENAI)

    from app.core.settings import OPENAI_API_BASE, LLM_REQUEST_TIMEOUT
    if OPENAI_API_BASE:
        kwargs['base_url'] = OPENAI_API_BASE
    kwargs.setdefault('request_timeout', LLM_REQUEST_TIMEOUT)
    kwargs.setdefault('max_retries', max(0, int(os.getenv('LLM_PROVIDER_MAX_RETRIES', '0'))))
    for key, value in _provider_http_clients().items():
        kwargs.setdefault(key, value)

    all_callbacks = _merge_callbacks(callbacks)
    if all_callbacks:
        kwargs['callbacks'] = all_callbacks
    if metadata:
        kwargs['metadata'] = metadata

    # Build rate limiter callbacks for observability (NOT dynamic adjustment)
    # Dynamic adjustment of shared max_bucket_size is unsafe under concurrency.
    # Instead, log rate limit headers for monitoring; keep fixed requests_per_second.
    llm_rate_limiter = kwargs.pop('rate_limiter', None)

    def _on_ratelimit_info(response) -> None:
        try:
            headers = getattr(response, 'headers', {})
            remaining_req = headers.get('x-ratelimit-remaining-requests', 'N/A')
            remaining_tok = headers.get('x-ratelimit-remaining-tokens', 'N/A')
            reset_time = headers.get('x-ratelimit-reset-requests', 'N/A')
            logger.debug(
                f"[LLM RateLimit] remaining_requests={remaining_req}, "
                f"remaining_tokens={remaining_tok}, reset={reset_time}"
            )
        except Exception:
            pass

    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        streaming=streaming,
        **kwargs
    )

    if llm_rate_limiter:
        llm.rate_limiter = llm_rate_limiter._rpm_limiter
        logger.debug(f"[LLM] Rate limiter attached to LLM instance")

    if hasattr(llm, 'on_llm_ratelimit_info'):
        llm.on_llm_ratelimit_info = _on_ratelimit_info

    return llm


def _create_zhipuai_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    streaming: bool = False,
    **kwargs
) -> Any:
    """Create a ZhipuAI (GLM) LLM instance.

    Uses langchain-classic (community packages' new home) with
    langchain-community fallback while it is still available.
    Long-term: migrate to ChatOpenAI + GLM OpenAI-compatible endpoint.
    """
    try:
        from langchain_classic.chat_models import ChatZhipuAI
    except ImportError:
        try:
            from langchain_community.chat_models import ChatZhipuAI
        except ImportError:
            raise ImportError(
                "ChatZhipuAI requires langchain-classic or langchain-community. "
                "Install with: pip install langchain-classic>=1.0.8"
            )

    api_key = get_api_key(LLMProvider.ZHIPUAI)

    from app.core.settings import LLM_REQUEST_TIMEOUT
    kwargs.setdefault('request_timeout', LLM_REQUEST_TIMEOUT)

    all_callbacks = _merge_callbacks(callbacks)
    if all_callbacks:
        kwargs['callbacks'] = all_callbacks
    if metadata:
        kwargs['metadata'] = metadata

    return ChatZhipuAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        streaming=streaming,
        **kwargs
    )


def _create_minimax_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    streaming: bool = False,
    **kwargs,
) -> Any:
    """Create MiniMax through its official OpenAI-compatible endpoint.

    MiniMax documents ``temperature`` as an open interval ``(0, 1]``;
    normalise a caller's deterministic ``0`` to the smallest valid value
    rather than sending a request the provider will reject.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        from langchain_community.chat_models import ChatOpenAI

    from app.core.settings import MINIMAX_API_BASE, LLM_REQUEST_TIMEOUT

    api_key = get_api_key(LLMProvider.MINIMAX)
    effective_temperature = min(1.0, max(0.01, float(temperature)))
    kwargs["base_url"] = MINIMAX_API_BASE
    kwargs.setdefault("request_timeout", LLM_REQUEST_TIMEOUT)
    kwargs.setdefault("max_retries", max(0, int(os.getenv("LLM_PROVIDER_MAX_RETRIES", "0"))))
    for key, value in _provider_http_clients().items():
        kwargs.setdefault(key, value)

    all_callbacks = _merge_callbacks(callbacks)
    if all_callbacks:
        kwargs["callbacks"] = all_callbacks
    if metadata:
        kwargs["metadata"] = metadata

    # MiniMax deprecated ``max_tokens`` in favour of ``max_completion_tokens``
    # on its OpenAI-compatible endpoint.  Keep the completion limit as an
    # explicit ChatOpenAI field so the provider adapter does not hide it in
    # ``model_kwargs`` or emit a version-dependent warning.
    model_kwargs = dict(kwargs.pop("model_kwargs", None) or {})
    completion_limit = int(model_kwargs.pop("max_completion_tokens", max_tokens))
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs

    return ChatOpenAI(
        model=model,
        temperature=effective_temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        streaming=streaming,
        max_completion_tokens=completion_limit,
        **kwargs,
    )


def _create_opencode_go_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    streaming: bool = False,
    **kwargs,
) -> Any:
    """Create an OpenCode Go LLM through its OpenAI-compatible endpoint."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        from langchain_community.chat_models import ChatOpenAI

    from app.core.settings import OPENCODE_GO_API_BASE, LLM_REQUEST_TIMEOUT

    api_key = get_api_key(LLMProvider.OPENCODE_GO)
    kwargs["base_url"] = OPENCODE_GO_API_BASE
    kwargs.setdefault("request_timeout", LLM_REQUEST_TIMEOUT)
    kwargs.setdefault("max_retries", max(0, int(os.getenv("LLM_PROVIDER_MAX_RETRIES", "0"))))
    # langchain-openai otherwise injects a socket-options transport that
    # disables httpx proxy auto-detection.  OpenCode Go is reached through the
    # deployment proxy in this environment, so keep the plain proxy-aware
    # httpx clients supplied below.
    kwargs.setdefault("http_socket_options", ())
    for key, value in _provider_http_clients().items():
        kwargs.setdefault(key, value)

    all_callbacks = _merge_callbacks(callbacks)
    if all_callbacks:
        kwargs["callbacks"] = all_callbacks
    if metadata:
        kwargs["metadata"] = metadata

    # OpenCode Go exposes the standard OpenAI Chat Completions contract.
    # Accept the fully-qualified OpenCode config form as a convenience, but
    # send only the provider's model id to the API.
    model_id = model.removeprefix("opencode-go/")

    return ChatOpenAI(
        model=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        streaming=streaming,
        **kwargs,
    )


def create_llm(
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    provider: Optional[str] = None,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    streaming: bool = False,
    **kwargs
) -> Any:
    """Create an LLM instance with specified provider."""
    from app.core.settings import (
        LLM_MODEL,
        MINIMAX_MODEL,
        OPENCODE_GO_MODEL,
        LANGCHAIN_TRACING_V2,
        LANGCHAIN_PROJECT,
    )

    selected_provider = get_provider(provider)
    # MiniMax reasoning responses can otherwise inherit an accidentally huge
    # workspace MAX_TOKENS (for example 65536), keeping every long planning
    # dimension open for many minutes.  Keep the provider boundary bounded;
    # stage contracts still require complete human-readable sections and do
    # not rely on truncation as a recovery strategy.
    if selected_provider == LLMProvider.MINIMAX:
        max_tokens = min(int(max_tokens), 8192)
    if model is None:
        if selected_provider == LLMProvider.MINIMAX:
            model = MINIMAX_MODEL
        elif selected_provider == LLMProvider.OPENCODE_GO:
            model = OPENCODE_GO_MODEL
        else:
            model = LLM_MODEL

    if LANGCHAIN_TRACING_V2:
        logger.debug(f"[LLM Factory] LangSmith tracing enabled (project: {LANGCHAIN_PROJECT})")

    logger.debug(f"[LLM Factory] Creating LLM: model={model}, provider={selected_provider.value}")

    if selected_provider == LLMProvider.ZHIPUAI:
        return _create_zhipuai_llm(
            model=model, temperature=temperature, max_tokens=max_tokens,
            callbacks=callbacks, metadata=metadata, streaming=streaming, **kwargs
        )
    elif selected_provider == LLMProvider.MINIMAX:
        return _create_minimax_llm(
            model=model, temperature=temperature, max_tokens=max_tokens,
            callbacks=callbacks, metadata=metadata, streaming=streaming, **kwargs
        )
    elif selected_provider == LLMProvider.OPENCODE_GO:
        return _create_opencode_go_llm(
            model=model, temperature=temperature, max_tokens=max_tokens,
            callbacks=callbacks, metadata=metadata, streaming=streaming, **kwargs
        )
    else:
        return _create_openai_llm(
            model=model, temperature=temperature, max_tokens=max_tokens,
            callbacks=callbacks, metadata=metadata, streaming=streaming, **kwargs
        )


def get_default_llm(
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Any:
    """Get the default LLM instance using model from environment."""
    return create_llm(temperature=temperature, max_tokens=max_tokens,
                     callbacks=callbacks, metadata=metadata)


def get_openai_llm(
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Any:
    """Get an OpenAI LLM instance explicitly."""
    return _create_openai_llm(model, temperature, max_tokens,
                             callbacks=callbacks, metadata=metadata, **kwargs)


def get_zhipuai_llm(
    model: str = "glm-4-flash",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Any:
    """Get a ZhipuAI LLM instance explicitly."""
    return _create_zhipuai_llm(model, temperature, max_tokens,
                              callbacks=callbacks, metadata=metadata, **kwargs)


def get_minimax_llm(
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Any:
    """Get a MiniMax LLM explicitly through the OpenAI-compatible endpoint."""
    from app.core.settings import MINIMAX_MODEL

    return _create_minimax_llm(
        model or MINIMAX_MODEL, temperature, max_tokens,
        callbacks=callbacks, metadata=metadata, **kwargs
    )


def get_opencode_go_llm(
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Any:
    """Get an OpenCode Go LLM explicitly."""
    from app.core.settings import OPENCODE_GO_MODEL

    return _create_opencode_go_llm(
        model or OPENCODE_GO_MODEL, temperature, max_tokens,
        callbacks=callbacks, metadata=metadata, **kwargs
    )


def create_flash_llm(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Any:
    """Create a Flash model instance for lightweight tasks."""
    # Flash callers historically supplied provider-specific model names. When
    # the active provider is MiniMax, route through the same provider-aware
    # factory and let its configured default model be selected.
    if get_provider() in (LLMProvider.MINIMAX, LLMProvider.OPENCODE_GO):
        # Flash tasks are lightweight discriminators/extractors (unit mapping,
        # anchor picking, mention extraction).  MiniMax-M2.x thinking cannot be
        # turned off, and this langchain-openai version forwards model_kwargs
        # entries to AsyncCompletions.create() so both thinking and
        # reasoning_split break the call.  Do NOT pass extra model kwargs;
        # call sites strip <think> traces defensively instead.
        return create_llm(
            temperature=temperature if temperature is not None else 0.3,
            max_tokens=max_tokens if max_tokens is not None else 500,
            callbacks=callbacks,
            metadata=metadata,
            streaming=bool(kwargs.pop("streaming", False)),
            **kwargs,
        )
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        from langchain_community.chat_models import ChatOpenAI

    from app.core.settings import (
        FLASH_MODEL_NAME,
        FLASH_MODEL_MAX_TOKENS,
        FLASH_MODEL_TEMPERATURE,
        DASHSCOPE_API_KEY,
        DASHSCOPE_API_BASE,
        LLM_REQUEST_TIMEOUT
    )

    model = model or FLASH_MODEL_NAME
    temperature = FLASH_MODEL_TEMPERATURE if temperature is None else temperature
    max_tokens = FLASH_MODEL_MAX_TOKENS if max_tokens is None else max_tokens

    if not DASHSCOPE_API_KEY:
        raise ValueError("DASHSCOPE_API_KEY not found for Flash model.")

    all_callbacks = _merge_callbacks(callbacks)

    flash_kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": DASHSCOPE_API_KEY,
        "base_url": DASHSCOPE_API_BASE,
        "request_timeout": LLM_REQUEST_TIMEOUT,
        **kwargs
    }

    if all_callbacks:
        flash_kwargs["callbacks"] = all_callbacks
    if metadata:
        flash_kwargs["metadata"] = metadata

    logger.debug(f"[LLM Factory] Creating Flash LLM: model={model}")
    return ChatOpenAI(**flash_kwargs)


__all__ = [
    "LLMProvider",
    "get_provider",
    "get_api_key",
    "create_llm",
    "get_default_llm",
    "get_openai_llm",
    "get_zhipuai_llm",
    "get_minimax_llm",
    "get_opencode_go_llm",
    "create_flash_llm",
]
