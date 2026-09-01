import json
import os
from pathlib import Path
from dotenv import load_dotenv
from app.core.llm_config import get_llm_settings

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

# Implicit LLM calls use MiniMax high-speed unless a provider/model override is
# supplied explicitly.
DEFAULT_LLM_MODEL = "MiniMax-M2.7-highspeed"

# Compatibility exports remain available to the rest of the application, but
# their values now come from the same typed snapshot used by the factory and
# Instructor.  This prevents one client path from silently selecting a
# different provider, model, endpoint, or protocol.
LLM_CONFIG = get_llm_settings()
LLM_PROVIDER = LLM_CONFIG.provider
LLM_MODEL = LLM_CONFIG.llm_model
MAX_TOKENS = LLM_CONFIG.max_tokens
OPENAI_API_KEY = LLM_CONFIG.openai_api_key
ZHIPUAI_API_KEY = LLM_CONFIG.zhipuai_api_key
DASHSCOPE_API_KEY = LLM_CONFIG.dashscope_api_key
DASHSCOPE_API_BASE = LLM_CONFIG.dashscope_api_base
MINIMAX_API_KEY = LLM_CONFIG.minimax_api_key
MINIMAX_API_BASE = LLM_CONFIG.minimax_api_base
MINIMAX_MODEL = LLM_CONFIG.minimax_model
OPENCODE_GO_API_KEY = LLM_CONFIG.opencode_go_api_key
OPENCODE_GO_API_BASE = LLM_CONFIG.opencode_go_api_base
OPENCODE_GO_MODEL = LLM_CONFIG.opencode_go_model
LLM_STRUCTURED_MODE = LLM_CONFIG.structured_mode
LLM_PROVIDER_MAX_RETRIES = LLM_CONFIG.provider_max_retries
LLM_PROVIDER_REQUEST_TIMEOUT = LLM_CONFIG.request_timeout_seconds()
DATA_TEMPORAL_ADMISSION_LLM_ENABLED = bool(
    LLM_CONFIG.data_temporal_admission_llm_enabled
)

_PROVIDER_CONCURRENCY_DEFAULT = (
    LLM_CONFIG.provider_concurrency()
)

# L1 dimensions fan out concurrently, but each dimension still emits a
# potentially large typed observation array before its separate report pass.
# Keep a bounded per-request budget while leaving enough headroom for source
# lineage and structured observations.  These are request/output budgets, not
# model context-window limits.
L1_MAX_TOKENS = LLM_CONFIG.stage_policy("l1").max_tokens
L1_REPORT_MAX_TOKENS = LLM_CONFIG.stage_policy("l1").report_max_tokens
# A length-retry is a separate, one-shot ceiling.  It is deliberately larger
# than the normal L1 request but remains bounded and provider-configurable.
LLM_INCOMPLETE_OUTPUT_MAX_TOKENS = LLM_CONFIG.incomplete_output_max_tokens
L1_LLM_TIMEOUT_S = LLM_CONFIG.stage_policy("l1").timeout_s
L1_LLM_MAX_CONCURRENT = LLM_CONFIG.stage_concurrency("l1")
L1_TRANSIENT_RETRIES = LLM_CONFIG.stage_policy("l1").transient_retries
L1_TRANSIENT_RETRY_BACKOFF_S = (
    LLM_CONFIG.stage_policy("l1").transient_retry_backoff_s
)

