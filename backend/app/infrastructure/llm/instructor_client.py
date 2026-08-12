"""Instructor client factory — wraps DashScope/OpenAI for structured extraction.

Uses the Instructor library to enforce Pydantic schema at generation time
with automatic retries on validation failure. This replaces the previous
LangChain with_structured_output approach with stronger schema guarantees.
"""

import instructor
from openai import OpenAI

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_cached_client: instructor.Instructor | None = None


def get_instructor_client() -> instructor.Instructor:
    """Create or return cached Instructor client for the configured provider."""
    global _cached_client
    if _cached_client is not None:
        return _cached_client

    from app.infrastructure.llm.factory import LLMProvider, get_provider
    from app.core.settings import (
        DASHSCOPE_API_BASE,
        DASHSCOPE_API_KEY,
        MINIMAX_API_BASE,
        MINIMAX_API_KEY,
    )
    if get_provider() == LLMProvider.MINIMAX:
        api_key, base_url = MINIMAX_API_KEY, MINIMAX_API_BASE
    else:
        api_key, base_url = DASHSCOPE_API_KEY, DASHSCOPE_API_BASE
    if not api_key:
        raise ValueError(f"API key not set for {get_provider().value} Instructor client")

    base_client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    _cached_client = instructor.from_openai(base_client)
    logger.debug("[Instructor] Client created (provider=%s, base_url=%s)", get_provider().value, base_url)
    return _cached_client


def get_flash_model() -> str:
    """Return the Flash model name for Instructor calls."""
    from app.infrastructure.llm.factory import LLMProvider, get_provider
    from app.core.settings import FLASH_MODEL_NAME, MINIMAX_MODEL
    return MINIMAX_MODEL if get_provider() == LLMProvider.MINIMAX else FLASH_MODEL_NAME
