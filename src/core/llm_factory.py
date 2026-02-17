"""
Unified LLM Factory for Village Planning Agent

Supports both OpenAI and ZhipuAI (GLM) providers with auto-detection based on model name.
Includes automatic LangSmith tracing support.
"""

import os
from enum import Enum
from typing import Optional, Any, List, Dict

from ..utils.logger import get_logger

logger = get_logger(__name__)


class LLMProvider(Enum):
    """LLM Provider enumeration"""
    OPENAI = "openai"
    ZHIPUAI = "zhipuai"


def detect_provider(model_name: str, explicit_provider: Optional[str] = None) -> LLMProvider:
    """
    Detect the appropriate LLM provider based on model name prefix or explicit setting.

    Args:
        model_name: The model name (e.g., "glm-4-flash", "gpt-4o-mini")
        explicit_provider: Optional explicit provider override ("openai" or "zhipuai")

    Returns:
        LLMProvider enum value

    Examples:
        >>> detect_provider("glm-4-flash")
        <LLMProvider.ZHIPUAI: 'zhipuai'>
        >>> detect_provider("gpt-4o-mini")
        <LLMProvider.OPENAI: 'openai'>
        >>> detect_provider("custom-model", explicit_provider="zhipuai")
        <LLMProvider.ZHIPUAI: 'zhipuai'>
    """
    if explicit_provider:
        try:
            return LLMProvider(explicit_provider.lower())
        except ValueError:
            pass

    # Auto-detect based on model name prefix
    if model_name.startswith("glm-"):
        return LLMProvider.ZHIPUAI
    elif model_name.startswith("gpt-") or model_name.startswith("deepseek-"):
        return LLMProvider.OPENAI
    else:
        # Default to OpenAI for unknown models
        return LLMProvider.OPENAI


def get_api_key(provider: LLMProvider) -> str:
    """
    Get the API key for the specified provider from environment variables.

    Args:
        provider: The LLM provider

    Returns:
        API key string

    Raises:
        ValueError: If the required API key is not found
    """
    if provider == LLMProvider.ZHIPUAI:
        key = os.getenv("ZHIPUAI_API_KEY")
        if not key:
            raise ValueError(
                "ZHIPUAI_API_KEY not found in environment. "
                "Please set it in your .env file or environment variables."
            )
        return key
    else:  # OPENAI
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError(
                "OPENAI_API_KEY not found in environment. "
                "Please set it in your .env file or environment variables."
            )
        return key


def _merge_callbacks(
    user_callbacks: Optional[List[Any]] = None
) -> List[Any]:
    """
    Merge user-provided callbacks with LangSmith callbacks

    Args:
        user_callbacks: Optional list of user-provided callbacks

    Returns:
        Merged list of callbacks (user callbacks + LangSmith callbacks)
    """
    all_callbacks = []

    # Add user callbacks first
    if user_callbacks:
        all_callbacks.extend(user_callbacks)

    # Add LangSmith callbacks if enabled
    try:
        from .langsmith_integration import get_langsmith_manager
        langsmith_manager = get_langsmith_manager()
        if langsmith_manager.is_enabled():
            langsmith_callbacks = langsmith_manager.get_callbacks()
            if langsmith_callbacks:
                all_callbacks.extend(langsmith_callbacks)
    except Exception as e:
        # Silently fail if LangSmith is not configured
        logger.debug(f"[LLM Factory] Could not get LangSmith callbacks: {e}")

    return all_callbacks


