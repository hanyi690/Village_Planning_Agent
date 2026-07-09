"""Tool metadata registry (read-only) for SSE events and UI rendering."""

from typing import Any, Dict, Optional
from dataclasses import dataclass


@dataclass
class ToolMetadata:
    name: str
    description: str
    display_name: Optional[str] = None
    estimated_time: Optional[float] = None
    display_hints: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.display_name is None:
            self.display_name = self.name
        if self.display_hints is None:
            self.display_hints = {"primary_view": "text", "priority_fields": []}


_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "population_prediction": {
        "display_name": "人口预测",
        "description": "基于人口模型预测未来人口变化趋势，支持村庄规划标准模型。",
        "estimated_time": 3.0,
        "display_hints": {"primary_view": "chart", "priority_fields": ["forecast_population", "growth_rate"]},
    },
    "knowledge_search": {
        "display_name": "知识检索",
        "description": "从知识库检索专业数据和法规条文。",
        "estimated_time": 2.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["content", "source"]},
    },
    "web_search": {
        "display_name": "网络搜索",
        "description": "从互联网搜索实时信息。",
        "estimated_time": 4.0,
        "display_hints": {"primary_view": "text", "priority_fields": ["results"]},
    },
}


class ToolRegistry:
    """Read-only tool metadata for SSE / UI display."""

    _metadata: Dict[str, ToolMetadata] = {}

    @classmethod
    def get_tool_metadata(cls, name: str) -> Optional[ToolMetadata]:
        return cls._metadata.get(name)

    @classmethod
    def get_all_metadata(cls) -> Dict[str, ToolMetadata]:
        return cls._metadata.copy()

    @classmethod
    def get_tool_info(cls, tool_name: str) -> Dict[str, Any]:
        meta = cls._metadata.get(tool_name)
        if meta is None:
            return {"display_name": tool_name, "description": "", "estimated_time": None}
        return {
            "display_name": meta.display_name,
            "description": meta.description,
            "estimated_time": meta.estimated_time,
        }

    @classmethod
    def get_display_name(cls, tool_name: str) -> str:
        return cls.get_tool_info(tool_name)["display_name"]

    @classmethod
    def get_description(cls, tool_name: str) -> str:
        return cls.get_tool_info(tool_name)["description"]

    @classmethod
    def get_estimated_time(cls, tool_name: str) -> Optional[float]:
        return cls.get_tool_info(tool_name)["estimated_time"]


# Populate metadata from definitions
for _n, _d in _TOOL_DEFINITIONS.items():
    ToolRegistry._metadata[_n] = ToolMetadata(
        name=_n,
        description=_d.get("description", ""),
        display_name=_d.get("display_name", _n),
        estimated_time=_d.get("estimated_time"),
        display_hints=_d.get("display_hints"),
    )


__all__ = ["ToolRegistry", "ToolMetadata"]
