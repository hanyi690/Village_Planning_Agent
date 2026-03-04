"""
RAG 知识库配置
支持环境变量覆盖，适配 Docker 部署
"""
import os
from pathlib import Path
from typing import Literal

# ==================== 项目路径配置 ====================
PROJECT_ROOT = Path(__file__).parent.parent.parent
SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"  # 指向项目根目录的 data/ 目录
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"

# ==================== 向量数据库配置 ====================
# 支持的环境变量
VECTOR_DB_TYPE: Literal["chroma", "faiss", "qdrant"] = os.getenv(
    "VECTOR_DB_TYPE", "chroma"
)

# Chroma 配置（默认）
CHROMA_PERSIST_DIR = KNOWLEDGE_BASE_DIR / "chroma_db"
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "rural_planning")

# FAISS 配置（可选）
FAISS_INDEX_PATH = KNOWLEDGE_BASE_DIR / "faiss_index"

# Qdrant 配置（生产环境推荐）
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "rural_planning")

# ==================== Embedding 模型配置 ====================
# Embedding Provider: local (HuggingFace 本地) 或 aliyun (阿里云 DashScope API)
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local")

# 本地模型配置 (EMBEDDING_PROVIDER=local)
EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "BAAI/bge-small-zh-v1.5"  # 中文 Embedding 模型
)
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")  # 可选: cuda, mps

# 阿里云 DashScope Embedding API 配置 (EMBEDDING_PROVIDER=aliyun)
# 文档: https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
ALIYUN_EMBEDDING_BASE_URL = os.getenv(
    "ALIYUN_EMBEDDING_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
# 支持的模型: text-embedding-v4 (推荐), text-embedding-v3, text-embedding-v2
# text-embedding-v4 支持可变维度: 2048/1536/1024/768/512/256/128/64
ALIYUN_EMBEDDING_MODEL = os.getenv("ALIYUN_EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))

# ==================== HuggingFace 镜像和离线配置 ====================
# 国内镜像站点（首次下载模型时使用）
# 默认使用阿里云镜像，国内访问更快
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

# 离线模式配置（自动检测，模型存在时自动启用离线）
HF_HUB_OFFLINE = os.getenv("HF_HUB_OFFLINE", "") == "1"
TRANSFORMERS_OFFLINE = os.getenv("TRANSFORMERS_OFFLINE", "") == "1"


def get_huggingface_cache_dir() -> Path:
    """
    获取 HuggingFace 缓存目录
    优先级：HF_HOME > HF_HUB_CACHE > 默认 ~/.cache/huggingface
    """
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home)
    
    hf_hub_cache = os.getenv("HF_HUB_CACHE")
    if hf_hub_cache:
        return Path(hf_hub_cache)
    
    # 默认缓存目录
    return Path.home() / ".cache" / "huggingface"


def check_model_cached(model_name: str = None) -> bool:
    """
    检测模型是否已在本地缓存
    
    Args:
        model_name: 模型名称，默认使用 EMBEDDING_MODEL_NAME
        
    Returns:
        True 如果模型已缓存且完整
    """
    model_name = model_name or EMBEDDING_MODEL_NAME
    
    # 转换模型名称为缓存目录格式：BAAI/bge-small-zh-v1.5 -> models--BAAI--bge-small-zh-v1.5
    cache_dir = get_huggingface_cache_dir()
    model_cache_name = "models--" + model_name.replace("/", "--")
    model_cache_path = cache_dir / "hub" / model_cache_name
    
    if not model_cache_path.exists():
        return False
    
    # 检查 snapshots 目录是否有内容
    snapshots_dir = model_cache_path / "snapshots"
    if not snapshots_dir.exists():
        return False
    
    # 检查是否有有效的 snapshot（包含模型文件）
    no_exist_path = model_cache_path / ".no_exist"
    for snapshot in snapshots_dir.iterdir():
        if snapshot.is_dir():
            # 检查是否有模型文件（.bin 或 .safetensors）
            has_model = list(snapshot.glob("*.bin")) or list(snapshot.glob("*.safetensors"))
            if has_model:
                # 模型文件存在，清除可能存在的过期 .no_exist 标记
                # （之前下载可能中途失败留下了标记，但模型文件后来已完整下载）
                if no_exist_path.exists():
                    try:
                        no_exist_path.unlink()
                        print(f"🧹 已清除过期的 .no_exist 标记文件")
                    except Exception:
                        pass  # 忽略删除失败
                return True
    
    return False


def setup_huggingface_env(force_offline: bool = None, force_online: bool = False):
    """
    配置 HuggingFace 环境变量
    自动检测模型缓存，智能决定离线模式或镜像下载
    
    Args:
        force_offline: 强制离线模式（None 表示自动检测）
        force_online: 强制在线模式（用于首次下载）
    """
    model_cached = check_model_cached()
    
    # 决定是否使用离线模式
    if force_online:
        # 强制在线模式（首次下载）
        use_offline = False
    elif force_offline is not None:
        # 强制指定
        use_offline = force_offline
    else:
        # 自动检测：模型已缓存则使用离线模式
        use_offline = model_cached
    
    if use_offline:
        # 离线模式：避免网络请求超时
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        print(f"✅ 模型已缓存，启用离线模式: {EMBEDDING_MODEL_NAME}")
    else:
        # 在线模式：使用镜像站点下载
        os.environ.pop("HF_HUB_OFFLINE", None)
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        
        # 设置镜像站点
        if HF_ENDPOINT:
            os.environ["HF_ENDPOINT"] = HF_ENDPOINT
            print(f"📥 模型未缓存，使用镜像下载: {HF_ENDPOINT}")
        else:
            print(f"📥 模型未缓存，从 HuggingFace 官方下载")

# ==================== 文本分割配置 ====================
# 针对 Planning Agent 优化：更大的 chunk_size 保留更多上下文
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "2500"))  # 默认 2500（比传统 RAG 更大）
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "500"))  # 默认 500
ADD_START_INDEX = os.getenv("ADD_START_INDEX", "true").lower() == "true"

