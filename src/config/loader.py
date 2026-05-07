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


def load_config(path: str = "src/config/planning_phases.yaml") -> PlanningConfig:
    """
    加载 YAML 配置文件

    Args:
        path: 配置文件路径，默认为 src/config/planning_phases.yaml

    Returns:
        PlanningConfig: 验证后的配置对象
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(config_path, encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    return PlanningConfig(**raw_data)


def get_phase_by_id(config: PlanningConfig, phase_id: str) -> Optional[PhaseConfig]:
    """
    根据阶段 ID 获取阶段配置

    Args:
        config: 规划配置
        phase_id: 阶段 ID (layer1, layer2, layer3)

    Returns:
        PhaseConfig or None
    """
    for phase in config.phases:
        if phase.id == phase_id:
            return phase
    return None


def get_dimension_by_key(
    config: PlanningConfig, phase_id: str, dimension_key: str
) -> Optional[DimensionConfig]:
    """
    根据维度键获取维度配置

    Args:
        config: 规划配置
        phase_id: 阶段 ID
        dimension_key: 维度键

    Returns:
        DimensionConfig or None
    """
    phase = get_phase_by_id(config, phase_id)
    if not phase:
        return None

    for dim in phase.dimensions:
        if dim.key == dimension_key:
            return dim
    return None