"""
LangChain Tool Adapter

Converts ToolRegistry tools to LangChain StructuredTool format,
enabling bind_tools capability for LLM function calling.

Reference: Tool System Refactor Plan (2026-05-08)
"""

from typing import Any, Callable, Dict, List, Optional, Type
from langchain_core.tools import StructuredTool

from .protocol import IMPL_STATUS, ImplStatus, is_stub_tool
from .registry import ToolRegistry, TOOL_PARAMETER_SCHEMAS, TOOL_METADATA_DEFINITIONS
from ..utils.logger import get_logger

logger = get_logger(__name__)


def tool_to_structured_tool(
    tool_name: str,
    tool_func: Optional[Callable] = None,
    include_stub_warning: bool = True
) -> Optional[StructuredTool]:
    """
    Convert a registered tool to LangChain StructuredTool.

    Args:
        tool_name: Tool identifier
        tool_func: Optional custom function (uses registry if None)
        include_stub_warning: Add STUB/MOCK warning to description

    Returns:
        StructuredTool instance or None if tool not found
    """
    # Get tool function from registry
    if tool_func is None:
        tool_func = ToolRegistry.get_tool(tool_name)

    if tool_func is None:
        logger.warning(f"[LangChainAdapter] Tool not found: {tool_name}")
        return None

    # Get metadata
    meta_def = TOOL_METADATA_DEFINITIONS.get(tool_name, {})
    param_schema = TOOL_PARAMETER_SCHEMAS.get(tool_name)

    # Build description with status warning
    description = meta_def.get("description", f"Execute {tool_name}")
    if include_stub_warning and is_stub_tool(tool_name):
        status = IMPL_STATUS.get(tool_name, ImplStatus.STUB).value
        description = f"[{status}] {description} - Warning: Implementation incomplete"

    # Create StructuredTool
    return StructuredTool(
        name=tool_name,
        description=description,
        func=tool_func,
        args_schema=None,  # Use JSON schema directly
    )


def get_structured_tools_for_llm(
    tool_names: Optional[List[str]] = None,
    include_stubs: bool = True,
    include_mock: bool = True
) -> List[StructuredTool]:
    """
    Get StructuredTool list for LLM bind_tools.

    Args:
        tool_names: Specific tools to include (None = all registered)
        include_stubs: Include STUB status tools
        include_mock: Include MOCK status tools

    Returns:
        List of StructuredTool instances
    """
    if tool_names is None:
        tool_names = list(ToolRegistry._tools.keys())

    tools = []
    for name in tool_names:
        status = IMPL_STATUS.get(name, ImplStatus.STUB)

        # Skip based on status filters
        if status == ImplStatus.STUB and not include_stubs:
            continue
        if status == ImplStatus.MOCK and not include_mock:
            continue
        if status == ImplStatus.DISABLED:
            continue

        tool = tool_to_structured_tool(name)
        if tool:
            tools.append(tool)

    logger.info(f"[LangChainAdapter] Created {len(tools)} StructuredTools")
    return tools


def get_tools_by_status(target_status: ImplStatus) -> List[str]:
    """
    Get list of tool names with specified implementation status.

    Args:
        target_status: The status to filter by

    Returns:
        List of tool names matching the status
    """
    return [
        name for name, status in IMPL_STATUS.items()
        if status == target_status
    ]


# Convenience functions using get_tools_by_status
def get_implemented_tools() -> List[str]:
    """Get list of fully implemented tool names."""
    return get_tools_by_status(ImplStatus.IMPLEMENTED)


def get_stub_tools() -> List[str]:
    """Get list of STUB status tool names."""
    return get_tools_by_status(ImplStatus.STUB)


def get_mock_tools() -> List[str]:
    """Get list of MOCK status tool names."""
    return get_tools_by_status(ImplStatus.MOCK)


__all__ = [
    "tool_to_structured_tool",
    "get_structured_tools_for_llm",
    "get_tools_by_status",
    "get_implemented_tools",
    "get_stub_tools",
    "get_mock_tools",
]