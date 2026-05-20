"""Unified experiment configuration.

Merges old config.py + dependencies.py into dataclass-based config.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path setup — inject project roots so backend imports work
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # Village_Planning_Agent/
_BACKEND_ROOT = _PROJECT_ROOT / "backend"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Village data
# ---------------------------------------------------------------------------
_STATUS_REPORT_PATH = _PROJECT_ROOT / "docs" / "MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md"

JINTIAN_VILLAGE_DATA: str = ""
if _STATUS_REPORT_PATH.exists():
    JINTIAN_VILLAGE_DATA = _STATUS_REPORT_PATH.read_text(encoding="utf-8")

JINTIAN_TASK_DESCRIPTION = (
    "编制梅州市金田村村庄规划，"
    "涵盖国土空间布局、产业发展、人居环境、设施配套、历史文化保护等方面。"
)

JINTIAN_CONSTRAINTS = (
    "1. 耕地保有量不低于85.2公顷，永久基本农田78.83公顷；\n"
    "2. 生态保护红线362.02公顷；\n"
    "3. 村庄建设用地规模30.5公顷；\n"
    "4. 林地保有量不低于423.6公顷；\n"
    "5. 符合梅州市国土空间总体规划要求。"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class VillageConfig:
    """Village-specific configuration."""

    village_name: str
    status_report: str
    task_description: str
    constraints: str

    @classmethod
    def jintian(cls) -> "VillageConfig":
        return cls(
            village_name="金田村",
            status_report=JINTIAN_VILLAGE_DATA,
            task_description=JINTIAN_TASK_DESCRIPTION,
            constraints=JINTIAN_CONSTRAINTS,
        )


@dataclass
class CascadeScenario:
    """A single cascade revision scenario."""

    name: str
    target_dimension: str
    target_layer: int
    feedback: str
    keywords: Dict[str, List[str]]
    min_consistency_threshold: float = 0.6


# Default cascade scenarios (from old config.py SCENARIOS)
CASCADE_SCENARIOS: Dict[str, CascadeScenario] = {
    "scenario1": CascadeScenario(
        name="驳回规划定位（Layer 2）",
        target_dimension="planning_positioning",
        target_layer=2,
        feedback="""金田村常住人口仅500人，不具备承接大规模旅游的基础设施条件。
千年古檀树、古茶亭遗址等核心历史资源应划定为绝对保护对象，剥离重度商业开发权。
规划定位应转向生态保育优先、客家文化微改造的渐进式发展路径。""",
        keywords={
            "positive": ["生态保育", "渐进式发展", "客家文化微改造", "绝对保护", "保护优先", "微改造"],
            "negative": ["大规模旅游", "商业开发", "景区化", "旅游开发"],
        },
    ),
    "scenario2": CascadeScenario(
        name="驳回自然环境分析（Layer 1）",
        target_dimension="natural_environment",
        target_layer=1,
        feedback="""现状报告中明确记载金田村存在5处崩塌隐患点和35处滑坡隐患点，
但当前分析未对隐患点的空间分布与影响范围进行充分评估，需强化地质灾害风险的分析深度。""",
        keywords={
            "positive": ["崩塌隐患", "滑坡隐患", "地质灾害风险", "隐患点分布", "风险管控", "风险评估"],
            "negative": [],
        },
    ),
}

# Default RAG group configs (L2 RAG is OFF in actual application)
RAG_GROUPS: Dict[str, Dict[int, bool]] = {
    "g1": {1: False, 2: False, 3: False},  # Pure LLM baseline
    "g2": {1: False, 2: False, 3: True},   # L3 RAG only
    "g3": {1: True, 2: False, 3: True},    # L1+L3 RAG (actual app config, L2 OFF)
}


@dataclass
class ExperimentConfig:
    """Top-level experiment configuration."""

    experiment_id: str
    village: VillageConfig
    output_dir: Path
    cache_dir: Path
    use_cache: bool = True
    max_concurrent: int = 3

    # Scenario / group definitions
    cascade_scenarios: Dict[str, CascadeScenario] = field(default_factory=lambda: dict(CASCADE_SCENARIOS))
    rag_groups: Dict[str, Dict[int, bool]] = field(default_factory=lambda: dict(RAG_GROUPS))

    @classmethod
    def default(cls, experiment_id: str = "default") -> "ExperimentConfig":
        """Create a default config for jintian village."""
        base = _PROJECT_ROOT / "output" / "experiments"
        return cls(
            experiment_id=experiment_id,
            village=VillageConfig.jintian(),
            output_dir=base / experiment_id,
            cache_dir=base / "cache",
        )
