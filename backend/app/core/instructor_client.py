"""Instructor client factory — wraps DashScope/OpenAI for structured extraction.

Uses the Instructor library to enforce Pydantic schema at generation time
with automatic retries on validation failure. This replaces the previous
LangChain with_structured_output approach with stronger schema guarantees.
"""

import instructor
from openai import OpenAI

from app.utils.logger import get_logger

logger = get_logger(__name__)

_cached_client: instructor.Instructor | None = None


def get_instructor_client() -> instructor.Instructor:
    """Create or return cached Instructor client patched with DashScope."""
    global _cached_client
    if _cached_client is not None:
        return _cached_client

    from app.core.settings import DASHSCOPE_API_KEY, DASHSCOPE_API_BASE

    if not DASHSCOPE_API_KEY:
        raise ValueError("DASHSCOPE_API_KEY not set for Instructor client")

    base_client = OpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_API_BASE,
    )
    _cached_client = instructor.from_openai(base_client)
    logger.debug("[Instructor] Client created (base_url=%s)", DASHSCOPE_API_BASE)
    return _cached_client


def get_flash_model() -> str:
    """Return the Flash model name for Instructor calls."""
    from app.core.settings import FLASH_MODEL_NAME
    return FLASH_MODEL_NAME
