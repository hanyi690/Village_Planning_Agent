"""
核心模块 (Core Module)

包含配置、LLM 工厂和状态构建器。
"""

from .config import (
    OPENAI_API_KEY,
    LLM_MODEL,
    MAX_TOKENS,
    VECTOR_STORE_DIR,
    VECTORDB_PERSIST,
)

__all__ = [
    "OPENAI_API_KEY",
    "LLM_MODEL",
    "MAX_TOKENS",
    "VECTOR_STORE_DIR",
    "VECTORDB_PERSIST",
]