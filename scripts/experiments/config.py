"""
Experiment Configuration
实验配置

定义实验场景、关键词检测列表、输出路径等配置。
"""

from pathlib import Path
from typing import Dict, List, Any

# ============================================
# Output Paths
# ============================================

OUTPUT_BASE = Path(__file__).parent.parent.parent / "output" / "experiments" / "cascade_consistency"
BASELINE_DIR = OUTPUT_BASE / "baseline"
SCENARIO1_DIR = OUTPUT_BASE / "scenario1_planning_positioning"
SCENARIO2_DIR = OUTPUT_BASE / "scenario2_natural_environment"
ANALYSIS_DIR = OUTPUT_BASE / "analysis"


# ============================================
# Scenario Definitions
# ============================================

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "scenario1": {
        "name": "驳回规划定位（Layer 2）",
        "target_dimension": "planning_positioning",
        "target_layer": 2,
        "feedback": """金田村常住人口仅500人，不具备承接大规模旅游的基础设施条件。
千年古檀树、古茶亭遗址等核心历史资源应划定为绝对保护对象，剥离重度商业开发权。
规划定位应转向生态保育优先、客家文化微改造的渐进式发展路径。""",
        # 预期影响范围（基于 get_impact_tree）
        "expected_impact": {
            "total_downstream": 8,  # 包括目标维度
            "max_wave": 2,
            "wave_distribution": {
                0: ["planning_positioning"],  # 目标维度
                1: ["development_goals", "planning_strategies", "industry", "spatial_structure", "land_use_planning"],
                2: ["project_bank"],
            },
        },
        # 关关键词检测
        "keywords": {
            "positive": ["生态保育", "渐进式发展", "客家文化微改造", "绝对保护", "保护优先", "微改造"],
            "negative": ["大规模旅游", "商业开发", "景区化", "旅游开发"],
        },
    },
    "scenario2": {
        "name": "驳回自然环境分析（Layer 1）",
        "target_dimension": "natural_environment",
        "target_layer": 1,
        "feedback": """现状报告中明确记载金田村存在5处崩塌隐患点和35处滑坡隐患点，
但当前分析未对隐患点的空间分布与影响范围进行充分评估，需强化地质灾害风险的分析深度。""",
        "expected_impact": {
            "total_downstream": 12,  # 包括目标维度
            "max_wave": 3,
            "wave_distribution": {
                0: ["natural_environment"],
                1: ["resource_endowment", "ecological", "spatial_structure", "land_use_planning", "disaster_prevention", "infrastructure_planning"],
                2: ["planning_positioning", "planning_strategies"],
                3: ["development_goals", "project_bank"],
            },
        },
        "keywords": {
            "positive": ["崩塌隐患", "滑坡隐患", "地质灾害风险", "隐患点分布", "风险管控", "风险评估"],
            "negative": [],
        },
    },
}


# ============================================
# Test Data Configuration
# ============================================

JINTIAN_VILLAGE_DATA = {
    "village_name": "金田村委会",
    "area_km2": 23.53,
    "population": 500,
    "administrative": "梅州市梅县区水车镇",
    "coordinate_system": "EPSG:4326",
}


# ============================================
# Annotation Template Configuration
# ============================================

ANNOTATION_FIELDS = [
    {"field": "dimension_key", "label": "维度编号", "type": "text"},
    {"field": "dimension_name", "label": "维度名称", "type": "text"},
    {"field": "layer", "label": "层级", "type": "number"},
    {"field": "wave", "label": "波次", "type": "number"},
    {"field": "positive_keyword_coverage", "label": "正向关键词检出率", "type": "percentage"},
    {"field": "negative_keyword_residual", "label": "残留负面关键词", "type": "text"},
    {"field": "human_judgment", "label": "人工判定", "type": "select", "options": ["达标", "部分达标", "未达标"]},
    {"field": "notes", "label": "备注", "type": "text"},
]


# ============================================
# Utility Functions
# ============================================

def ensure_output_dirs():
    """Ensure all output directories exist."""
    for dir_path in [BASELINE_DIR, SCENARIO1_DIR, SCENARIO2_DIR, ANALYSIS_DIR]:
        dir_path.mkdir(parents=True, exist_ok=True)


def get_scenario_config(scenario_name: str) -> Dict[str, Any]:
    """Get scenario configuration by name."""
    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}")
    return SCENARIOS[scenario_name]


def get_output_dir(scenario_name: str) -> Path:
    """Get output directory for a scenario."""
    if scenario_name == "baseline":
        return BASELINE_DIR
    elif scenario_name == "scenario1":
        return SCENARIO1_DIR
    elif scenario_name == "scenario2":
        return SCENARIO2_DIR
    elif scenario_name == "analysis":
        return ANALYSIS_DIR
    else:
        raise ValueError(f"Unknown scenario: {scenario_name}")