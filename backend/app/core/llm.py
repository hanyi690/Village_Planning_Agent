"""
Unified LLM Factory for Village Planning Agent

Supports OpenAI (including DeepSeek) and ZhipuAI (GLM) providers.
Provider is determined by LLM_PROVIDER environment variable or explicit parameter.
Includes automatic LangSmith tracing support.
"""

import asyncio
import os
from enum import Enum
from typing import Optional, Any, List, Dict

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Global LLM semaphore (lazy init)
_llm_semaphore: Optional[asyncio.Semaphore] = None
_semaphore_lock = asyncio.Lock()


async def get_llm_semaphore(max_concurrent: int = 20) -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        async with _semaphore_lock:
            if _llm_semaphore is None:
                _llm_semaphore = asyncio.Semaphore(max_concurrent)
                logger.info(f"[LLM] Global semaphore created: max_concurrent={max_concurrent}")
    return _llm_semaphore


class LLMProvider(Enum):
    """LLM Provider enumeration"""
    OPENAI = "openai"
    ZHIPUAI = "zhipuai"


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
        from app.core.tracing import get_langsmith_manager
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
    kwargs['request_timeout'] = LLM_REQUEST_TIMEOUT

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
    """Create a ZhipuAI (GLM) LLM instance."""
    try:
        from langchain_community.chat_models import ChatZhipuAI
    except ImportError:
        raise ImportError("langchain-community required for ZhipuAI support.")

    api_key = get_api_key(LLMProvider.ZHIPUAI)

    from app.core.settings import LLM_REQUEST_TIMEOUT
    kwargs['request_timeout'] = LLM_REQUEST_TIMEOUT

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
    from app.core.settings import LLM_MODEL, LANGCHAIN_TRACING_V2, LANGCHAIN_PROJECT

    if model is None:
        model = LLM_MODEL

    if LANGCHAIN_TRACING_V2:
        logger.debug(f"[LLM Factory] LangSmith tracing enabled (project: {LANGCHAIN_PROJECT})")

    selected_provider = get_provider(provider)
    logger.debug(f"[LLM Factory] Creating LLM: model={model}, provider={selected_provider.value}")

    if selected_provider == LLMProvider.ZHIPUAI:
        return _create_zhipuai_llm(
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


def create_flash_llm(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Any:
    """Create a Flash model instance for lightweight tasks."""
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
    temperature = temperature or FLASH_MODEL_TEMPERATURE
    max_tokens = max_tokens or FLASH_MODEL_MAX_TOKENS

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
    "create_flash_llm",
]