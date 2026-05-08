"""
Tool Protocol - Unified interface for all tools

Provides:
- IMPL_STATUS: Implementation status annotations for each tool
- ToolResult: Standardized return value dataclass
- Tool Protocol: Interface contract for tool implementations
- create_stub_result: Helper for STUB/MOCK tools

Reference: Tool System Refactor Plan (2026-05-08)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Literal, runtime_checkable
from enum import Enum


class ImplStatus(str, Enum):
    """Tool implementation status"""
    IMPLEMENTED = "IMPLEMENTED"   # Fully functional
    STUB = "STUB"                 # Partially implemented, may have gaps
    MOCK = "MOCK"                 # Returns simulated/hardcoded data
    DISABLED = "DISABLED"         # Not available for use


# Tool Implementation Status Registry
IMPL_STATUS: Dict[str, ImplStatus] = {
    # Layer 0: Basic data
    "boundary_fallback": ImplStatus.MOCK,
    "gis_data_fetch": ImplStatus.STUB,
    "gis_coverage_calculator": ImplStatus.STUB,

    # Layer 1: Spatial analysis
    "spatial_overlay": ImplStatus.STUB,
    "spatial_query": ImplStatus.STUB,
    "accessibility_analysis": ImplStatus.STUB,
    "isochrone_analysis": ImplStatus.STUB,
    "poi_search": ImplStatus.STUB,
    "landuse_change_analysis": ImplStatus.STUB,
    "hazard_buffer_generator": ImplStatus.MOCK,

    # Layer 2: Planning decisions
    "facility_validator": ImplStatus.MOCK,
    "constraint_validator": ImplStatus.MOCK,
    "ecological_sensitivity": ImplStatus.MOCK,
    "spatial_layout_generator": ImplStatus.STUB,
    "planning_vectorizer": ImplStatus.STUB,

    # Output layer
    "map_renderer": ImplStatus.STUB,

    # Core tools (fully implemented)
    "knowledge_search": ImplStatus.IMPLEMENTED,
    "web_search": ImplStatus.IMPLEMENTED,
    "population_model_v1": ImplStatus.IMPLEMENTED,
    "document_overview": ImplStatus.IMPLEMENTED,
    "chapter_content": ImplStatus.IMPLEMENTED,
}


@dataclass
class ToolResult:
    """
    Standardized tool execution result

    All tools return this format, no exceptions thrown.

    Attributes:
        status: Execution status - "success", "partial", or "error"
        data: The actual result data (GeoJSON, analysis dict, string, etc.)
        error: Error message if status != "success"
        metadata: Additional context including impl_status for STUB/MOCK tools
    """
    status: Literal["success", "partial", "error"]
    data: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if execution was successful"""
        return self.status == "success"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


def create_stub_result(
    tool_name: str,
    message: str,
    data: Any = None,
    status: Literal["success", "partial", "error"] = "partial"
) -> ToolResult:
    """
    Create a result for STUB/MOCK tools with status annotation

    Args:
        tool_name: Tool identifier
        message: Explanation message
        data: Optional mock data
        status: Result status (default "partial" for stubs)

    Returns:
        ToolResult with impl_status in metadata
    """
    impl_status = IMPL_STATUS.get(tool_name, ImplStatus.STUB)

    return ToolResult(
        status=status,
        data=data,
        error=None if status != "error" else message,
        metadata={
            "impl_status": impl_status.value,
            "tool_name": tool_name,
            "message": message,
            "is_stub": impl_status in (ImplStatus.STUB, ImplStatus.MOCK),
        }
    )


@runtime_checkable
class Tool(Protocol):
    """
    Protocol for tool implementations

    Any callable that accepts a context dict and returns a string
    can be registered as a tool.
    """
    def __call__(self, context: Dict[str, Any]) -> str:
        """Execute the tool with given context"""
        ...


def is_stub_tool(tool_name: str) -> bool:
    """Check if a tool is STUB or MOCK"""
    status = IMPL_STATUS.get(tool_name, ImplStatus.STUB)
    return status in (ImplStatus.STUB, ImplStatus.MOCK)


def get_impl_status(tool_name: str) -> str:
    """Get implementation status string for a tool"""
    return IMPL_STATUS.get(tool_name, ImplStatus.STUB).value


__all__ = [
    "ImplStatus",
    "IMPL_STATUS",
    "ToolResult",
    "Tool",
    "create_stub_result",
    "is_stub_tool",
    "get_impl_status",
]