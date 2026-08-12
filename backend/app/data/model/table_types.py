from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class ColumnSpec(BaseModel):
    name: str
    dtype: str = "string"
    description: str = ""


class TableDataset(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    rows: List[Dict[str, Any]] = Field(default_factory=list)
    columns: List[ColumnSpec] = Field(default_factory=list)
    table_type: str = ""
    layer_type: str = ""


class PopulationTable(TableDataset):
    table_type: str = "population"


class IndustryTable(TableDataset):
    table_type: str = "industry"


class FacilityInventory(TableDataset):
    table_type: str = "facility_inventory"


class ConstructionProjectTable(TableDataset):
    table_type: str = "construction_projects"


class ControlRuleTable(TableDataset):
    table_type: str = "control_rules"


class PlanningIndicatorTable(TableDataset):
    table_type: str = "planning_indicators"


class LandUseStructureTable(TableDataset):
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