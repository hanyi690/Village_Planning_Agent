"""Ground Truth Configuration for RAG Quality Evaluation.

Defines the mapping between evaluation dimensions and authoritative document sections.
This configuration ensures all RAG groups are evaluated against the same baseline.

IMPORTANT: 现状报告是"输入数据/事实基座"，是所有维度忠实度评估的核心依据。
规划文本是"输出成果"，仅作为质量上限参照。

依赖传递原则（参考 phases.yaml）：
- L1 维度：直接使用现状报告对应章节
- L2 维度：依赖 L1 维度的现状数据（layer_depends_on）
- L3 维度：依赖 L1 维度的现状数据 + L2 维度的分析结果（layer_depends_on + phase_depends_on）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path

# Project root directory (scripts/experiments/rag -> experiments -> scripts -> project)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Document paths (relative to project root)
DOCUMENTS = {
    "planning_text": PROJECT_ROOT / "docs" / "MinerU_markdown_平远县泗水镇金田村村庄规划（2022-2035年）文本_2056639426835755008.md",
    "status_report": PROJECT_ROOT / "docs" / "MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md",
    "planning_idea": PROJECT_ROOT / "docs" / "MinerU_markdown_泗水镇金田村规划思路_2056637620474851328.md",
    "planning_detail": PROJECT_ROOT / "docs" / "MinerU_markdown_泗水镇金田村规划细化_2056637557694480384.md",
}


@dataclass
class SectionMapping:
    """Mapping configuration for a document section."""
    doc_key: str  # Key in DOCUMENTS
    section_start: str  # Section title or marker to find start
    section_end: Optional[str] = None  # Section title or marker to find end


@dataclass
class DimensionMapping:
    """Mapping configuration for a dimension.

    知识依据(knowledge_sections)来自现状报告，是忠实度评估的基准。
    质量参照(quality_reference)来自规划文档，用于质量上限对照。
    depends_on: 该维度依赖的 L1 现状维度（用于知识传递）
    """
    dimension_key: str
    dimension_name: str
    layer: int
    # 知识依据：来自现状报告的现状数据
    knowledge_sections: List[SectionMapping] = field(default_factory=list)
    # 质量参照：来自规划文档的规划方案
    quality_reference: List[SectionMapping] = field(default_factory=list)
    # 依赖的 L1 现状维度（用于知识传递，参考 phases.yaml）
    layer_depends_on: List[str] = field(default_factory=list)


# ============================================
# L1 维度映射：直接使用现状报告对应章节
# ============================================
L1_MAPPINGS: Dict[str, DimensionMapping] = {
    "location": DimensionMapping(
        dimension_key="location",
        dimension_name="区位与对外交通分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "一、区位分析", "二、社会经济分析"),
        ],
        layer_depends_on=[],
    ),
    "socio_economic": DimensionMapping(
        dimension_key="socio_economic",
        dimension_name="社会经济分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "二、社会经济分析", "三、自然环境分析"),
        ],
        layer_depends_on=[],
    ),
    "villager_wishes": DimensionMapping(
        dimension_key="villager_wishes",
        dimension_name="村民意愿与诉求分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "【村庄发展诉求】", "【村庄现状台账】"),
        ],
        layer_depends_on=[],
    ),
    "superior_planning": DimensionMapping(
        dimension_key="superior_planning",
        dimension_name="上位规划与政策导向分析",
        layer=1,
        # 现状报告无此章节，使用规划文本的规划依据
        knowledge_sections=[
            SectionMapping("planning_text", "规划依据", "规划范围"),
        ],
        layer_depends_on=[],
    ),
    "natural_environment": DimensionMapping(
        dimension_key="natural_environment",
        dimension_name="自然环境分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "三、自然环境分析", "四、土地利用分析"),
        ],
        layer_depends_on=[],
    ),
    "land_use": DimensionMapping(
        dimension_key="land_use",
        dimension_name="土地利用分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "四、土地利用分析", "五、道路交通分析"),
        ],
        layer_depends_on=[],
    ),
    "traffic": DimensionMapping(
        dimension_key="traffic",
        dimension_name="道路交通分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "五、道路交通分析", "六、公共服务设施分析"),
        ],
        layer_depends_on=[],
    ),
    "public_services": DimensionMapping(
        dimension_key="public_services",
        dimension_name="公共服务设施分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "六、公共服务设施分析", "七、基础设施分析"),
        ],
        layer_depends_on=[],
    ),
    "infrastructure": DimensionMapping(
        dimension_key="infrastructure",
        dimension_name="基础设施分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "七、基础设施分析", "八、绿地与活动场地分析"),
        ],
        layer_depends_on=[],
    ),
    "ecological_green": DimensionMapping(
        dimension_key="ecological_green",
        dimension_name="生态绿地分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "八、绿地与活动场地分析", "九、建筑现状分析"),
        ],
        layer_depends_on=[],
    ),
    "architecture": DimensionMapping(
        dimension_key="architecture",
        dimension_name="建筑分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "九、建筑现状分析", "十、历史文化资源分析"),
        ],
        layer_depends_on=[],
    ),
    "historical_culture": DimensionMapping(
        dimension_key="historical_culture",
        dimension_name="历史文化与乡愁保护分析",
        layer=1,
        knowledge_sections=[
            SectionMapping("status_report", "十、历史文化资源分析", "【村庄发展诉求】"),
        ],
        layer_depends_on=[],
    ),
}


# ============================================
# L3 维度映射：按照 phases.yaml 的依赖传递路径
# ============================================
L3_MAPPINGS: Dict[str, DimensionMapping] = {
    "industry": DimensionMapping(
        dimension_key="industry",
        dimension_name="产业规划",
        layer=3,
        # phases.yaml: layer_depends_on: socio_economic, land_use
        knowledge_sections=[
            SectionMapping("status_report", "二、社会经济分析", "三、自然环境分析"),
            SectionMapping("status_report", "四、土地利用分析", "五、道路交通分析"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "【产业规划】", "【村庄总体规划】"),
        ],
        layer_depends_on=["socio_economic", "land_use"],
    ),
    "spatial_structure": DimensionMapping(
        dimension_key="spatial_structure",
        dimension_name="空间结构规划",
        layer=3,
        # phases.yaml: layer_depends_on: natural_environment, land_use
        knowledge_sections=[
            SectionMapping("status_report", "三、自然环境分析", "四、土地利用分析"),
            SectionMapping("status_report", "四、土地利用分析", "五、道路交通分析"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "一、空间格局", "二、土地利用规划"),
        ],
        layer_depends_on=["natural_environment", "land_use"],
    ),
    "land_use_planning": DimensionMapping(
        dimension_key="land_use_planning",
        dimension_name="土地利用规划",
        layer=3,
        # phases.yaml: layer_depends_on: land_use, natural_environment
        knowledge_sections=[
            SectionMapping("status_report", "四、土地利用分析", "五、道路交通分析"),
            SectionMapping("status_report", "三、自然环境分析", "四、土地利用分析"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "二、土地利用规划", "三、村庄用地控制"),
        ],
        layer_depends_on=["land_use", "natural_environment"],
    ),
    "settlement_planning": DimensionMapping(
        dimension_key="settlement_planning",
        dimension_name="居民点规划",
        layer=3,
        # phases.yaml: layer_depends_on: socio_economic
        knowledge_sections=[
            SectionMapping("status_report", "二、社会经济分析", "三、自然环境分析"),
            SectionMapping("status_report", "九、建筑现状分析", "十、历史文化资源分析"),
        ],
        quality_reference=[
            SectionMapping("planning_text", "农村住房建设", "基础设施和公共服务设施建设"),
        ],
        layer_depends_on=["socio_economic"],
    ),
    "traffic_planning": DimensionMapping(
        dimension_key="traffic_planning",
        dimension_name="道路交通规划",
        layer=3,
        # phases.yaml: layer_depends_on: traffic
        knowledge_sections=[
            SectionMapping("status_report", "五、道路交通分析", "六、公共服务设施分析"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "四、道路交通规划", "五、公共服务设施规划"),
        ],
        layer_depends_on=["traffic"],
    ),
    "public_service": DimensionMapping(
        dimension_key="public_service",
        dimension_name="公共服务设施规划",
        layer=3,
        # phases.yaml: layer_depends_on: public_services, socio_economic
        knowledge_sections=[
            SectionMapping("status_report", "六、公共服务设施分析", "七、基础设施分析"),
            SectionMapping("status_report", "二、社会经济分析", "三、自然环境分析"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "五、公共服务设施规划", "六、基础设施规划"),
        ],
        layer_depends_on=["public_services", "socio_economic"],
    ),
    "infrastructure_planning": DimensionMapping(
        dimension_key="infrastructure_planning",
        dimension_name="基础设施规划",
        layer=3,
        # phases.yaml: layer_depends_on: infrastructure
        knowledge_sections=[
            SectionMapping("status_report", "七、基础设施分析", "八、绿地与活动场地分析"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "六、基础设施规划", "七、生态绿地规划"),
        ],
        layer_depends_on=["infrastructure"],
    ),
    "ecological": DimensionMapping(
        dimension_key="ecological",
        dimension_name="生态绿地规划",
        layer=3,
        # phases.yaml: layer_depends_on: ecological_green
        knowledge_sections=[
            SectionMapping("status_report", "八、绿地与活动场地分析", "九、建筑现状分析"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "七、生态绿地规划", "八、防震减灾规划"),
        ],
        layer_depends_on=["ecological_green"],
    ),
    "disaster_prevention": DimensionMapping(
        dimension_key="disaster_prevention",
        dimension_name="防震减灾规划",
        layer=3,
        # phases.yaml: layer_depends_on: infrastructure, architecture
        knowledge_sections=[
            SectionMapping("status_report", "七、基础设施分析", "八、绿地与活动场地分析"),
            SectionMapping("status_report", "九、建筑现状分析", "十、历史文化资源分析"),
            SectionMapping("status_report", "三、自然环境分析", "四、土地利用分析"),  # 地质灾害
        ],
        quality_reference=[
            SectionMapping("planning_detail", "八、防震减灾规划", "九、近期建设项目库"),
        ],
        layer_depends_on=["infrastructure", "architecture"],
    ),
    "heritage": DimensionMapping(
        dimension_key="heritage",
        dimension_name="历史文保规划",
        layer=3,
        # phases.yaml: layer_depends_on: historical_culture
        knowledge_sections=[
            SectionMapping("status_report", "十、历史文化资源分析", "【村庄发展诉求】"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "【历史文化保护规划】", "【村庄风貌指引】"),
        ],
        layer_depends_on=["historical_culture"],
    ),
    "landscape": DimensionMapping(
        dimension_key="landscape",
        dimension_name="村庄风貌指引",
        layer=3,
        # phases.yaml: layer_depends_on: architecture, historical_culture
        knowledge_sections=[
            SectionMapping("status_report", "九、建筑现状分析", "十、历史文化资源分析"),
            SectionMapping("status_report", "十、历史文化资源分析", "【村庄发展诉求】"),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "【村庄风貌指引】", None),
        ],
        layer_depends_on=["architecture", "historical_culture"],
    ),
    "project_bank": DimensionMapping(
        dimension_key="project_bank",
        dimension_name="建设项目库",
        layer=3,
        # phases.yaml: depends_on 多个 L3 维度，layer_depends_on 为空
        # 知识依据：村庄需求台账
        knowledge_sections=[
            SectionMapping("status_report", "【村庄需求台账】", None),
        ],
        quality_reference=[
            SectionMapping("planning_detail", "九、近期建设项目库", None),
        ],
        layer_depends_on=[],
    ),
}


# 合并所有维度映射
DIMENSION_MAPPINGS: Dict[str, DimensionMapping] = {
    **L1_MAPPINGS,
    **L3_MAPPINGS,
}


def get_dimension_mapping(dimension_key: str) -> Optional[DimensionMapping]:
    """Get mapping configuration for a dimension."""
    return DIMENSION_MAPPINGS.get(dimension_key)


def get_layer_dimensions(layer: int) -> List[str]:
    """Get all dimension keys for a layer."""
    return [k for k, v in DIMENSION_MAPPINGS.items() if v.layer == layer]


def get_all_dimension_keys() -> List[str]:
    """Get all dimension keys."""
    return list(DIMENSION_MAPPINGS.keys())


def get_l1_knowledge_for_l3(l3_key: str) -> List[SectionMapping]:
    """Get L1 knowledge sections that a L3 dimension depends on.

    Args:
        l3_key: L3 dimension key

    Returns:
        List of SectionMapping from L1 dimensions
    """
    l3_mapping = DIMENSION_MAPPINGS.get(l3_key)
    if not l3_mapping or l3_mapping.layer != 3:
        return []

    # Collect knowledge sections from dependent L1 dimensions
    sections = []
    for l1_key in l3_mapping.layer_depends_on:
        l1_mapping = L1_MAPPINGS.get(l1_key)
        if l1_mapping:
            sections.extend(l1_mapping.knowledge_sections)

    return sections