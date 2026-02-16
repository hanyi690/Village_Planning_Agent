"""
维度配置加载器 - 从 YAML 配置文件加载维度映射信息

此模块替代旧的 dimension_mapping.py，通过加载 YAML 配置文件来提供相同的 API，
实现配置即代码的架构。

兼容性: 提供与原 dimension_mapping.py 相同的导出接口和函数。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
import threading

from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 配置缓存（线程安全）
# ==========================================

_dimensions_config: Optional[Dict[str, Any]] = None
_prompts_config: Optional[Dict[str, str]] = None
_config_lock = threading.Lock()


# ==========================================
# 配置加载函数
# ==========================================

def _load_all_configs() -> None:
    """加载所有配置文件（带缓存 + 线程安全）"""
    global _dimensions_config, _prompts_config

    # 快速路径：如果已加载，直接返回
    if _dimensions_config is not None:
        return

    # 使用锁保护配置加载
    with _config_lock:
        # 双重检查：可能在等待锁时已被其他线程加载
        if _dimensions_config is not None:
            return

        try:
            # 从 dimension_metadata.py 加载配置
            from ..config.dimension_metadata import DIMENSIONS_METADATA
            _dimensions_config = {"dimensions": DIMENSIONS_METADATA}
            _prompts_config = {}  # Prompt 不再从这里加载
            logger.info(f"[dimension_config] 配置加载完成: {len(DIMENSIONS_METADATA)} 个维度")
        except ImportError as e:
            logger.error(f"[dimension_config] 导入 dimension_metadata 失败: {e}")
            _dimensions_config = {"dimensions": {}}
            _prompts_config = {}
def get_dimensions_config() -> Dict[str, Any]:
    """获取完整的维度配置"""
    _load_all_configs()
    return _dimensions_config


def get_prompts_config() -> Dict[str, str]:
    """获取完整的 Prompt 配置"""
    _load_all_configs()
    return _prompts_config


# ==========================================
# 维度名称映射
# ==========================================

def _build_dimension_names_mapping(layer: int) -> Dict[str, str]:
    """
    构建指定层级的维度名称映射

    Args:
        layer: 层级编号 (1, 2, 3)

    Returns:
        维度 key 到名称的映射字典
    """
    config = get_dimensions_config()
    dimensions = config.get("dimensions", {})
    
    return {
        key: dim_data["name"]
        for key, dim_data in dimensions.items()
        if dim_data.get("layer") == layer
    }


def _build_full_dependency_chain() -> Dict[str, Any]:
    """
    从维度配置构建完整的三层依赖关系映射

    Returns:
        包含每个详细规划维度依赖链的字典
    """
    config = get_dimensions_config()
    dimensions = config.get("dimensions", {})
    
    chain = {}
    for key, dim_data in dimensions.items():
        if dim_data.get("layer") == 3:  # 只处理详细规划维度
            deps = dim_data.get("dependencies", {})
            chain[key] = {
                "layer1_analyses": deps.get("layer1_analyses", []),
                "layer2_concepts": deps.get("layer2_concepts", []),
                "wave": deps.get("wave", 1),
                "depends_on_detailed": deps.get("depends_on_detailed", [])
            }
    
    return chain


def _build_wave_config() -> Dict[int, Any]:
    """
    从维度配置构建波次配置

    Returns:
        波次配置字典
    """
    config = get_dimensions_config()
    dimensions = config.get("dimensions", {})
    
    waves = {}
    for key, dim_data in dimensions.items():
        if dim_data.get("layer") == 3:
            wave = dim_data.get("dependencies", {}).get("wave", 1)
            if wave not in waves:
                waves[wave] = {
                    "dimensions": [],
                    "description": f"Wave {wave}"
                }
            waves[wave]["dimensions"].append(key)
    
    # 添加描述
    if 1 in waves:
        waves[1]["description"] = "第一波次：11个独立维度完全并行执行"
    if 2 in waves:
        waves[2]["description"] = "第二波次：项目建设库（等待Wave 1完成）"
    
    return waves


# ==========================================
# 公共导出 - 维度名称映射
# ==========================================

def get_analysis_dimension_names() -> Dict[str, str]:
    """获取现状分析维度名称映射（Layer 1）"""
    return _build_dimension_names_mapping(1)


def get_concept_dimension_names() -> Dict[str, str]:
    """获取规划思路维度名称映射（Layer 2）"""
    return _build_dimension_names_mapping(2)


def get_detailed_dimension_names() -> Dict[str, str]:
    """获取详细规划维度名称映射（Layer 3）"""
    return _build_dimension_names_mapping(3)


# 延迟初始化的属性（兼容旧 API）
def ANALYSIS_DIMENSION_NAMES() -> Dict[str, str]:
    """现状分析维度名称映射"""
    return get_analysis_dimension_names()


def CONCEPT_DIMENSION_NAMES() -> Dict[str, str]:
    """规划思路维度名称映射"""
    return get_concept_dimension_names()


def DETAILED_DIMENSION_NAMES() -> Dict[str, str]:
    """详细规划维度名称映射"""
    return get_detailed_dimension_names()


# ==========================================
# 公共导出 - 依赖链和波次配置
# ==========================================

def get_full_dependency_chain() -> Dict[str, Any]:
    """获取完整的三层依赖关系映射"""
    return _build_full_dependency_chain()


def get_wave_config() -> Dict[int, Any]:
    """获取波次配置"""
    return _build_wave_config()


def get_default_adapter_config() -> Dict[str, List[str]]:
    """
    获取默认适配器配置

    Returns:
        维度到工具的映射字典
    """
    config = get_dimensions_config()
    return config.get("adapters", {})


# 延迟初始化的属性（兼容旧 API）
def FULL_DEPENDENCY_CHAIN() -> Dict[str, Any]:
    """完整的三层依赖关系映射"""
    return get_full_dependency_chain()


def WAVE_CONFIG() -> Dict[int, Any]:
    """波次配置"""
    return get_wave_config()


def DEFAULT_ADAPTER_CONFIG() -> Dict[str, List[str]]:
    """默认适配器配置"""
    return get_default_adapter_config()


# ==========================================
# 旧映射以保持向后兼容
# ==========================================

def get_analysis_to_concept_mapping() -> Dict[str, Any]:
    """
    获取现状分析维度到规划思路维度的映射

    Returns:
        映射字典
    """
    config = get_dimensions_config()
    dimensions = config.get("dimensions", {})
    
    mapping = {}
    for key, dim_data in dimensions.items():
        if dim_data.get("layer") == 2:  # Layer 2 dimensions
            deps = dim_data.get("dependencies", {})
            required_analyses = deps.get("layer1_analyses", [])
            
            # 添加描述
            descriptions = {
                "resource_endowment": "资源禀赋分析需要自然资源和土地利用信息",
                "planning_positioning": "规划定位分析需要区位和人文信息",
                "development_goals": "发展目标分析需要社会服务设施信息",
                "planning_strategies": "规划策略需要全面的现状信息"
            }
            
            mapping[key] = {
                "required_analyses": required_analyses,
                "description": descriptions.get(key, "")
            }
    
    return mapping


# ==========================================
# 依赖查询 API 函数
# ==========================================

def get_full_dependency_chain_func(detailed_dimension: str) -> dict:
    """
    获取指定详细规划维度的完整依赖链

    Args:
        detailed_dimension: 详细规划维度（如 "industry"）

    Returns:
        包含 layer1_analyses, layer2_concepts, wave, depends_on_detailed 的字典
    """
    chain = get_full_dependency_chain()
    return chain.get(detailed_dimension, {})


def get_execution_wave(detailed_dimension: str) -> int:
    """
    获取指定详细规划维度的执行波次

    Args:
        detailed_dimension: 详细规划维度

    Returns:
        波次编号 (1 或 2)，未找到返回 0
    """
    chain = get_full_dependency_chain()
    dim_chain = chain.get(detailed_dimension)
    if dim_chain:
        return dim_chain.get("wave", 0)
    return 0


def get_dimensions_by_wave(wave: int) -> list:
    """
    获取指定波次的所有维度

    Args:
        wave: 波次编号 (1 或 2)

    Returns:
        该波次的维度列表
    """
    wave_config = get_wave_config()
    config = wave_config.get(wave)
    if config:
        return config.get("dimensions", [])
    return []


def check_detailed_dependencies_ready(dimension: str, completed_dimensions: list) -> bool:
    """
    检查指定详细规划维度的依赖是否满足

    Args:
        dimension: 详细规划维度
        completed_dimensions: 已完成的维度列表

    Returns:
        True 如果依赖满足，False 否则
    """
    chain = get_full_dependency_chain()
    dim_chain = chain.get(dimension)
    if not dim_chain:
        return True  # 未找到依赖信息，默认可以执行

    depends_on = dim_chain.get("depends_on_detailed", [])
    if not depends_on:
        return True  # 无依赖，可以执行

    # 检查所有依赖是否都已完成
    return all(d in completed_dimensions for d in depends_on)


def visualize_dependency_graph() -> str:
    """
    生成依赖关系的 Mermaid 格式图（用于调试和文档）

    Returns:
        Mermaid 格式的依赖图字符串
    """
    lines = ["graph TD"]

    analysis_names = get_analysis_dimension_names()
    concept_names = get_concept_dimension_names()
    detailed_names = get_detailed_dimension_names()

    # 添加现状分析节点
    for dim, name in analysis_names.items():
        lines.append(f"    A1_{dim}[现状: {name}]")

    # 添加规划思路节点
    for dim, name in concept_names.items():
        lines.append(f"    A2_{dim}[思路: {name}]")

    # 添加详细规划节点
    for dim, name in detailed_names.items():
        wave = get_execution_wave(dim)
        lines.append(f"    A3_{dim}[详细: {name} (Wave {wave})]")

    # 添加依赖关系
    chain = get_full_dependency_chain()
    for detailed_dim, dim_chain in chain.items():
        # 现状 -> 详细规划
        for analysis_dim in dim_chain.get("layer1_analyses", []):
            lines.append(f"    A1_{analysis_dim} --> A3_{detailed_dim}")

        # 思路 -> 详细规划
        for concept_dim in dim_chain.get("layer2_concepts", []):
            if concept_dim != "ALL":
                lines.append(f"    A2_{concept_dim} --> A3_{detailed_dim}")

        # 详细规划间依赖
        for dep_dim in dim_chain.get("depends_on_detailed", []):
            lines.append(f"    A3_{dep_dim} -.-> A3_{detailed_dim}")

    return "\n".join(lines)


def get_wave_summary() -> dict:
    """
    获取波次执行摘要

    Returns:
        包含波次信息的字典
    """
    wave_config = get_wave_config()
    detailed_names = get_detailed_dimension_names()
    
    summary = {}
    for wave_num in sorted(wave_config.keys()):
        config = wave_config[wave_num]
        dimensions = config["dimensions"]
        summary[wave_num] = {
            "description": config["description"],
            "dimensions": dimensions,
            "count": len(dimensions),
            "dimension_names": [detailed_names[d] for d in dimensions]
        }
    return summary


def get_required_analyses_for_concept(concept_dimension: str) -> list:
    """
    获取指定规划思路维度需要的现状分析维度列表

    Args:
        concept_dimension: 规划思路维度（如 "resource_endowment"）

    Returns:
        需要的现状分析维度列表，如果需要所有维度则返回 ["ALL"]
    """
    mapping = get_analysis_to_concept_mapping()
    concept_mapping = mapping.get(concept_dimension)
    if concept_mapping:
        return concept_mapping["required_analyses"]
    return ["ALL"]


def get_required_info_for_detailed(detailed_dimension: str) -> dict:
    """
    获取指定详细规划维度需要的信息（从 FULL_DEPENDENCY_CHAIN 提取）

    Args:
        detailed_dimension: 详细规划维度（如 "industry"）

    Returns:
        包含 required_concepts 和 required_analyses 的字典
    """
    chain = get_full_dependency_chain()
    dim_chain = chain.get(detailed_dimension)
    if dim_chain:
        return {
            "required_concepts": dim_chain.get("layer2_concepts", []),
            "required_analyses": dim_chain.get("layer1_analyses", [])
        }
    return {
        "required_concepts": ["ALL"],
        "required_analyses": ["ALL"]
    }


def get_concept_to_detailed_mapping(detailed_dimension: str) -> dict:
    """
    从完整依赖链中提取规划思路维度映射（替代旧的 CONCEPT_TO_DETAILED_MAPPING）

    Args:
        detailed_dimension: 详细规划维度

    Returns:
        包含 required_concepts 和 required_analyses 的字典
    """
    return get_required_info_for_detailed(detailed_dimension)


# ==========================================
# 模块级别的缓存和导出
# ==========================================

# 创建缓存实例
_cached_analysis_names: Optional[Dict[str, str]] = None
_cached_concept_names: Optional[Dict[str, str]] = None
_cached_detailed_names: Optional[Dict[str, str]] = None
_cached_dependency_chain: Optional[Dict[str, Any]] = None
_cached_wave_config: Optional[Dict[int, Any]] = None
_cached_adapter_config: Optional[Dict[str, List[str]]] = None


# 提供模块级别的导出（兼容旧 API）
def _get_cached_or_compute(cache_var, compute_func):
    """获取缓存值或计算新值"""
    if cache_var is not None:
        return cache_var
    return compute_func()


# 导出常量（使用全局变量缓存，首次访问时加载）
_ANALYSIS_DIMENSION_NAMES = None
_CONCEPT_DIMENSION_NAMES = None
_DETAILED_DIMENSION_NAMES = None
_FULL_DEPENDENCY_CHAIN = None
_WAVE_CONFIG = None
_DEFAULT_ADAPTER_CONFIG = None
_ANALYSIS_TO_CONCEPT_MAPPING = None

def _ensure_configs_loaded():
    """确保配置已加载"""
    _load_all_configs()

def ANALYSIS_DIMENSION_NAMES():
    """获取现状分析维度名称映射"""
    global _ANALYSIS_DIMENSION_NAMES
    if _ANALYSIS_DIMENSION_NAMES is None:
        _ensure_configs_loaded()
        _ANALYSIS_DIMENSION_NAMES = _build_dimension_names_mapping(1)
    return _ANALYSIS_DIMENSION_NAMES

def CONCEPT_DIMENSION_NAMES():
    """获取规划思路维度名称映射"""
    global _CONCEPT_DIMENSION_NAMES
    if _CONCEPT_DIMENSION_NAMES is None:
        _ensure_configs_loaded()
        _CONCEPT_DIMENSION_NAMES = _build_dimension_names_mapping(2)
    return _CONCEPT_DIMENSION_NAMES

def DETAILED_DIMENSION_NAMES():
    """获取详细规划维度名称映射"""
    global _DETAILED_DIMENSION_NAMES
    if _DETAILED_DIMENSION_NAMES is None:
        _ensure_configs_loaded()
        _DETAILED_DIMENSION_NAMES = _build_dimension_names_mapping(3)
    return _DETAILED_DIMENSION_NAMES

def FULL_DEPENDENCY_CHAIN():
    """获取完整的三层依赖关系映射"""
    global _FULL_DEPENDENCY_CHAIN
    if _FULL_DEPENDENCY_CHAIN is None:
        _ensure_configs_loaded()
        _FULL_DEPENDENCY_CHAIN = _build_full_dependency_chain()
    return _FULL_DEPENDENCY_CHAIN

def WAVE_CONFIG():
    """获取波次配置"""
    global _WAVE_CONFIG
    if _WAVE_CONFIG is None:
        _ensure_configs_loaded()
        _WAVE_CONFIG = _build_wave_config()
    return _WAVE_CONFIG

def DEFAULT_ADAPTER_CONFIG():
    """获取默认适配器配置"""
    global _DEFAULT_ADAPTER_CONFIG
    if _DEFAULT_ADAPTER_CONFIG is None:
        _ensure_configs_loaded()
        _DEFAULT_ADAPTER_CONFIG = get_default_adapter_config()
    return _DEFAULT_ADAPTER_CONFIG

def ANALYSIS_TO_CONCEPT_MAPPING():
    """获取现状分析到规划思路的映射"""
    global _ANALYSIS_TO_CONCEPT_MAPPING
    if _ANALYSIS_TO_CONCEPT_MAPPING is None:
        _ensure_configs_loaded()
        _ANALYSIS_TO_CONCEPT_MAPPING = get_analysis_to_concept_mapping()
    return _ANALYSIS_TO_CONCEPT_MAPPING


__all__ = [
    # 维度名称映射
    "ANALYSIS_DIMENSION_NAMES",
    "CONCEPT_DIMENSION_NAMES",
    "DETAILED_DIMENSION_NAMES",
    # 依赖链和波次配置
    "FULL_DEPENDENCY_CHAIN",
    "WAVE_CONFIG",
    "DEFAULT_ADAPTER_CONFIG",
    # 旧映射
    "ANALYSIS_TO_CONCEPT_MAPPING",
    # 函数
    "get_full_dependency_chain",
    "get_execution_wave",
    "get_dimensions_by_wave",
    "check_detailed_dependencies_ready",
    "visualize_dependency_graph",
    "get_wave_summary",
    "get_required_analyses_for_concept",
    "get_required_info_for_detailed",
    "get_concept_to_detailed_mapping",
    # 配置获取函数
    "get_dimensions_config",
    "get_prompts_config",
    # 维度名称获取函数
    "get_analysis_dimension_names",
    "get_concept_dimension_names",
    "get_detailed_dimension_names",
]