"""
配置加载器测试
"""

import pytest
from pathlib import Path

from src.config.loader import (
    load_config,
    PlanningConfig,
    PhaseConfig,
    DimensionConfig,
)


class TestLoadConfig:
    """配置加载测试"""

    def test_load_config_returns_planning_config(self):
        """加载配置返回 PlanningConfig 类型"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        assert isinstance(config, PlanningConfig)

    def test_config_has_three_phases(self):
        """配置包含三个阶段"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        assert len(config.phases) == 3

    def test_layer1_has_twelve_dimensions(self):
        """Layer 1 包含 12 个维度"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        layer1 = config.phases[0]
        assert layer1.id == "layer1"
        assert len(layer1.dimensions) == 12

    def test_layer2_has_four_dimensions(self):
        """Layer 2 包含 4 个维度"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        layer2 = config.phases[1]
        assert layer2.id == "layer2"
        assert len(layer2.dimensions) == 4

    def test_layer3_has_twelve_dimensions(self):
        """Layer 3 包含 12 个维度"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        layer3 = config.phases[2]
        assert layer3.id == "layer3"
        assert len(layer3.dimensions) == 12

    def test_layer1_execution_is_parallel(self):
        """Layer 1 执行模式为 parallel"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        assert config.phases[0].execution == "parallel"

    def test_layer2_execution_is_wave(self):
        """Layer 2 执行模式为 wave"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        assert config.phases[1].execution == "wave"

    def test_dimension_has_required_fields(self):
        """维度包含必需字段"""
        config_path = Path(__file__).parent.parent.parent / "src" / "config" / "planning_phases.yaml"
        config = load_config(str(config_path))
        dim = config.phases[0].dimensions[0]
        assert dim.key == "location"
        assert dim.name == "区位与对外交通分析"
        assert isinstance(dim.tools, list)
        assert isinstance(dim.rag_query, str)
        assert isinstance(dim.depends_on, list)


class TestDimensionConfig:
    """维度配置模型测试"""

    def test_dimension_config_defaults(self):
        """维度配置默认值"""
        dim = DimensionConfig(key="test", name="测试维度")
        assert dim.tools == []
        assert dim.rag_query == ""
        assert dim.depends_on == []


class TestPhaseConfig:
    """阶段配置模型测试"""

    def test_phase_config_structure(self):
        """阶段配置结构"""
        phase = PhaseConfig(
            id="test_phase",
            name="测试阶段",
            execution="parallel",
            dimensions=[]
        )
        assert phase.id == "test_phase"
        assert phase.execution == "parallel"