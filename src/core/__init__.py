"""Core module configuration and initialization."""

from .config import (
    LLM_MODEL,
    LLM_PROVIDER,
    MAX_TOKENS,
    LLM_TIMEOUT,
    OPENAI_API_BASE,
    VECTOR_STORE_DIR,
    VECTORDB_PERSIST,
    LANGCHAIN_TRACING_V2,
    LANGCHAIN_API_KEY,
    LANGCHAIN_PROJECT,
)
from .prompts import (
    SYSTEM_PROMPT,
    HUMAN_PROMPT_TEMPLATE,
    PLANNING_CONCEPT_PROMPT,
)

__all__ = [
    # LLM Configuration
    "LLM_MODEL",
    "LLM_PROVIDER",
    "MAX_TOKENS",
    "LLM_TIMEOUT",
    "OPENAI_API_BASE",
    # Vector Store
    "VECTOR_STORE_DIR",
    "VECTORDB_PERSIST",
    # LangSmith
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_PROJECT",
    # Prompts
    "SYSTEM_PROMPT",
    "HUMAN_PROMPT_TEMPLATE",
    "PLANNING_CONCEPT_PROMPT",
]
