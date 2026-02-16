"""Core configuration for the Village Planning Agent."""

from __future__ import annotations

import os
from typing import Final

from dotenv import load_dotenv

load_dotenv()


# ==========================================
# API Keys
# ==========================================

OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
ZHIPUAI_API_KEY: str | None = os.getenv("ZHIPUAI_API_KEY")


# ==========================================
# LLM Configuration
# ==========================================

LLM_MODEL: str = os.getenv("LLM_MODEL", "glm-4-flash")
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "zhipuai")
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1500"))
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "300"))
OPENAI_API_BASE: str | None = os.getenv("OPENAI_API_BASE")


# ==========================================
# RAG / Vector Store Settings
# ==========================================

VECTOR_STORE_DIR: str = os.getenv(
    "VECTOR_STORE_DIR",
    "f:\\project\\Village_Planning_Agent\\vectordb"
)
VECTORDB_PERSIST: bool = os.getenv("VECTORDB_PERSIST", "true").lower() in ("1", "true", "yes")

# RAG Integration Settings
RAG_ENABLED: bool = os.getenv("RAG_ENABLED", "true").lower() == "true"
RAG_KNOWLEDGE_PRELOAD: bool = os.getenv("RAG_KNOWLEDGE_PRELOAD", "true").lower() == "true"
RAG_PHASE1_ENABLED: bool = os.getenv("RAG_PHASE1_ENABLED", "true").lower() == "true"
RAG_PHASE2_ENABLED: bool = os.getenv("RAG_PHASE2_ENABLED", "true").lower() == "true"

# Knowledge Base Paths
KNOWLEDGE_BASE_PATH: str = os.getenv("KNOWLEDGE_BASE_PATH", "./knowledge_base")
CHROMA_PERSIST_DIRECTORY: str = os.getenv(
    "CHROMA_PERSIST_DIRECTORY",
    "./knowledge_base/chroma_db"
)


# ==========================================
# LangSmith Tracing Configuration
# ==========================================

LANGCHAIN_TRACING_V2: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "village-planning-agent")
LANGCHAIN_ENDPOINT: str | None = os.getenv("LANGCHAIN_ENDPOINT")
LANGCHAIN_CALLBACKS_BACKGROUND: bool = os.getenv("LANGCHAIN_CALLBACKS_BACKGROUND", "true").lower() == "true"


# ==========================================
# Planning Configuration
# ==========================================

# Default task and constraints
DEFAULT_TASK_DESCRIPTION: str = os.getenv(
    "DEFAULT_TASK_DESCRIPTION",
    "制定村庄总体规划方案"
)
DEFAULT_CONSTRAINTS: str = os.getenv(
    "DEFAULT_CONSTRAINTS",
    "无特殊约束"
)

# Execution mode defaults
DEFAULT_STEP_MODE: bool = os.getenv("DEFAULT_STEP_MODE", "true").lower() in ("1", "true", "yes")
DEFAULT_STREAM_MODE: bool = os.getenv("DEFAULT_STREAM_MODE", "true").lower() in ("1", "true", "yes")
DEFAULT_ENABLE_REVIEW: bool = os.getenv("DEFAULT_ENABLE_REVIEW", "false").lower() in ("1", "true", "yes")
