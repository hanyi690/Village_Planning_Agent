"""Data acquisition tools — fetch GIS data and search POI."""

import json
from typing import Any

from langchain_core.tools import tool


@tool
def fetch_gis_data(location: str, buffer_km: float = 5.0, max_features: int = 500) -> str:
    """Fetch GIS data (water, road, residential) for a location.
    Args:
        location: Village name or address.
        buffer_km: Search radius in km. Default 5.
        max_features: Max features per layer. Default 500.
    """
    from app.modules.gis.data.fetcher import get_fetcher
    if not location:
        return json.dumps({"success": False, "error": "location required"}, ensure_ascii=False)
    fetcher = get_fetcher()
    result = fetcher.fetch_all_gis_data(location, buffer_km, max_features)
    summary: dict[str, Any] = {
        "location": result.get("location"),
        "is_village_level": result.get("is_village_level", False),
        "layers": {},
    }
    for key in ("water", "road", "residential"):
        layer = result.get(key, {})
        features = layer.get("geojson", {}).get("features", []) if layer.get("success") and layer.get("geojson") else []
        summary["layers"][key] = len(features)
    return json.dumps({"success": True, "data": summary}, ensure_ascii=False)


@tool
def search_poi(keyword: str, center: list, radius: int = 1000, page_size: int = 20) -> str:
    """Search POI near a location (Amap priority, Tianditu fallback).
    Args:
        keyword: Search keyword (e.g. school, hospital).
        center: Center coordinates [lon, lat].
        radius: Search radius in meters. Default 1000.
        page_size: Results per page. Default 20.
    """
    from app.modules.gis.data.providers.poi import POIProvider
    if not keyword:
        return json.dumps({"success": False, "error": "keyword required"}, ensure_ascii=False)
    if not center:
        return json.dumps({"success": False, "error": "center required"}, ensure_ascii=False)
    c = tuple(center) if isinstance(center, list) else center
    result = POIProvider.search_poi_nearby(keyword=keyword, center=c, radius=radius, page_size=page_size)
    return json.dumps(result, ensure_ascii=False)
