"""Lazy GIS tool registry for the planning agent."""

from __future__ import annotations

from typing import Any, List


def get_gis_pipeline_tools() -> List[Any]:
    """Load the LangChain tool set only when the agent requests it.

    Note: ``parse_planning_text`` was removed when PARSE became an
    independent top-level stage (Wave A.1); planning-text parsing no longer
    runs through the GIS tool bundle.
    """
    from .conflict import detect_conflicts
    from .export import export_gdb
    from .extract import extract_structured_text
    from .kg import build_knowledge_graph, query_knowledge_graph
    from .lookup import lookup_land_use_code
    from .render import render_map
    from .validate import validate_layout

    return [
        extract_structured_text,
        lookup_land_use_code,
        build_knowledge_graph,
        query_knowledge_graph,
        detect_conflicts,
        validate_layout,
        export_gdb,
        render_map,
    ]


def __getattr__(name: str) -> Any:
    if name == "GIS_PIPELINE_TOOLS":
        return get_gis_pipeline_tools()
    raise AttributeError(name)


__all__ = ["GIS_PIPELINE_TOOLS", "get_gis_pipeline_tools"]
