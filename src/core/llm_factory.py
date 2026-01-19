"""
Unified LLM Factory for Village Planning Agent

Supports both OpenAI and ZhipuAI (GLM) providers with auto-detection based on model name.
"""

import os
from enum import Enum
from typing import Optional, Any


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


def _create_openai_llm(
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    **kwargs
) -> Any:
    """
    Create an OpenAI LLM instance.

    Args:
        model: Model name (e.g., "gpt-4o-mini", "deepseek-reasoner")
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
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
    **kwargs
) -> Any:
    """
    Create a ZhipuAI (GLM) LLM instance.

    Args:
        model: Model name (e.g., "glm-4-flash", "glm-4", "glm-4-plus")
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
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

        >>> # Invoke the LLM
        >>> from langchain_core.messages import HumanMessage
        >>> response = llm.invoke([HumanMessage(content="Hello!")])
        >>> print(response.content)
    """
    from .config import LLM_MODEL

    if model is None:
        model = LLM_MODEL

    # Detect provider
    detected_provider = detect_provider(model, provider)

    # Route to appropriate provider-specific function
    if detected_provider == LLMProvider.ZHIPUAI:
        return _create_zhipuai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
    else:  # OPENAI
        return _create_openai_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )


# Convenience functions for backward compatibility
def get_default_llm(temperature: float = 0.7, max_tokens: int = 2000) -> Any:
    """
    Get the default LLM instance using model from environment.

    Convenience function for quick access to the default LLM.

    Args:
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate

    Returns:
        LLM instance
    """
    return create_llm(temperature=temperature, max_tokens=max_tokens)


def get_openai_llm(
    model: str = "gpt-4o-mini",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    **kwargs
) -> Any:
    """
    Get an OpenAI LLM instance explicitly.

    Args:
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        **kwargs: Additional parameters

    Returns:
        ChatOpenAI instance
    """
    return _create_openai_llm(model, temperature, max_tokens, **kwargs)


def get_zhipuai_llm(
    model: str = "glm-4.7",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    **kwargs
) -> Any:
    """
    Get a ZhipuAI LLM instance explicitly.

    Args:
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        **kwargs: Additional parameters

    Returns:
        ChatZhipuAI instance
    """
    return _create_zhipuai_llm(model, temperature, max_tokens, **kwargs)
