import os
from pathlib import Path
from dotenv import load_dotenv

# The supported production command runs with ``backend`` as cwd, while the
# repository-managed .env lives at the workspace root.  Relying on
# ``load_dotenv()`` alone therefore silently drops the configured provider
# and key.  Resolve both locations explicitly.  Process environment values
# retain precedence so a deployed/CI key cannot be overwritten by a stale
# workspace file.
_ENV_PROJECT_ROOT = (
    Path(os.getenv("PROJECT_ROOT")).resolve()
    if os.getenv("PROJECT_ROOT")
    else Path(__file__).resolve().parents[3]
)
load_dotenv(Path.cwd() / ".env", override=False)
load_dotenv(_ENV_PROJECT_ROOT / ".env", override=False)

IS_PRODUCTION = os.getenv("ENVIRONMENT") == "production"

# Project root directory (cross-platform)
# backend/app/core/settings.py -> PROJECT_ROOT = project root
# Support PROJECT_ROOT env var override (for Docker where file layout differs)
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "")).resolve() if os.getenv("PROJECT_ROOT") else Path(__file__).resolve().parent.parent.parent.parent

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY")

# DashScope (阿里云百炼) API 配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_BASE = os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# Implicit LLM calls use MiniMax high-speed unless a provider/model override is
# supplied explicitly.
DEFAULT_LLM_MODEL = "MiniMax-M2.7-highspeed"

# MiniMax OpenAI-compatible provider.  Keep this separate from the
# primary OPENAI_API_KEY/base pair so switching providers cannot silently send
# a MiniMax key to DashScope (or vice versa).
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
MINIMAX_API_BASE = os.getenv("MINIMAX_API_BASE", "https://api.minimaxi.com/v1")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", DEFAULT_LLM_MODEL)

# LLM Configuration
# MiniMax is the default provider; every model setting remains explicitly
# overridable for controlled experiments and provider-specific deployments.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "minimax")
LLM_MODEL = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))

# LLM Request Timeout (seconds)
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "180"))  # 3 minutes
LLM_STREAM_TIMEOUT = int(os.getenv("LLM_STREAM_TIMEOUT", "300"))  # 5 minutes

# LLM Max Concurrent Requests (for asyncio.gather + asyncio.Semaphore)
# qwen3.7-plus hard limit: 500 RPS / 30,000 RPM. 50 is safe with monitoring.
# Can be tuned up to 100 with cold start.
LLM_MAX_CONCURRENT = int(os.getenv("LLM_MAX_CONCURRENT", "3"))

# LLM Rate Limit (requests_per_second for InMemoryRateLimiter)
LLM_RATE_LIMIT_RPS = float(os.getenv("LLM_RATE_LIMIT_RPS", "500"))

# Cold start duration: linearly ramp concurrency from 1 to max over this period
LLM_WARMUP_SECONDS = float(os.getenv("LLM_WARMUP_SECONDS", "5.0"))

# Embedding API rate limits (text-embedding-v4 ~30 QPS)
EMBEDDING_MAX_CONCURRENT = int(os.getenv("EMBEDDING_MAX_CONCURRENT", "10"))
EMBEDDING_RATE_LIMIT_RPS = float(os.getenv("EMBEDDING_RATE_LIMIT_RPS", "25"))

# LangGraph Send API parallel node limit (prevents 28-dimension full-parallel burst)
GRAPH_MAX_CONCURRENCY = int(os.getenv("GRAPH_MAX_CONCURRENCY", "3"))
KG_BUILD_TIMEOUT_SECONDS = float(os.getenv("KG_BUILD_TIMEOUT_SECONDS", "180"))
BACKEND_STARTUP_TIMEOUT_SECONDS = float(os.getenv("BACKEND_STARTUP_TIMEOUT_SECONDS", "30"))
GRAPH_RECURSION_LIMIT = int(os.getenv("GRAPH_RECURSION_LIMIT", "100"))
BUSINESS_RETRY_LIMIT = int(os.getenv("BUSINESS_RETRY_LIMIT", "3"))

# OpenAI-compatible API base URL (for DeepSeek, etc.)
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")

# ==========================================
# RAG / Vector Store Configuration
# ==========================================
# Data directory structure (must be defined first)
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_BASE_DIR = DATA_DIR / "knowledge_base"
DATABASE_DIR = DATA_DIR / "database"

# GIS data directory (village-level spatial data organized by current/planned/api)
GIS_DATA_DIR = DATA_DIR / "gis"
JINTIAN_GIS_DIR = GIS_DATA_DIR / "jintian"

