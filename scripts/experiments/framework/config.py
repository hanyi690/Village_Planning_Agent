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


# Default cascade scenarios - Updated based on actual discrepancies between ideal and generated text
CASCADE_SCENARIOS: Dict[str, CascadeScenario] = {
    # 场景一：修正村庄分类（Layer 2 → Layer 3 跨层传播）
    # 理想文本：集聚提升类，生成文本：特色保护类
    "scenario1": CascadeScenario(
        name="驳回规划定位-修正村庄分类",
        target_dimension="planning_positioning",
        target_layer=2,
        feedback="""金田村根据《平远县国土空间总体规划（2021—2035年）》被划定为"集聚提升类村庄"，而非"特色保护类村庄"。请修正规划定位，调整为：
1. 村庄分类：集聚提升类
2. 发展定位：特色南药综合开发示范村
3. 产业方向：以南药种植、加工、销售为主导，结合林下经济和生态旅游
4. 发展目标：至2035年，村集体年收入突破50万元，南药产业产值达到300万元""",
        keywords={
            "positive": ["集聚提升类", "南药产业", "特色南药综合开发示范村", "南药种植", "南药加工", "产业集聚"],
            "negative": ["特色保护类", "文旅主导", "生态保育村"],
        },
    ),

    # 场景二：修正规划指标（Layer 2 → Layer 3 跨层传播）
    # 理想文本指标与生成文本指标存在严重差异
    "scenario2": CascadeScenario(
        name="驳回发展目标-修正规划指标",
        target_dimension="development_goals",
        target_layer=2,
        feedback="""规划指标存在严重错误，请根据上位规划要求修正：
1. 人口规模：基期年1406人，目标年1681人（而非1454人）
2. 耕地保有量：85.42公顷增至127.18公顷（需增加41.76公顷）
3. 基本农田保护面积：81.43公顷（非85.2公顷）
4. 生态保护红线面积：367.68公顷（非325.92公顷）
5. 村庄建设用地规模：15.81公顷增至17.66公顷（非30.17公顷）
6. 人均建设用地：112.35㎡降至105.05㎡（非555㎡）""",
        keywords={
            "positive": ["耕地保有量127.18", "基本农田81.43", "生态红线367.68", "建设用地17.66", "人口1681"],
            "negative": ["建设用地30", "人均建设用地555", "耕地保有量85.2"],
        },
    ),

    # 场景三：修正产业方向（Layer 3 内部传播）
    # 理想文本：南药产业，生成文本：林下经济+文旅
    "scenario3": CascadeScenario(
        name="驳回产业规划-修正产业方向",
        target_dimension="industry",
        target_layer=3,
        feedback="""产业规划方向错误，金田村应重点发展南药产业而非林下经济+文旅。请修正：
1. 主导产业：南药种植、南药加工、南药销售
2. 产业项目：南药加工合作社（田坑、塘笃）、南药产业园（园寨）、药苗培育基地（田坑）、药膳加工坊（黄竹）
3. 经营性建设用地：规划安排1.37公顷
4. 产业目标：打造岭南特色南药产业示范基地""",
        keywords={
            "positive": ["南药产业", "南药加工合作社", "南药产业园", "药苗培育基地", "药膳加工坊", "经营性建设用地1.37"],
            "negative": ["林下经济主导", "文旅主导", "杉木家具"],
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
