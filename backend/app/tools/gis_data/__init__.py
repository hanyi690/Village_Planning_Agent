"""GIS data acquisition tools — non-pipeline, lightweight queries.

These tools fetch GIS data from providers and calculate coverage/accessibility.
Unlike pipeline tools in tools/gis/, these are used by the Router Agent and
test routes for pre-pipeline data gathering.

See: docs/gis/proposals/03_TOOL_FIRST_ARCHITECTURE.md
"""

from .fetch import fetch_gis_data
from .search_poi import search_poi
from .analytics import calculate_gis_coverage, analyze_accessibility

GIS_DATA_TOOLS = [
    fetch_gis_data,
    search_poi,
    calculate_gis_coverage,
    analyze_accessibility,
]

__all__ = ["GIS_DATA_TOOLS"]
