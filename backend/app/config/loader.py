"""
配置加载器

从 YAML 文件加载规划阶段配置，使用 Pydantic 进行验证。
"""

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class DimensionSemanticConfig(BaseModel):
    """Semantic contract owned by one YAML dimension entry."""

    focus: str = ""
    l1_fact_types: List[str] = Field(default_factory=list)
    l3_claim_families: List[str] = Field(default_factory=list)
    l3_grounding_requirements: List[str] = Field(default_factory=list)
    spatial_authority: str = ""
    source_section_hints: List[str] = Field(default_factory=list)


class DimensionEvidenceConfig(BaseModel):
    """Retrieval boundary owned by one YAML dimension entry."""

    entity_scope: List[str] = Field(default_factory=list)


class DimensionConfig(BaseModel):
    """维度配置"""
    key: str
    name: str
    tools: List[str] = Field(default_factory=list)
    rag_query: str = ""
    prefer_doc_types: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)
    layer_depends_on: List[str] = Field(default_factory=list)
    phase_depends_on: List[str] = Field(default_factory=list)
    # P1: KG 查询命名空间分派（"analysis" | "shared" | "execute" | 组合）
    #   L1 默认 analysis；L2 用 analysis+shared；L3 用 execute+shared。
    kg_query: str = ""
    # Prompt/evidence boundary owned by the same YAML dimension definition.
    semantic: DimensionSemanticConfig = Field(default_factory=DimensionSemanticConfig)
    evidence: DimensionEvidenceConfig = Field(default_factory=DimensionEvidenceConfig)


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

    config = PlanningConfig(**raw_data)
    dimensions = [dim for phase in config.phases for dim in phase.dimensions]
    keys = [dim.key for dim in dimensions]
    if len(keys) != 28 or len(set(keys)) != 28:
        raise ValueError(f"phases.yaml must contain 28 unique dimensions, got {len(keys)}")
    for dim in dimensions:
        semantic = dim.semantic
        required = (
            semantic.focus,
            semantic.l1_fact_types,
            semantic.l3_claim_families,
            semantic.l3_grounding_requirements,
            semantic.spatial_authority,
            dim.evidence.entity_scope,
        )
        if any(not value for value in required):
            raise ValueError(f"dimension {dim.key!r} has incomplete semantic/evidence configuration")
        for field_name, values in (
            ("l1_fact_types", semantic.l1_fact_types),
            ("l3_claim_families", semantic.l3_claim_families),
            ("l3_grounding_requirements", semantic.l3_grounding_requirements),
            ("entity_scope", dim.evidence.entity_scope),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"dimension {dim.key!r} has duplicate {field_name}")
    return config


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
