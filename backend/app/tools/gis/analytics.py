"""Analytics tools — GIS coverage and accessibility analysis."""

import json
from typing import Optional

from langchain_core.tools import tool


@tool
def calculate_gis_coverage(location: str, buffer_km: float = 5.0, max_features: int = 100) -> str:
    """Calculate GIS data coverage and completeness for a location."""
    from ._analytics.coverage import calculate_gis_coverage
    if not location:
        return json.dumps({"success": False, "error": "location required"}, ensure_ascii=False)
    result = calculate_gis_coverage(location=location, buffer_km=buffer_km, max_features=max_features)
    return json.dumps(result, ensure_ascii=False)


@tool
def analyze_accessibility(
    analysis_type: str = "driving_accessibility",
    origin: Optional[list] = None,
    destinations: Optional[list] = None,
    center: Optional[list] = None,
) -> str:
    """Accessibility analysis (driving/walking/service/isochrone).
    Args:
        analysis_type: driving_accessibility, walking_accessibility, service_coverage, poi_coverage, isochrone
        origin: Origin coordinates [lon, lat]
        destinations: Destination list [[lon, lat], ...]
        center: Center coordinates [lon, lat]
    """
    from ._analytics.accessibility import run_accessibility_analysis
    o = tuple(origin) if origin else None
    c = tuple(center) if center else None
    ds = [tuple(d) if isinstance(d, list) else d for d in destinations] if destinations else None
    result = run_accessibility_analysis(analysis_type=analysis_type, origin=o, destinations=ds, center=c)
    return json.dumps(result, ensure_ascii=False)
