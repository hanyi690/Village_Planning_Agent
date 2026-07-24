"""Tool: search_poi — search POI near a location."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.tools.helpers import make_result


@tool
def search_poi(keyword: str, center: list, radius: int = 1000, page_size: int = 20) -> dict[str, Any]:
    """Search POI near a location (Amap priority, Tianditu fallback).

    Args:
        keyword: Search keyword (e.g. school, hospital).
        center: Center coordinates [lon, lat].
        radius: Search radius in meters. Default 1000.
        page_size: Results per page. Default 20.
    """
    from app.modules.data.providers.poi import POIProvider
    if not keyword:
        return make_result(success=False, error="keyword required")
    if not center:
        return make_result(success=False, error="center required")
    c = tuple(center) if isinstance(center, list) else center
    result = POIProvider.search_poi_nearby(keyword=keyword, center=c, radius=radius, page_size=page_size)
    return make_result(success=result.get("success", True), data=result)
