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
    build_knowledge_graph,
    query_knowledge_graph,
    detect_conflicts,
    allocate_zones,
    generate_layout,
    validate_layout,
)

GIS_TOOLS = [
    # Data acquisition
    fetch_gis_data,
    calculate_gis_coverage,
    analyze_accessibility,
    search_poi,
    # Layout planning
    build_knowledge_graph,
    query_knowledge_graph,
    detect_conflicts,
    allocate_zones,
    generate_layout,
    validate_layout,
]

__all__ = ["GIS_TOOLS"]
