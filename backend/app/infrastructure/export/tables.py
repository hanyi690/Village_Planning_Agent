"""Table export functions — 一图一表一规则 表格汇交导出.

规划成果中"一图一表一规则"的"表"与"规则"产出:
  - 近期建设项目表 (ConstructionProjectTable → Excel/CSV)
  - 管制规则表 (ControlRuleTable → Excel/CSV)
  - 规划指标表 (PlanningIndicatorTable → 附表1)
  - 用地结构表 (LandUseStructureTable → 附表)
"""

from __future__ import annotations

from typing import Any, Dict, List


def export_construction_projects(projects: list) -> List[Dict[str, Any]]:
    """Export 近期建设项目表."""
    return []


def export_control_rules(rules: list) -> List[Dict[str, Any]]:
    """Export 管制规则."""
    return []


def export_planning_indicators(indicators: list) -> List[Dict[str, Any]]:
    """Export 规划指标表 (附表1)."""
    return []


def export_land_use_structure(structure: list) -> List[Dict[str, Any]]:
    """Export 用地结构表."""
    return []


__all__ = [
    "export_construction_projects",
    "export_control_rules",
    "export_planning_indicators",
    "export_land_use_structure",
]