# LLM Request Timeout (seconds)
LLM_REQUEST_TIMEOUT = int(LLM_CONFIG.request_timeout_seconds())
LLM_STREAM_TIMEOUT = int(LLM_CONFIG.stream_timeout)  # 10 minutes; real L3 dimensions take 228-483s, 120s caused spurious provider trips
DIMENSION_EXECUTION_TIMEOUT_S = float(
    os.getenv("DIMENSION_EXECUTION_TIMEOUT_S", str(min(1200, LLM_STREAM_TIMEOUT)))
)  # includes provider queue wait plus one long real request
LAYER_TIMEOUT_S = int(os.getenv("LAYER_TIMEOUT_S", "1800"))  # bounds a full provider wave set without allowing an unbounded fan-in
GROUND_ANCHOR_TIMEOUT_S = float(os.getenv("GROUND_ANCHOR_TIMEOUT_S", "180"))  # optional L1 enrichment budget; never block L2 indefinitely
# Spatial grounding uses the shared LLM selector by default. One run still has
# a bounded call budget for grouped ambiguous mentions and typed topology-aware
# choices; the deterministic candidate graph always runs first, so these are
# evidence-constrained calls rather than blind generation.
GROUND_LLM_CALL_TIMEOUT_S = float(LLM_CONFIG.ground_call_timeout_s)
GROUND_MAX_LLM_CALLS = int(LLM_CONFIG.ground_max_calls)
GROUND_LLM_MAX_CONCURRENT = LLM_CONFIG.stage_concurrency("ground")
# One initial selector wave plus at most two shared-context recovery waves.
# The runtime clamps this to 1..3 so repeated provider calls stay bounded.
GROUND_MAX_RECOVERY_ROUNDS = int(LLM_CONFIG.ground_max_recovery_rounds)
GROUND_QUERY_SPEC_MAX_TOKENS = int(LLM_CONFIG.ground_query_spec_max_tokens)
GROUND_LLM_MAX_TOKENS = int(LLM_CONFIG.ground_max_tokens)
GROUND_LLM_PARSE_RETRIES = int(LLM_CONFIG.ground_parse_retries)
GROUND_LLM_ENABLED = bool(LLM_CONFIG.ground_llm_enabled)
RAG_TIMEOUT_S = int(os.getenv("RAG_TIMEOUT_S", "60"))  # per-dimension RAG retrieval cap
EXTERNAL_ANCHOR_TIMEOUT_S = int(os.getenv("EXTERNAL_ANCHOR_TIMEOUT_S", "30"))  # 外源锚点总预算，超时跳过（绝不阻塞 L1 派发）
# Normalized map observations are loaded from this local cache only.  The
# loader never owns an HTTP client; changing this path therefore cannot turn
# evidence retrieval into an implicit provider request.
EXTERNAL_MAP_CACHE_ROOT = os.getenv(
    "EXTERNAL_MAP_CACHE_ROOT",
    str(PROJECT_ROOT / "output" / "map_validation"),
)
# World-model migration mode.  ``off`` preserves the compatibility runtime;
# ``shadow``/``prefer_v2`` are rollout modes; ``v2_only`` requires callers to
# provide a normalized DATA catalog and never builds a Bundle/KG fallback.
COGNITION_WORLD_MODEL_MODE = os.getenv(
    "COGNITION_WORLD_MODEL_MODE", "off"
).strip().lower()
if COGNITION_WORLD_MODEL_MODE not in {"off", "shadow", "prefer_v2", "v2_only"}:
    COGNITION_WORLD_MODEL_MODE = "off"

def _parse_dimension_timeouts(raw: str) -> dict[str, float]:
    """Parse the per-dimension idle-timeout map from ``DIMENSION_TIMEOUT_S``.

    JSON object of ``{"<dimension_key>": seconds}``; any malformed value is
    dropped so a bad config can never crash the workflow import.
    """
    if not str(raw or "").strip():
        return {}
    try:
        payload = json.loads(str(raw))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    timeouts: dict[str, float] = {}
    for key, value in payload.items():
        key = str(key or "").strip()
        if not key:
            continue
        try:
            timeout = float(value)
        except (TypeError, ValueError):
            continue
        if timeout > 0:
            timeouts[key] = timeout
    return timeouts


# A7: per-dispatch idle timeout for long-tail dimensions, keyed by dimension
# key (LangGraph Send(timeout=TimeoutPolicy(idle_timeout=...))).  Empty by
# default; long-tail dimensions keep the shared layer deadline otherwise.
DIMENSION_TIMEOUT_S = _parse_dimension_timeouts(os.getenv("DIMENSION_TIMEOUT_S", "{}"))

# LLM Max Concurrent Requests.  This is the single default provider budget;
# L2/L3 may override it explicitly for a provider-specific deployment.
LLM_MAX_CONCURRENT = LLM_CONFIG.provider_concurrency()

# Optional OpenAI-compatible reasoning control (for example DeepSeek V4
# Flash through OpenCode Go).  Empty keeps the provider's native default.
LLM_REASONING_EFFORT = LLM_CONFIG.reasoning_effort.strip()

# Consecutive transport failures required before opening the session circuit.
# A single transient 5xx should not deadlock the whole fan-out layer.
LLM_PROVIDER_CIRCUIT_FAILURE_THRESHOLD = max(
    1, int(LLM_CONFIG.provider_circuit_failure_threshold)
)

# LLM Rate Limit (requests_per_second for InMemoryRateLimiter)
LLM_RATE_LIMIT_RPS = float(os.getenv("LLM_RATE_LIMIT_RPS", "500"))

# Cold start duration: linearly ramp concurrency from 1 to max over this period
LLM_WARMUP_SECONDS = float(os.getenv("LLM_WARMUP_SECONDS", "5.0"))

