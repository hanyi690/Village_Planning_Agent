"""Compatibility wrapper for legacy run_gis_analysis imports."""

from __future__ import annotations

from typing import Any, Dict


def run_gis_analysis(analysis_type: str, **kwargs: Any) -> Dict[str, Any]:
    """Dispatch a small set of GIS analyses to current modules."""
    if analysis_type in {"driving_accessibility", "walking_accessibility", "service_coverage", "poi_coverage"}:
        from .accessibility import run_accessibility_analysis
        return run_accessibility_analysis(analysis_type=analysis_type, **kwargs)
    if analysis_type in {"isochrone", "isochrones"}:
        from .isochrone import generate_isochrones
        center = kwargs.get("center")
        if isinstance(center, list):
            center = tuple(center)
        return generate_isochrones(center=center, **{k: v for k, v in kwargs.items() if k != "center"})
    return {"success": False, "error": f"Unsupported GIS analysis type: {analysis_type}"}
