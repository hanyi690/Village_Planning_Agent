"""
Analytics tools module exports.
"""

from .knowledge_search import (
    knowledge_search_tool,
    document_overview_registry_wrapper,
    chapter_content_registry_wrapper,
    PLANNING_TOOLS,
)
from .population import calculate_population

# Web search placeholder (TBD)
def web_search_tool(context: dict) -> str:
    """Web search placeholder - returns guidance message."""
    return "Web search functionality is not yet implemented. Please use knowledge_search instead."


__all__ = [
    "knowledge_search_tool",
    "web_search_tool",
    "calculate_population",
    "document_overview_registry_wrapper",
    "chapter_content_registry_wrapper",
    "PLANNING_TOOLS",
]