# Embedding API rate limits (text-embedding-v4 ~30 QPS)
EMBEDDING_MAX_CONCURRENT = int(LLM_CONFIG.embedding_max_concurrent)
EMBEDDING_RATE_LIMIT_RPS = float(LLM_CONFIG.embedding_rate_limit_rps)
RAG_DASHSCOPE_ENABLED = bool(LLM_CONFIG.rag_dashscope_enabled)

# LangGraph Send API parallel node limit.  Keep it aligned with the provider
# budget unless a deployment deliberately chooses a smaller graph fan-out.
GRAPH_MAX_CONCURRENCY = int(os.getenv("GRAPH_MAX_CONCURRENCY", str(LLM_MAX_CONCURRENT)))
KG_BUILD_TIMEOUT_SECONDS = float(os.getenv("KG_BUILD_TIMEOUT_SECONDS", "180"))
KG_STORAGE_BACKEND = os.getenv("KG_STORAGE_BACKEND", "rdf_memory").strip().lower()
KG_LAYER1_CACHE_MAXSIZE = int(os.getenv("KG_LAYER1_CACHE_MAXSIZE", "16"))
KG_QUERY_CACHE_MAXSIZE = int(os.getenv("KG_QUERY_CACHE_MAXSIZE", "512"))
EVIDENCE_CACHE_MAXSIZE = int(os.getenv("EVIDENCE_CACHE_MAXSIZE", "128"))
BACKEND_STARTUP_TIMEOUT_SECONDS = float(os.getenv("BACKEND_STARTUP_TIMEOUT_SECONDS", "30"))
# On process restart, only recent non-terminal sessions are inspected for a
# pending LangGraph checkpoint.  This is a recovery scan budget, not a graph
# execution timeout; HUMAN interrupts are always left parked for the operator.
RUNTIME_RECOVERY_MAX_SESSIONS = int(os.getenv("RUNTIME_RECOVERY_MAX_SESSIONS", "128"))
RUNTIME_RECOVERY_MAX_AGE_HOURS = float(os.getenv("RUNTIME_RECOVERY_MAX_AGE_HOURS", "24"))
GRAPH_RECURSION_LIMIT = int(os.getenv("GRAPH_RECURSION_LIMIT", "100"))
BUSINESS_RETRY_LIMIT = int(os.getenv("BUSINESS_RETRY_LIMIT", "3"))
# Per-session validation replay budget: total VALIDATE retries across the
# whole session (safety net above the per-stage BUSINESS_RETRY_LIMIT, e.g.
# interleaved EXECUTE/SELECT/L3 rework episodes).  Exhaustion degrades to a
# diagnostic terminal instead of looping stages forever.
VALIDATION_BUDGET_PER_SESSION = int(os.getenv("VALIDATION_BUDGET_PER_SESSION", "20"))
# Per-dimension LLM failure retries before the run degrades to a diagnostic
# terminal (provider resume re-dispatches ONLY the failed dimensions).
DIMENSION_RETRY_LIMIT = int(os.getenv("DIMENSION_RETRY_LIMIT", "1"))

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
ALIYUN_EMBEDDING_MODEL = LLM_CONFIG.embedding_model
EMBEDDING_DIMENSIONS = int(LLM_CONFIG.embedding_dimensions)

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

FLASH_MODEL_NAME = LLM_CONFIG.flash_model_name
FLASH_MODEL_MAX_TOKENS = int(LLM_CONFIG.flash_model_max_tokens)
FLASH_MODEL_TEMPERATURE = float(LLM_CONFIG.flash_model_temperature)

# ==========================================
# Semantic enrichment / vocabulary LLM configuration
# ==========================================
# These settings are shared by source-semantic enrichment and vocabulary
# extraction.  They are not a second retrieval path and must not be used as a
# deterministic fallback for EvidenceGraph resolution.

GIS_EXPLORE_LLM_ENABLED = bool(LLM_CONFIG.gis_explore_llm_enabled)
GIS_EXPLORE_MODEL = LLM_CONFIG.gis_explore_model
GIS_EXPLORE_MAX_TOKENS = int(LLM_CONFIG.gis_explore_max_tokens)
GIS_EXPLORE_TEMPERATURE = float(LLM_CONFIG.gis_explore_temperature)

# Source-label semantics are an explicit, quota-consuming Minimax step.  Keep
# it off for local/demo runs; production enables it when the provider budget
# and the current L1 snapshot are ready.  Disabled means unresolved/ambiguous,
# never a deterministic label fallback.
SOURCE_SEMANTIC_LLM_ENABLED = bool(LLM_CONFIG.source_semantic_llm_enabled)
