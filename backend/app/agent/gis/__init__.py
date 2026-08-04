"""GIS planning application package with lazy public exports."""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "create_parse_agent_graph":
        from . import agent

        return getattr(agent, name)
    if name == "build_layout_pipeline":
        from .layout_pipeline import build_layout_pipeline

        return build_layout_pipeline
    if name == "ParseAgentState":
        from .parse.state import ParseAgentState

        return ParseAgentState
    raise AttributeError(name)


__all__ = [
    "create_parse_agent_graph",
    "build_layout_pipeline",
    "ParseAgentState",
]
