"""GIS tools for the ReAct Agent.

Exports all GIS @tool definitions as a unified GIS_TOOLS list.
"""

from .data_tools import (
    fetch_gis_data,
    calculate_gis_coverage,
    analyze_accessibility,
    search_poi,
)
from .layout_tools import (
    parse_planning_text,
    build_knowledge_graph,
    query_knowledge_graph,
    detect_conflicts,
    allocate_zones,
    generate_layout,
    validate_layout,
    measure_divergence,
)

GIS_TOOLS = [
    # Data acquisition
    fetch_gis_data,
    calculate_gis_coverage,
    analyze_accessibility,
    search_poi,
    # Layout planning
    parse_planning_text,
    build_knowledge_graph,
    query_knowledge_graph,
    detect_conflicts,
    allocate_zones,
    generate_layout,
    validate_layout,
    measure_divergence,
]

__all__ = ["GIS_TOOLS"]