# RAG Document Cache (unified under data/RAG_doc/_cache/)
RAG_DOC_DIR = DATA_DIR / "RAG_doc"
RAG_CACHE_DIR = RAG_DOC_DIR / "_cache"
OUTLINE_INDEX_DIR = RAG_CACHE_DIR / "outline_index"
VECTOR_CACHE_DIR = RAG_CACHE_DIR / "vector_cache"
CHROMA_PERSIST_DIR = RAG_CACHE_DIR / "chroma_db_new"

# Basic settings
VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", str(CHROMA_PERSIST_DIR))
VECTORDB_PERSIST = os.getenv("VECTORDB_PERSIST", "true").lower() in ("1", "true", "yes")
RAG_ENABLED = os.getenv("RAG_ENABLED", "false").lower() in ("1", "true", "yes")

# Flash/instructor enrichment is optional and must not add a second LLM call
# to the hot path of real planning runs.
BACKGROUND_SUMMARY_ENRICHMENT = os.getenv("BACKGROUND_SUMMARY_ENRICHMENT", "false").lower() in ("1", "true", "yes")

# Vector database type: chroma (default), faiss, qdrant
VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE", "chroma")

# Chroma configuration
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "rural_planning")

# FAISS configuration
FAISS_INDEX_PATH = DATA_DIR / "faiss_index"

# Qdrant configuration (production)
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "rural_planning")

# ==========================================
# Embedding Model Configuration
# ==========================================
# 使用阿里云 DashScope Embedding API
ALIYUN_EMBEDDING_MODEL = os.getenv("ALIYUN_EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))

# ==========================================
# Text Splitting Configuration
# ==========================================
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "500"))
ADD_START_INDEX = os.getenv("ADD_START_INDEX", "true").lower() == "true"

# ==========================================
# Document Parser Configuration
# ==========================================

# Parser selection: "mineru" (default, best quality), "docling" (local), "markitdown" (fast)
DOCUMENT_PARSER = os.getenv("DOCUMENT_PARSER", "mineru")

# MinerU Configuration (cloud API, best quality)
MINERU_USE_AGENT_API = os.getenv("MINERU_USE_AGENT_API", "true").lower() == "true"
MINERU_TOKEN = os.getenv("MINERU_TOKEN", "")  # Required for Precise API (large files)
MINERU_TIMEOUT = int(os.getenv("MINERU_TIMEOUT", "300"))  # Poll timeout in seconds

# Docling Configuration (local, fallback)
DOCLING_USE_CUDA = os.getenv("DOCLING_USE_CUDA", "false").lower() == "true"
DOCLING_BATCH_SIZE = int(os.getenv("DOCLING_BATCH_SIZE", "50"))  # pages per batch
DOCLING_FORCE_OCR = os.getenv("DOCLING_FORCE_OCR", "false").lower() == "true"

# ==========================================
# Retrieval Configuration
# ==========================================
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
RETRIEVE_SCORE_THRESHOLD = float(os.getenv("RETRIEVE_SCORE_THRESHOLD", "0.7"))
MAX_MERGE_CONTENT_LENGTH = int(os.getenv("MAX_MERGE_CONTENT_LENGTH", "8000"))
QUERY_CACHE_TTL = int(os.getenv("QUERY_CACHE_TTL", "0"))

# LLM Chunking Configuration
LLM_CHUNK_ENABLED = os.getenv("LLM_CHUNK_ENABLED", "false").lower() == "true"
LLM_CHUNK_THRESHOLD = float(os.getenv("LLM_CHUNK_THRESHOLD", "0.7"))
LLM_CHUNK_MAX_DOC_SIZE = int(os.getenv("LLM_CHUNK_MAX_DOC_SIZE", "10000"))

# Default LLM provider for summarization tasks
DEFAULT_PROVIDER = os.getenv("MODEL_PROVIDER", LLM_PROVIDER)

# ==========================================
# OSS Configuration (for knowledge base sync)
# ==========================================

OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-shenzhen.aliyuncs.com")
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")
OSS_KB_PATH = os.getenv("OSS_KB_PATH", "RAG_doc/_cache/chroma_db_new")

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

# ==========================================
# GIS Configuration (天地图)
# ==========================================

# Map tile source (for visualization)
# Available options:
# - "tianditu": 天地图 tiles (国内推荐)
# - "geoq": GeoQ ArcGIS tiles (国内可用)
# - "openstreetmap": OSM tiles (国内可能不稳定)
GIS_TILE_SOURCE: str = os.getenv("GIS_TILE_SOURCE", "tianditu")

