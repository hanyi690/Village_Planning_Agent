import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# Project root directory (cross-platform)
# backend/app/core/settings.py -> PROJECT_ROOT = project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY")

# DashScope (阿里云百炼) API 配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_BASE = os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# LLM Configuration
# LLM_PROVIDER: 必填，可选值: "deepseek", "openai", "zhipuai"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.5-plus")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8192"))

# LLM Request Timeout (seconds)
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "180"))  # 3 minutes
LLM_STREAM_TIMEOUT = int(os.getenv("LLM_STREAM_TIMEOUT", "300"))  # 5 minutes

# LLM Max Concurrent Requests (for asyncio.gather)
# DashScope limit: ~5-10 concurrent requests
# Updated from 4 to 8 for better parallelism
LLM_MAX_CONCURRENT = int(os.getenv("LLM_MAX_CONCURRENT", "8"))

# OpenAI-compatible API base URL (for DeepSeek, etc.)
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")

# ==========================================
# RAG / Vector Store Configuration
# ==========================================
# Basic settings
VECTOR_STORE_DIR = os.getenv("VECTOR_STORE_DIR", str(PROJECT_ROOT / "vectordb"))
VECTORDB_PERSIST = os.getenv("VECTORDB_PERSIST", "true").lower() in ("1", "true", "yes")
RAG_ENABLED = os.getenv("RAG_ENABLED", "true").lower() in ("1", "true", "yes")

# Data directory structure
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_BASE_DIR = DATA_DIR / "knowledge_base"
DATABASE_DIR = DATA_DIR / "database"

# Vector database type: chroma (default), faiss, qdrant
VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE", "chroma")

# Chroma configuration
CHROMA_PERSIST_DIR = DATA_DIR / "chroma_db"
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
# Provider: local (HuggingFace) or aliyun (DashScope API)
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local")

# Local model (EMBEDDING_PROVIDER=local)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")  # cuda, mps

# Aliyun DashScope (EMBEDDING_PROVIDER=aliyun)
ALIYUN_EMBEDDING_MODEL = os.getenv("ALIYUN_EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))

# HuggingFace mirror
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

# ==========================================
# Text Splitting Configuration
# ==========================================
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "500"))
ADD_START_INDEX = os.getenv("ADD_START_INDEX", "true").lower() == "true"

# ==========================================
# Retrieval Configuration
# ==========================================
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
RETRIEVE_SCORE_THRESHOLD = float(os.getenv("RETRIEVE_SCORE_THRESHOLD", "0.7"))
QUERY_CACHE_TTL = int(os.getenv("QUERY_CACHE_TTL", "0"))

# Default LLM provider for summarization tasks
DEFAULT_PROVIDER = os.getenv("MODEL_PROVIDER", LLM_PROVIDER)

# ==========================================
# OSS Configuration (for knowledge base sync)
# ==========================================

OSS_ACCESS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID", "")
OSS_ACCESS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-shenzhen.aliyuncs.com")
OSS_BUCKET_NAME = os.getenv("OSS_BUCKET_NAME", "")
OSS_KB_PATH = os.getenv("OSS_KB_PATH", "knowledge_base/chroma_db")

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

# ==========================================
# Backend Session Configuration (from constants/config.py)
# ==========================================

# Session Event Configuration
MAX_SESSION_EVENTS = 5000

# Event Cleanup Configuration
EVENT_CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes
SESSION_TTL_HOURS = 24

# SSE Queue Configuration
# Increased from 500 to 2000 to handle high-frequency events (dimension_delta)
SSE_QUEUE_SIZE = 2000

# Queue full wait timeout (100ms) - fallback to pending_events cache
SSE_QUEUE_WAIT_TIMEOUT = 0.1

# ==========================================
# Multimodal Configuration
# ==========================================

MULTIMODAL_ENABLED = os.getenv("MULTIMODAL_ENABLED", "false").lower() == "true"
MULTIMODAL_MODEL = os.getenv("MULTIMODAL_MODEL", "gpt-4o")
IMAGE_DETAIL_LEVEL = os.getenv("IMAGE_DETAIL_LEVEL", "auto")  # "low", "high", or "auto"
MAX_IMAGE_SIZE_MULTIMODAL = int(os.getenv("MAX_IMAGE_SIZE_MULTIMODAL", "10_000_000"))  # 10MB
DEFAULT_IMAGE_FORMAT = os.getenv("DEFAULT_IMAGE_FORMAT", "jpeg")  # jpeg, png, gif, webp

# ==========================================
# Flash Model Configuration (OpenAI-compatible format via DashScope)
# ==========================================
# Flash model is used for lightweight tasks: summaries, keyword extraction, etc.
# Uses DashScope's OpenAI-compatible endpoint for unified calling pattern.

FLASH_MODEL_NAME = os.getenv("FLASH_MODEL_NAME", "qwen-flash")
FLASH_MODEL_MAX_TOKENS = int(os.getenv("FLASH_MODEL_MAX_TOKENS", "500"))
FLASH_MODEL_TEMPERATURE = float(os.getenv("FLASH_MODEL_TEMPERATURE", "0.3"))


# ==========================================
# HuggingFace Environment Setup
# ==========================================

def get_huggingface_cache_dir() -> Path:
    """
    Get HuggingFace cache directory.
    Priority: HF_HOME > HF_HUB_CACHE > default ~/.cache/huggingface
    """
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home)

    hf_hub_cache = os.getenv("HF_HUB_CACHE")
    if hf_hub_cache:
        return Path(hf_hub_cache)

    return Path.home() / ".cache" / "huggingface"


def check_model_cached(model_name: str = None) -> bool:
    """
    Check if model is cached locally.

    Args:
        model_name: Model name, defaults to EMBEDDING_MODEL_NAME

    Returns:
        True if model is cached and complete
    """
    model_name = model_name or EMBEDDING_MODEL_NAME

    cache_dir = get_huggingface_cache_dir()
    model_cache_name = "models--" + model_name.replace("/", "--")
    model_cache_path = cache_dir / "hub" / model_cache_name

    if not model_cache_path.exists():
        return False

    snapshots_dir = model_cache_path / "snapshots"
    if not snapshots_dir.exists():
        return False

    no_exist_path = model_cache_path / ".no_exist"
    for snapshot in snapshots_dir.iterdir():
        if snapshot.is_dir():
            has_model = list(snapshot.glob("*.bin")) or list(snapshot.glob("*.safetensors"))
            if has_model:
                if no_exist_path.exists():
                    try:
                        no_exist_path.unlink()
                    except Exception:
                        pass
                return True

    return False


def setup_huggingface_env(force_offline: bool = None, force_online: bool = False):
    """
    Configure HuggingFace environment.
    Auto-detect model cache, decide offline mode or mirror download.

    Args:
        force_offline: Force offline mode (None = auto-detect)
        force_online: Force online mode (for first download)
    """
    model_cached = check_model_cached()

    if force_online:
        use_offline = False
    elif force_offline is not None:
        use_offline = force_offline
    else:
        use_offline = model_cached

    if use_offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        print(f"Model cached, offline mode enabled: {EMBEDDING_MODEL_NAME}")
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)

        if HF_ENDPOINT:
            os.environ["HF_ENDPOINT"] = HF_ENDPOINT
            print(f"Model not cached, using mirror: {HF_ENDPOINT}")
        else:
            print(f"Model not cached, downloading from HuggingFace official")