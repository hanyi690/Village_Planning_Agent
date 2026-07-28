"""Tool: fetch_gis_data — load GIS data layers via DataCatalog."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.tools.helpers import make_result
from app.utils.logger import get_logger

logger = get_logger(__name__)


@tool
def fetch_gis_data(location: str, buffer_km: float = 5.0, max_features: int = 500) -> dict[str, Any]:
    """Load GIS data for a village via DataCatalog.

    Args:
        location: Village name or address.
        buffer_km: Search radius in km (unused for local file data). Default 5.
        max_features: Max features per layer (unused for local file data). Default 500.
    """
    from app.modules.data.catalog.catalog import DataCatalog

    if not location:
        return make_result(success=False, error="location required")

    try:
        catalog = DataCatalog()
        bundle = catalog.load_village_bundle(location)
        layers: dict[str, Any] = {
            "boundary": bool(bundle.boundary),
            "landuse_current": len(bundle.polygons.get("landuse_current")),
            "landuse_planned": len(bundle.polygons.get("landuse_planned")),
            "roads": len(bundle.lines.get("roads_current")) + len(bundle.lines.get("roads_planned")),
            "annotations": len(bundle.points.get("annotations_current")) + len(bundle.points.get("annotations_planned")),
        }
        return make_result(
            success=True,
            data={
                "location": location,
                "parcel_count": bundle.parcel_count,
                "layers": layers,
            },
        )
    except Exception as e:
        logger.warning("[fetch_gis_data] %s: %s", location, e)
        return make_result(success=False, error=str(e))