# ==========================================
# 天地图地理服务配置
# ==========================================

# 天地图 API Key (服务端密钥，校验 IP 白名单)
# 注意：需在天地图控制台配置 IP 白名单（本地测试可留空）
TIANDITU_API_KEY: str = os.getenv("TIANDITU_API_KEY", "")

# 天地图速率限制（每秒请求数）
TIANDITU_RATE_LIMIT: float = float(os.getenv("TIANDITU_RATE_LIMIT", "5.0"))

# 天地图最大重试次数
TIANDITU_MAX_RETRIES: int = int(os.getenv("TIANDITU_MAX_RETRIES", "3"))

# GIS 服务超时时间（秒）
GIS_TIMEOUT: int = int(os.getenv("GIS_TIMEOUT", "30"))

# ==========================================
# 广东省天地图专题服务配置
# ==========================================

# 广东省天地图Token（可选，若全国Key无法访问则使用）
GD_TIANDITU_TOKEN: str = os.getenv("GD_TIANDITU_TOKEN", TIANDITU_API_KEY)

# 广东省天地图服务基础URL（可配置）
# 每个服务有独立路径: /server/{service_id}/wmts, /server/{service_id}/wms
GD_TIANDITU_BASE_URL: str = os.getenv(
    "GD_TIANDITU_BASE_URL",
    "https://guangdong.tianditu.gov.cn"
)

# ==========================================
# 高德地图地理服务配置
# ==========================================

# 高德地图 API Key
AMAP_API_KEY: str = os.getenv("AMAP_API_KEY", "")

# 高德地图速率限制（每秒请求数）
AMAP_RATE_LIMIT: float = float(os.getenv("AMAP_RATE_LIMIT", "30.0"))

# 高德地图最大重试次数
AMAP_MAX_RETRIES: int = int(os.getenv("AMAP_MAX_RETRIES", "3"))

# ==========================================
# 百度地图地理服务配置
# ==========================================

# 百度地图 API Key
BAIDU_API_KEY: str = os.getenv("BAIDU_API_KEY", "")

# 百度地图速率限制（每秒请求数，默认 10）
BAIDU_RATE_LIMIT: float = float(os.getenv("BAIDU_RATE_LIMIT", "10.0"))

# 百度地图最大重试次数
BAIDU_MAX_RETRIES: int = int(os.getenv("BAIDU_MAX_RETRIES", "3"))

# ==========================================
# 腾讯地图地理服务配置
# ==========================================

# 腾讯地图 API Key
TECENT_MAP_API_KEY: str = os.getenv("TECENT_MAP_API_KEY", "")

# 腾讯地图速率限制（每秒请求数，默认 5）
TECENT_MAP_RATE_LIMIT: float = float(os.getenv("TECENT_MAP_RATE_LIMIT", "5.0"))

# 腾讯地图最大重试次数
TECENT_MAP_MAX_RETRIES: int = int(os.getenv("TECENT_MAP_MAX_RETRIES", "3"))

# ==========================================
# External Anchor Enrichment Switches
# ==========================================

# 是否启用 AMap 外源 POI 注入（村委会/设施/道路名/水库）
AMAP_EXTERNAL_ANCHOR_ENABLED: bool = os.getenv(
    "AMAP_EXTERNAL_ANCHOR_ENABLED", "false"
).lower() in ("1", "true", "yes")

# 是否启用百度外源 POI 注入
BAIDU_EXTERNAL_ANCHOR_ENABLED: bool = os.getenv(
    "BAIDU_EXTERNAL_ANCHOR_ENABLED", "false"
).lower() in ("1", "true", "yes")

# 是否启用腾讯地图外源 POI 注入
TECENT_MAP_EXTERNAL_ANCHOR_ENABLED: bool = os.getenv(
    "TECENT_MAP_EXTERNAL_ANCHOR_ENABLED", "false"
).lower() in ("1", "true", "yes")

# 是否启用天地图 WFS 矢量数据注入
TIANDITU_WFS_ANCHOR_ENABLED: bool = os.getenv(
    "TIANDITU_WFS_ANCHOR_ENABLED", "false"
).lower() in ("1", "true", "yes")

# WFS 单 layer 最多 features（防大查询）
TIANDITU_WFS_MAX_FEATURES: int = int(os.getenv("TIANDITU_WFS_MAX_FEATURES", "500"))