def _create_openai_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Any:
    """
    Create an OpenAI LLM instance.

    Args:
        model: Model name (e.g., "gpt-4o-mini", "deepseek-reasoner")
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        callbacks: Optional list of callback handlers (will be merged with LangSmith callbacks)
        metadata: Optional metadata dict for LangSmith tracing
        **kwargs: Additional parameters to pass to the LLM

    Returns:
        ChatOpenAI instance
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        from langchain_community.chat_models import ChatOpenAI

    api_key = get_api_key(LLMProvider.OPENAI)

    # Support for custom API base URL (e.g., DeepSeek)
    from .config import OPENAI_API_BASE
    if OPENAI_API_BASE:
        kwargs['base_url'] = OPENAI_API_BASE

    # Merge callbacks with LangSmith callbacks
    all_callbacks = _merge_callbacks(callbacks)

    # Only pass callbacks if we have them
    if all_callbacks:
        kwargs['callbacks'] = all_callbacks

    # Pass metadata if provided
    if metadata:
        kwargs['metadata'] = metadata

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        **kwargs
    )


def _create_zhipuai_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Any:
    """
    Create a ZhipuAI (GLM) LLM instance.

    Args:
        model: Model name (e.g., "glm-4-flash", "glm-4", "glm-4-plus")
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        callbacks: Optional list of callback handlers (will be merged with LangSmith callbacks)
        metadata: Optional metadata dict for LangSmith tracing
        **kwargs: Additional parameters to pass to the LLM

    Returns:
        ChatZhipuAI instance
    """
    try:
        from langchain_community.chat_models import ChatZhipuAI
    except ImportError:
        raise ImportError(
            "langchain-community is required for ZhipuAI support. "
            "Install it with: pip install langchain-community==0.4.1"
        )

    api_key = get_api_key(LLMProvider.ZHIPUAI)

    # Merge callbacks with LangSmith callbacks
    all_callbacks = _merge_callbacks(callbacks)

    # Only pass callbacks if we have them
    if all_callbacks:
        kwargs['callbacks'] = all_callbacks

    # Pass metadata if provided
    if metadata:
        kwargs['metadata'] = metadata

    return ChatZhipuAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        **kwargs
    )


def create_llm(
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    provider: Optional[str] = None,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs
) -> Any:
    """
    Create an LLM instance with auto-detected provider.

    This is the main factory function that unifies LLM creation across providers.
    It automatically detects the appropriate provider based on the model name prefix
    or explicit provider setting.

    Args:
        model: Model name. If None, reads from LLM_MODEL environment variable (default: "glm-4-flash")
        temperature: Sampling temperature (0.0 to 1.0)
        max_tokens: Maximum tokens to generate
        provider: Explicit provider override ("openai" or "zhipuai"). If None, auto-detects from model name
        callbacks: Optional list of callback handlers (will be merged with LangSmith callbacks)
        metadata: Optional metadata dict for LangSmith tracing
        **kwargs: Additional parameters passed to the underlying LLM constructor

    Returns:
        LLM instance (ChatOpenAI or ChatZhipuAI)

    Raises:
        ValueError: If required API keys are not found
        ImportError: If required packages are not installed

    Examples:
        >>> # Auto-detect provider from model name
        >>> llm = create_llm(model="glm-4-flash")  # Returns ChatZhipuAI
        >>> llm = create_llm(model="gpt-4o-mini")  # Returns ChatOpenAI

        >>> # Explicit provider override
        >>> llm = create_llm(model="custom-model", provider="zhipuai")

        >>> # Use default model from environment
        >>> llm = create_llm(temperature=0.5)

        >>> # With LangSmith metadata
        >>> metadata = {"project": "My Village", "dimension": "industry"}
        >>> llm = create_llm(metadata=metadata)

        >>> # Invoke the LLM
        >>> from langchain_core.messages import HumanMessage
        >>> response = llm.invoke([HumanMessage(content="Hello!")])
        >>> print(response.content)
    """
    from .config import LLM_MODEL, LANGCHAIN_TRACING_V2, LANGCHAIN_PROJECT

    if model is None:
        model = LLM_MODEL

    # Log LangSmith tracing status
    if LANGCHAIN_TRACING_V2:
        logger.info(f"[LLM Factory] LangSmith tracing enabled (project: {LANGCHAIN_PROJECT})")
    else:
        logger.debug("[LLM Factory] LangSmith tracing not enabled")

    # Detect provider
    detected_provider = detect_provider(model, provider)

    # Route to appropriate provider-specific function
    if detected_provider == LLMProvider.ZHIPUAI:
        return _create_zhipuai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            callbacks=callbacks,
            metadata=metadata,
            **kwargs
        )
    else:  # OPENAI
        return _create_openai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            callbacks=callbacks,
            metadata=metadata,
            **kwargs
        )


# Convenience functions for backward compatibility
def get_default_llm(
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Any:
    """
    Get the default LLM instance using model from environment.

    Convenience function for quick access to the default LLM.

    Args:
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        callbacks: Optional list of callback handlers
        metadata: Optional metadata dict for LangSmith tracing

    Returns:
        LLM instance
    """
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
    """
    Get an OpenAI LLM instance explicitly.

    Args:
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        callbacks: Optional list of callback handlers
        metadata: Optional metadata dict for LangSmith tracing
        **kwargs: Additional parameters

    Returns:
        ChatOpenAI instance
    """
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
    """
    Get a ZhipuAI LLM instance explicitly.

    Args:
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        callbacks: Optional list of callback handlers
        metadata: Optional metadata dict for LangSmith tracing
        **kwargs: Additional parameters

    Returns:
        ChatZhipuAI instance
    """
    return _create_zhipuai_llm(model, temperature, max_tokens,
                              callbacks=callbacks, metadata=metadata, **kwargs)
