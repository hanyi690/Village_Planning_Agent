"""
配置加载器

从 YAML 文件加载规划阶段配置，使用 Pydantic 进行验证。
"""

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class DimensionConfig(BaseModel):
    """维度配置"""
    key: str
    name: str
    tools: List[str] = Field(default_factory=list)
    rag_query: str = ""
    depends_on: List[str] = Field(default_factory=list)
    layer_depends_on: List[str] = Field(default_factory=list)
    phase_depends_on: List[str] = Field(default_factory=list)


class PhaseConfig(BaseModel):
    """阶段配置"""
    id: str
    name: str
    execution: str  # "parallel" or "wave"
    dimensions: List[DimensionConfig]


class PlanningConfig(BaseModel):
    """规划配置"""
    phases: List[PhaseConfig]


def load_config(path: str = None) -> PlanningConfig:
    """加载 YAML 配置文件"""
    if path is None:
        # 使用相对于此文件的路径（loader.py 所在目录）
        path = Path(__file__).parent / "phases.yaml"
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    return PlanningConfig(**raw_data)


def get_phase_by_id(config: PlanningConfig, phase_id: str) -> Optional[PhaseConfig]:
    """根据阶段 ID 获取阶段配置"""
    for phase in config.phases:
        if phase.id == phase_id:
            return phase
    return None


def get_dimension_by_key(
    config: PlanningConfig, phase_id: str, dimension_key: str
) -> Optional[DimensionConfig]:
    """根据维度键获取维度配置"""
    phase = get_phase_by_id(config, phase_id)
    if not phase:
        return None

    for dim in phase.dimensions:
        if dim.key == dimension_key:
            return dim
    return None


# 全局配置缓存（延迟加载）
_CONFIG_CACHE: Optional[PlanningConfig] = None


def _get_cached_config() -> PlanningConfig:
    """获取缓存的配置（单例模式）"""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_config()
    return _CONFIG_CACHE


def get_dimension_config(dimension_key: str) -> Optional[DimensionConfig]:
    """获取指定维度的配置"""
    config = _get_cached_config()
    for phase in config.phases:
        for dim in phase.dimensions:
            if dim.key == dimension_key:
                return dim
    return None


def get_dimension_name(dimension_key: str) -> str:
    """获取指定维度的显示名称"""
    dim = get_dimension_config(dimension_key)
    return dim.name if dim else dimension_key


def list_dimensions(layer: Optional[int] = None) -> List[DimensionConfig]:
    """列出维度配置"""
    config = _get_cached_config()
    if layer is None:
        result = []
        for phase in config.phases:
            result.extend(phase.dimensions)
        return result

    phase_id = f"layer{layer}"
    phase = get_phase_by_id(config, phase_id)
    return phase.dimensions if phase else []


def get_layer_dimensions(layer: int) -> List[str]:
    """获取指定层的所有维度键名"""
    dims = list_dimensions(layer)
    return [dim.key for dim in dims]


def get_dimension_layer(dimension_key: str) -> Optional[int]:
    """获取维度所属的层级"""
    config = _get_cached_config()
    for phase in config.phases:
        for dim in phase.dimensions:
            if dim.key == dimension_key:
                return int(phase.id.replace("layer", ""))
    return None


def dimension_exists(dimension_key: str) -> bool:
    """检查维度是否存在"""
    return get_dimension_config(dimension_key) is not None


def get_analysis_dimension_names() -> dict:
    """获取现状分析维度名称映射"""
    dims = list_dimensions(1)
    return {dim.key: dim.name for dim in dims}


def get_concept_dimension_names() -> dict:
    """获取规划思路维度名称映射"""
    dims = list_dimensions(2)
    return {dim.key: dim.name for dim in dims}


def get_detailed_dimension_names() -> dict:
    """获取详细规划维度名称映射"""
    dims = list_dimensions(3)
    return {dim.key: dim.name for dim in dims}


def filter_reports_by_dependency(
    required_keys: List[str],
    reports: dict,
    name_mapping: dict
) -> str:
    """按依赖配置筛选报告并格式化"""
    filtered_parts = []
    for k in required_keys:
        if k in reports:
            name = name_mapping.get(k, k)
            filtered_parts.append(f"### {name}\n\n{reports[k]}\n")
    return "\n".join(filtered_parts) if filtered_parts else ""