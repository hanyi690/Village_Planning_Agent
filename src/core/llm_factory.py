"""
Unified LLM Factory for Village Planning Agent

Supports OpenAI (including DeepSeek) and ZhipuAI (GLM) providers.
Provider is determined by LLM_PROVIDER environment variable or explicit parameter.
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


def get_provider(explicit_provider: Optional[str] = None) -> LLMProvider:
    """
    Get the LLM provider from explicit setting or environment variable.

    Args:
        explicit_provider: Optional explicit provider override ("deepseek", "openai", or "zhipuai")

    Returns:
        LLMProvider enum value

    Examples:
        >>> get_provider("zhipuai")
        <LLMProvider.ZHIPUAI: 'zhipuai'>
        >>> get_provider()  # Returns LLM_PROVIDER from environment
        <LLMProvider.OPENAI: 'openai'>  # if LLM_PROVIDER=deepseek or openai
    """
    from .config import LLM_PROVIDER
    
    provider_name = explicit_provider or LLM_PROVIDER
    
    # Map provider names
    if provider_name in ("deepseek", "openai"):
        return LLMProvider.OPENAI
    elif provider_name == "zhipuai":
        return LLMProvider.ZHIPUAI
    else:
        # Fallback to OpenAI for unknown providers
        logger.warning(f"Unknown provider '{provider_name}', falling back to OpenAI")
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
    streaming: bool = False,
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
        streaming: Enable streaming mode for the LLM
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
    from .config import OPENAI_API_BASE, LLM_REQUEST_TIMEOUT
    if OPENAI_API_BASE:
        kwargs['base_url'] = OPENAI_API_BASE

    # Add request timeout for API calls
    kwargs['request_timeout'] = LLM_REQUEST_TIMEOUT

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
        streaming=streaming,
        **kwargs
    )


def _create_zhipuai_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    streaming: bool = False,
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
        streaming: Enable streaming mode for the LLM
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

    # Add request timeout for API calls
    from .config import LLM_REQUEST_TIMEOUT
    kwargs['request_timeout'] = LLM_REQUEST_TIMEOUT

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
    """
    Create an LLM instance with specified provider.

    This is the main factory function that unifies LLM creation across providers.
    The provider is determined by: explicit `provider` parameter > LLM_PROVIDER env var.

    Args:
        model: Model name. If None, reads from LLM_MODEL environment variable (default: "deepseek-chat")
        temperature: Sampling temperature (0.0 to 1.0)
        max_tokens: Maximum tokens to generate
        provider: Explicit provider override ("deepseek", "openai", or "zhipuai").
                  If None, uses LLM_PROVIDER environment variable
        callbacks: Optional list of callback handlers (will be merged with LangSmith callbacks)
        metadata: Optional metadata dict for LangSmith tracing
        streaming: Enable streaming mode for the LLM (default: False)
        **kwargs: Additional parameters passed to the underlying LLM constructor

    Returns:
        LLM instance (ChatOpenAI or ChatZhipuAI)

    Raises:
        ValueError: If required API keys are not found
        ImportError: If required packages are not installed

    Examples:
        >>> # Use default provider and model from environment
        >>> llm = create_llm(temperature=0.5)

        >>> # Explicit provider
        >>> llm = create_llm(model="glm-4-flash", provider="zhipuai")
        >>> llm = create_llm(model="gpt-4o", provider="openai")

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

    # Log LangSmith tracing status (DEBUG level)
    if LANGCHAIN_TRACING_V2:
        logger.debug(f"[LLM Factory] LangSmith tracing enabled (project: {LANGCHAIN_PROJECT})")
    else:
        logger.debug("[LLM Factory] LangSmith tracing not enabled")

    # Get provider from explicit setting or environment
    selected_provider = get_provider(provider)
    logger.debug(f"[LLM Factory] Creating LLM: model={model}, provider={selected_provider.value}, streaming={streaming}")

    # Route to appropriate provider-specific function
    if selected_provider == LLMProvider.ZHIPUAI:
        return _create_zhipuai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            callbacks=callbacks,
            metadata=metadata,
            streaming=streaming,
            **kwargs
        )
    else:  # OPENAI (includes DeepSeek)
        return _create_openai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            callbacks=callbacks,
            metadata=metadata,
            streaming=streaming,
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


def create_multimodal_llm(
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    provider: Optional[str] = None,
    callbacks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    streaming: bool = False,
    **kwargs
) -> Any:
    """
    Create a multimodal LLM instance that supports text + image input.

    This function creates an LLM capable of processing images along with text.
    The model is automatically selected based on the provider if not specified.

    Args:
        model: Model name. If None, uses provider-specific default vision model:
               - OpenAI: "gpt-4o"
               - ZhipuAI: "glm-4v"
        temperature: Sampling temperature (0.0 to 1.0)
        max_tokens: Maximum tokens to generate
        provider: Explicit provider override ("openai" or "zhipuai")
        callbacks: Optional list of callback handlers
        metadata: Optional metadata dict for LangSmith tracing
        streaming: Enable streaming mode (default: False)
        **kwargs: Additional parameters

    Returns:
        Multimodal LLM instance (ChatOpenAI with vision support)

    Raises:
        ValueError: If provider doesn't support multimodal or API key not found

    Examples:
        >>> from src.core.message_builder import build_multimodal_message
        >>> llm = create_multimodal_llm()
        >>> msg = build_multimodal_message("Describe this image", image_base64="...", image_format="png")
        >>> response = llm.invoke([msg])
    """
    from .config import MULTIMODAL_ENABLED
    from .message_builder import get_recommended_multimodal_model, is_image_message_supported

    if not MULTIMODAL_ENABLED:
        logger.warning("[LLM Factory] MULTIMODAL_ENABLED is false. Creating regular LLM instead.")
        return create_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            provider=provider,
            callbacks=callbacks,
            metadata=metadata,
            streaming=streaming,
            **kwargs
        )

    # Get provider
    selected_provider = get_provider(provider)

    # Check if provider supports multimodal
    if not is_image_message_supported(selected_provider.value):
        raise ValueError(
            f"Provider '{selected_provider.value}' does not support multimodal/vision. "
            f"Supported providers: openai, zhipuai"
        )

    # Select appropriate multimodal model
    if model is None:
        model = get_recommended_multimodal_model(selected_provider.value)

    logger.info(f"[LLM Factory] Creating multimodal LLM: model={model}, provider={selected_provider.value}")

    # Create LLM using existing factory functions
    if selected_provider == LLMProvider.ZHIPUAI:
        return _create_zhipuai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            callbacks=callbacks,
            metadata=metadata,
            streaming=streaming,
            **kwargs
        )
    else:  # OPENAI
        return _create_openai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            callbacks=callbacks,
            metadata=metadata,
            streaming=streaming,
            **kwargs
        )
