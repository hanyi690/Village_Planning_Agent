"""GIS Agent builders — PARSE Agent entry point.

Architecture (2026-07-17):
  - Primary: build_layout_pipeline() → unified StateGraph with Pydantic state
  - PARSE: build_parse_agent_graph() → deterministic rule-based parser
"""

from __future__ import annotations


def create_parse_agent_graph():
    """PARSE Agent - unified planning text parser.

    Returns the parse function for direct invocation (not a LangGraph).
    Kept for backward compatibility with external callers.
    """
    from app.agent.select.parse_agent import parse_async
    return parse_async


__all__ = [
    "create_parse_agent_graph",
]
