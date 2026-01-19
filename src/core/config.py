import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")  # 可替换为环境中可用模型
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1500"))

# RAG / Vector store settings
VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", "f:\\project\\Village_Planning_Agent\\vectordb")
VECTORDB_PERSIST = os.getenv("VECTORDB_PERSIST", "true").lower() in ("1", "true", "yes")
