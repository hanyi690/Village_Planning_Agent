"""GIS planning application package with lazy public exports."""

from __future__ import annotations

from typing import Any


_GRAPH_EXPORTS = {
    "create_gis_agent_graph",
    "create_parse_agent_graph",
    "create_layout_agent_graph",
}
_STATE_EXPORTS = {
    "GISAgentState",
    "LayoutAgentState",
    "LayoutPipelineState",
}


def __getattr__(name: str) -> Any:
    if name in _GRAPH_EXPORTS:
        from . import agent

        return getattr(agent, name)
    if name == "build_layout_pipeline":
        from .layout_pipeline import build_layout_pipeline

        return build_layout_pipeline
    if name in _STATE_EXPORTS:
        from . import state

        return getattr(state, name)
    if name == "ParseAgentState":
        from .parse.state import ParseAgentState

        return ParseAgentState
    raise AttributeError(name)


__all__ = [
    "create_gis_agent_graph",
    "create_parse_agent_graph",
    "create_layout_agent_graph",
    "build_layout_pipeline",
    "GISAgentState",
    "ParseAgentState",
    "LayoutAgentState",
    "LayoutPipelineState",
]
