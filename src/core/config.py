import os
from dotenv import load_dotenv

load_dotenv(override=True)

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY")

# DashScope (阿里云百炼) API 配置
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_API_BASE = os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

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
# Knowledge Base Constants
# ==========================================

# 知识库类别
KB_CATEGORIES = ["policies", "cases", "standards", "domain", "local"]
KB_DEFAULT_CATEGORY = "policies"

# ==========================================
# Analysis Dimensions Constants
# ==========================================

# Layer 1 分析维度（现状分析）
ANALYSIS_DIMENSIONS = [
    "location",            # 区位分析
    "socio_economic",      # 社会经济分析
    "villager_wishes",     # 村民意愿与诉求分析
    "superior_planning",   # 上位规划与政策导向分析
    "natural_environment", # 自然环境分析
    "land_use",            # 土地利用分析
    "traffic",             # 道路交通分析
    "public_services",     # 公共服务设施分析
    "infrastructure",      # 基础设施分析
    "ecological_green",    # 生态绿地分析
    "architecture",        # 建筑分析
    "historical_culture",  # 历史文化分析
]

# Layer 1 关键维度（需要 RAG 知识检索）
CRITICAL_DIMENSIONS = [
    "land_use",
    "infrastructure",
    "ecological_green",
    "historical_culture",
    "superior_planning",
]

# 维度特定的知识检索查询模板
DIMENSION_QUERIES = {
    "land_use": "土地利用 用地分类 三区三线 建设用地标准 规划技术规范",
    "infrastructure": "基础设施 给排水 电力通信 污水处理 技术规范 建设标准",
    "ecological_green": "生态绿地 绿地系统 景观风貌 生态保护 绿地率 技术规范",
    "historical_culture": "历史文化 文物保护 传统村落 历史建筑 保护规划 规范",
    "superior_planning": "上位规划 政策法规 乡村振兴 十四五规划 指导意见",
}
