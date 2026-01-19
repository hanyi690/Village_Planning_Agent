"""
核心模块 (Core Module)

包含配置和初始化相关功能。
"""

from .config import (
    OPENAI_API_KEY,
    LLM_MODEL,
    MAX_TOKENS,
    VECTOR_STORE_DIR,
    VECTORDB_PERSIST,
)

from .prompts import (
    SYSTEM_PROMPT,
    HUMAN_PROMPT_TEMPLATE,
    PLANNING_CONCEPT_PROMPT,
)

__all__ = [
    # 配置
    "OPENAI_API_KEY",
    "LLM_MODEL",
    "MAX_TOKENS",
    "VECTOR_STORE_DIR",
    "VECTORDB_PERSIST",

    # Prompts
    "SYSTEM_PROMPT",
    "HUMAN_PROMPT_TEMPLATE",
    "PLANNING_CONCEPT_PROMPT",
]
