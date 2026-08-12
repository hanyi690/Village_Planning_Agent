"""Tool registry — unified metadata + executable tool lookup.

Executable side: ``register()`` stores LangChain BaseTool objects keyed by
name; ``for_agent()`` returns the bindable tool list for a given agent scope.
Display side: ToolMetadata for SSE events / UI rendering (existing behavior).
"""

from typing import Any, Dict, List, Optional
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


_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {}


class ToolRegistry:
    """Unified tool registry: metadata for SSE/UI + executable tool lookup.

    ``register()`` records display metadata AND the executable BaseTool object.
    ``for_agent(agent_id)`` returns the bindable tool list for an agent scope.
    """

    _metadata: Dict[str, ToolMetadata] = {}
    _tools: Dict[str, Any] = {}

    @classmethod
    def register(
        cls,
        name: str,
        tool: Any = None,
        description: str = "",
        display_name: Optional[str] = None,
        estimated_time: Optional[float] = None,
        display_hints: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a tool's executable object + display metadata."""
        if name not in cls._metadata:
            cls._metadata[name] = ToolMetadata(
                name=name,
                description=description,
                display_name=display_name,
                estimated_time=estimated_time,
                display_hints=display_hints,
            )
        if tool is not None:
            cls._tools[name] = tool

    @classmethod
    def get_tool(cls, name: str) -> Optional[Any]:
        """Return the registered executable tool, or None."""
        return cls._tools.get(name)

    @classmethod
    def registered_tools(cls) -> Dict[str, Any]:
        """Return a copy of the registered executable tools."""
        return dict(cls._tools)

    @classmethod
    def for_agent(cls, agent_id: str) -> List[Any]:
        """Return the bindable tool list for an agent scope.

        Known scopes:
          - "explore": session access tools (bundle_overview / spatial_context /
            spatial_features / layer_reports / knowledge_graph / rag_search)
        Other agents can adopt any of these lists by declaring the same scope.
        """
        if agent_id == "explore":
            from app.infrastructure.llm.tools.access import ACCESS_TOOLS
            return list(ACCESS_TOOLS)
        return []

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
