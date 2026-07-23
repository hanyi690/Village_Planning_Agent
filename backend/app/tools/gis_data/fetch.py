"""Tool: fetch_gis_data — fetch GIS data layers for a location."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.tools.helpers import make_result


@tool
def fetch_gis_data(location: str, buffer_km: float = 5.0, max_features: int = 500) -> dict[str, Any]:
    """Fetch GIS data (water, road, residential) for a location.

    Args:
        location: Village name or address.
        buffer_km: Search radius in km. Default 5.
        max_features: Max features per layer. Default 500.
    """
    from app.modules.gis.data.fetcher import get_fetcher
    if not location:
        return make_result(success=False, error="location required")
    fetcher = get_fetcher()
    result = fetcher.fetch_all_gis_data(location, buffer_km, max_features)
    summary: dict[str, Any] = {
        "location": result.get("location"),
        "is_village_level": result.get("is_village_level", False),
        "layers": {},
    }
    for key in ("water", "road", "residential"):
        layer = result.get(key, {})
        features = (
            layer.get("geojson", {}).get("features", [])
            if layer.get("success") and layer.get("geojson")
            else []
        )
        summary["layers"][key] = len(features)
    return make_result(success=True, data=summary)
