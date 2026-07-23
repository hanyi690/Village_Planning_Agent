"""Tool: calculate_gis_coverage + analyze_accessibility — GIS spatial analysis."""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import tool

from app.tools.helpers import make_result


@tool
def calculate_gis_coverage(location: str, buffer_km: float = 5.0, max_features: int = 100) -> dict[str, Any]:
    """Calculate GIS data coverage and completeness for a location."""
    from app.tools.gis._analytics.coverage import calculate_coverage as _calc
    if not location:
        return make_result(success=False, error="location required")
    result = _calc(location=location, buffer_km=buffer_km, max_features=max_features)
    return make_result(success=result.get("success", True), data=result)


@tool
def analyze_accessibility(
    analysis_type: str = "driving_accessibility",
    origin: Optional[list] = None,
    destinations: Optional[list] = None,
    center: Optional[list] = None,
) -> dict[str, Any]:
    """Accessibility analysis (driving/walking/service/isochrone).

    Args:
        analysis_type: driving_accessibility, walking_accessibility, service_coverage, poi_coverage, isochrone
        origin: Origin coordinates [lon, lat]
        destinations: Destination list [[lon, lat], ...]
        center: Center coordinates [lon, lat]
    """
    from app.tools.gis._analytics.accessibility import run_accessibility_analysis
    o = tuple(origin) if origin else None
    c = tuple(center) if center else None
    ds = [tuple(d) if isinstance(d, list) else d for d in destinations] if destinations else None
    result = run_accessibility_analysis(analysis_type=analysis_type, origin=o, destinations=ds, center=c)
    return make_result(success=result.get("success", True), data=result)
