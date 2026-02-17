import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY")

# LLM Configuration
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4-flash")  # Default to GLM for fast, cost-effective inference
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "zhipuai")  # Options: "auto", "openai", "zhipuai"
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1500"))

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
