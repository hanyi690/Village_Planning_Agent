"""Table dataset types — 第四数据形态 (非空间结构化行列数据).

覆盖规划输入侧调查表与输出侧汇交表 (一图一表一规则的'表'与'规则').
Shared fields:
  - rows: List[Dict[str, Any]]  行数据
  - columns: List[ColumnSpec]   列定义 (name + dtype + 语义)
  - table_type: str             表格类型标识
  - layer_type: str             所属图层 (表格也是一种 layer)
  - _meta: Dict[str, Any]       原始元数据
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ColumnSpec:
    """Column specification for table datasets."""
    name: str
    dtype: str = "string"  # "string" | "float" | "int" | "boolean"
    description: str = ""


@dataclass
class TableDataset:
    """表格数据集基类 — 非空间结构化行列数据."""

    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[ColumnSpec] = field(default_factory=list)
    table_type: str = ""
    layer_type: str = ""
    _meta: Dict[str, Any] = field(default_factory=dict, repr=False)


# ── 输入型表格 (现状调查) ──


@dataclass
class PopulationTable(TableDataset):
    """人口结构表 — 输入型.
    字段: 年龄结构/户数/劳动力/迁出率
    """
    table_type: str = "population"


@dataclass
class IndustryTable(TableDataset):
    """产业经济表 — 输入型.
    字段: 产业类型/产值/就业/用地需求
    """
    table_type: str = "industry"


@dataclass
class FacilityInventory(TableDataset):
    """设施清单表 — 输入型.
    字段: 设施名/类型/规模/服务人口
    """
    table_type: str = "facility_inventory"


# ── 输出型表格 (汇交成果: 一图一表一规则) ──


@dataclass
class ConstructionProjectTable(TableDataset):
    """近期建设项目表 — 输出型 (一表).
    字段: 项目名/位置/规模/投资/时序
    """
    table_type: str = "construction_projects"


@dataclass
class ControlRuleTable(TableDataset):
    """管制规则表 — 输出型 (一规则).
    字段: 分区/管制要求/引用条款
    """
    table_type: str = "control_rules"


@dataclass
class PlanningIndicatorTable(TableDataset):
    """规划指标表 — 输出型 (附表1).
    字段: 指标名/现状值/目标值/属性
    """
    table_type: str = "planning_indicators"


@dataclass
class LandUseStructureTable(TableDataset):
    """用地结构表 — 输出型 (附表).
    字段: 地类/现状面积/规划面积/增减
    """
    table_type: str = "land_use_structure"


__all__ = [
    "ColumnSpec",
    "TableDataset",
    "PopulationTable",
    "IndustryTable",
    "FacilityInventory",
    "ConstructionProjectTable",
    "ControlRuleTable",
    "PlanningIndicatorTable",
    "LandUseStructureTable",
]