# ==========================================
# Knowledge Base Constants
# ==========================================

# 知识库类别
KB_CATEGORIES = ["policies", "cases", "standards", "domain", "local", "laws", "plans"]
KB_DEFAULT_CATEGORY = "policies"

# 知识库中文目录到英文标识的映射
KB_CATEGORY_MAPPING: dict = {
    "01 专业教材": {"category": "domain", "doc_type": "textbook"},
    "02 法律法规": {"category": "laws", "has_subcategories": True},
    "03 政策文件": {"category": "policies", "has_subcategories": True},
    "04 技术规范": {"category": "standards", "has_subcategories": True},
    "05 上位规划": {"category": "plans", "doc_type": "report"},
    "06 相关案例": {"category": "cases", "doc_type": "case"},
}

# 知识库层级标识（用于 policies/laws/standards 的子分类）
KB_LEVELS: list = ["national", "local", "administrative"]

# ==========================================
# Logging Configuration
# ==========================================

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE_MAX_BYTES = int(os.getenv("LOG_FILE_MAX_BYTES", str(10 * 1024 * 1024)))  # 10MB
LOG_FILE_BACKUP_COUNT = int(os.getenv("LOG_FILE_BACKUP_COUNT", "7"))
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))  # 自动清理 N 天前的日志

# ==========================================
# Backend Session Configuration (from constants/config.py)
# ==========================================

# Event Cleanup Configuration
EVENT_CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes
SESSION_TTL_HOURS = 24

# SSE Queue Configuration
# Increased from 500 to 2000 to handle high-frequency events (dimension_delta)
SSE_QUEUE_SIZE = 2000

# ==========================================
# Multimodal Configuration
# ==========================================

MULTIMODAL_ENABLED = os.getenv("MULTIMODAL_ENABLED", "false").lower() == "true"
MULTIMODAL_MODEL = os.getenv("MULTIMODAL_MODEL", DEFAULT_LLM_MODEL)
IMAGE_DETAIL_LEVEL = os.getenv("IMAGE_DETAIL_LEVEL", "auto")  # "low", "high", or "auto"
MAX_IMAGE_SIZE_MULTIMODAL = int(os.getenv("MAX_IMAGE_SIZE_MULTIMODAL", "10_000_000"))  # 10MB
DEFAULT_IMAGE_FORMAT = os.getenv("DEFAULT_IMAGE_FORMAT", "jpeg")  # jpeg, png, gif, webp

# ==========================================
# Flash Model Configuration (OpenAI-compatible format via DashScope)
# ==========================================
# Flash model is used for lightweight tasks: summaries, keyword extraction, etc.
# Uses the active provider's OpenAI-compatible endpoint for unified calling.

FLASH_MODEL_NAME = os.getenv("FLASH_MODEL_NAME", DEFAULT_LLM_MODEL)
FLASH_MODEL_MAX_TOKENS = int(os.getenv("FLASH_MODEL_MAX_TOKENS", "500"))
FLASH_MODEL_TEMPERATURE = float(os.getenv("FLASH_MODEL_TEMPERATURE", "0.3"))

# ==========================================
# EXPLORE Agent Flash LLM Configuration
# ==========================================
# Independent Flash model configuration for the EXPLORE agent.  Decoupled from
# FLASH_MODEL_* (which other subsystems share) so EXPLORE can opt-in/out and
# tune its own budget without touching RAG / metadata-extractor.
#
# - GIS_EXPLORE_LLM_ENABLED: master switch.  When False, ExploreFlashAgent
#   falls back to its deterministic baseline (no LLM calls).
# - GIS_EXPLORE_MODEL: dedicated Flash model name (MiniMax high-speed by
#   default).
# - GIS_EXPLORE_TEMPERATURE: lower than the main analysis LLM (0.1) so domain
#   classification / BSM extraction stay reproducible.
# - GIS_EXPLORE_MAX_TOKENS: budget for per-call Flash responses.

GIS_EXPLORE_LLM_ENABLED = os.getenv("GIS_EXPLORE_LLM_ENABLED", "true").lower() in {"1", "true", "yes"}
GIS_EXPLORE_MODEL = os.getenv("GIS_EXPLORE_MODEL", DEFAULT_LLM_MODEL)
GIS_EXPLORE_MAX_TOKENS = int(os.getenv("GIS_EXPLORE_MAX_TOKENS", "1200"))
GIS_EXPLORE_TEMPERATURE = float(os.getenv("GIS_EXPLORE_TEMPERATURE", "0.1"))
