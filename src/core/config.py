import os
from dotenv import load_dotenv

load_dotenv(override=True)

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY")

# LLM Configuration
# LLM_PROVIDER: 必填，可选值: "deepseek", "openai", "zhipuai"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))

# OpenAI-compatible API base URL (for DeepSeek, etc.)
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")

# RAG / Vector store settings
VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", "f:\\project\\Village_Planning_Agent\\vectordb")
VECTORDB_PERSIST = os.getenv("VECTORDB_PERSIST", "true").lower() in ("1", "true", "yes")

# ==========================================
# LangSmith 追踪配置
# ==========================================
LANGCHAIN_TRACING_V2 = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.getenv("LANGCHAIN_PROJECT", "village-planning-agent")
LANGCHAIN_ENDPOINT = os.getenv("LANGCHAIN_ENDPOINT", None)
LANGCHAIN_CALLBACKS_BACKGROUND = os.getenv("LANGCHAIN_CALLBACKS_BACKGROUND", "true").lower() == "true"

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