# ==================== 检索配置 ====================
# Planning Agent 需要更多上下文，默认返回更多文档
DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
RETRIEVE_SCORE_THRESHOLD = float(os.getenv("RETRIEVE_SCORE_THRESHOLD", "0.7"))

# ==================== 日志配置 ====================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ==================== LLM 模型配置 ====================
# 从主配置导入模型供应商配置
DEFAULT_PROVIDER = os.getenv("MODEL_PROVIDER", "deepseek")

# ==================== Docker 部署检测 ====================
def is_docker() -> bool:
    """检测是否运行在 Docker 容器中"""
    return Path("/.dockerenv").exists() or os.path.exists("/.dockerenv")

# ==================== 验证配置 ====================
def validate_config() -> None:
    """验证配置是否有效"""
    # 确保目录存在
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 验证向量数据库类型
    valid_db_types = ["chroma", "faiss", "qdrant"]
    if VECTOR_DB_TYPE not in valid_db_types:
        raise ValueError(
            f"无效的 VECTOR_DB_TYPE: {VECTOR_DB_TYPE}. "
            f"可选值: {valid_db_types}"
        )

    # 验证 chunk_size
    if CHUNK_SIZE < 100:
        raise ValueError(f"CHUNK_SIZE 太小: {CHUNK_SIZE}，最小值为 100")

    if CHUNK_OVERLAP >= CHUNK_SIZE:
        raise ValueError(
            f"CHUNK_OVERLAP ({CHUNK_OVERLAP}) "
            f"不能大于等于 CHUNK_SIZE ({CHUNK_SIZE})"
        )


# 初始化时验证
validate_config()


# ==================== 结构化元数据 Schema（未来优化预留）====================
# 用于 Phase 1 知识库重构：在入库时注入结构化元数据
# 支持 Phase 2 动态检索：基于维度、地形等元数据过滤
METADATA_SCHEMA = {
    "dimensions": list,        # 适用维度标识 ["traffic", "land_use", "infrastructure", ...]
    "terrain": list,           # 适用地形 ["mountain", "plain", "hill", "all"]
    "indicators": dict,        # 量化技术指标 {"道路红线宽度": ">=4m", "绿地率": ">=30%"}
    "constraints": list,       # 强制性约束 ["严禁破坏基本农田", "建设用地不超X公顷"]
    "source": str,             # 来源文档名称
    "chunk_index": int,        # 切片索引（在原文档中的位置）
    "document_type": str,      # 文档类型 ["policy", "standard", "case", "guide"]
    "effective_date": str,     # 生效日期（政策文件）
    "region": list,            # 适用地区 ["广东省", "梅州市", "平远县"]
}

# 维度-章节映射（用于 Phase 3 依赖矩阵切片）
DIMENSION_CHAPTER_MAPPING = {
    "land_use": ["用地分类", "土地整治", "三区三线"],
    "infrastructure": ["给排水", "电力", "通信", "环卫"],
    "traffic": ["道路系统", "交通组织", "停车设施"],
    "ecological": ["生态保护", "绿地系统", "景观风貌"],
    "disaster_prevention": ["防灾减灾", "消防安全", "防洪排涝"],
    "heritage": ["文物保护", "历史建筑", "非遗保护"],
}
