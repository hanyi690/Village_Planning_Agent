"""Tianditu vector service driver — WFS / MapServer REST.

Wraps GDSpecializedService to provide DataSourceDriver interface
for Guangdong Tianditu thematic services (三区三线, 生态红线, etc.).

Config keys:
    service_id: str       # e.g. "SQSXWPSJ"
    protocol: str          # "mapserver_rest" | "wfs"
    layers: list[dict]    # [{id, name, layer_type}]
    crs: str              # default "EPSG:4490"
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.modules.gis.schema.canonical import BBox
from app.modules.gis.data.providers.tianditu.gd_service import GDSpecializedService
from app.utils.logger import get_logger

from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("tianditu_vector")
class TiandituVectorDriver(DataSourceDriver):
    """Guangdong Tianditu thematic vector driver.

    Fetches constraint layers (farmland, ecological, urban boundary,
    geological hazard) as GeoJSON FeatureCollections via MapServer REST
    or WFS fallback.
    """

    driver_type = "vector"

    def __init__(self, config: Dict[str, Any]):
        self.service_id = config["service_id"]
        self.protocol = config.get("protocol", "mapserver_rest")
        self.layers: List[Dict[str, Any]] = config.get("layers", [])
        self.crs = config.get("crs", "EPSG:4490")
        self.gd = GDSpecializedService()

    def fetch(
        self,
        bbox: Optional[BBox] = None,
        layer_type: Optional[str] = None,
        **kwargs,
    ) -> DataSourceResult:
        """Fetch vector data for a specific layer type.

        Args:
            bbox: Bounding box for spatial query.
            layer_type: Semantic layer type to fetch.
            **kwargs: Passed to underlying service.

        Returns:
            DataSourceResult with GeoJSON data.
        """
        if bbox is None:
            return DataSourceResult.fail(error="bbox required for vector fetch")

        if layer_type is None:
            return DataSourceResult.fail(error="layer_type required")

        # Find layer config by layer_type
        layer_config = self._find_layer(layer_type)
        if not layer_config:
            return DataSourceResult.fail(
                error=f"Layer type '{layer_type}' not found in service {self.service_id}"
            )

        layer_id = layer_config["id"]

        # Try MapServer REST query first (GeoJSON)
        if self.protocol == "mapserver_rest":
            result = self.gd.query_mapserver_layer(
                self.service_id, layer_id, bbox.as_tuple
            )
            if result.success and result.data:
                geojson = result.data.get("geojson")
                if geojson:
                    return DataSourceResult.ok(
                        data=geojson,
                        data_type="geojson",
                        service_id=self.service_id,
                        layer_id=layer_id,
                        layer_name=layer_config.get("name", ""),
                        source="mapserver_rest",
                    )

        # Fallback to WFS
        result = self.gd.fetch_constraint_data(layer_type, bbox.as_tuple)
        if result.success and result.data.get("geojson"):
            return DataSourceResult.ok(
                data=result.data["geojson"],
                data_type="geojson",
                service_id=self.service_id,
                layer_type=layer_type,
                source="wfs",
            )

        # WMS fallback — not GeoJSON, return URL for visualization
        wms_url = self.gd.get_wms_map_url(self.service_id, bbox.as_tuple)
        return DataSourceResult(
            success=True,
            data={"wms_url": wms_url},
            data_type="url",
            metadata={
                "service_id": self.service_id,
                "layer_type": layer_type,
                "source": "wms",
                "note": "WMS imagery only, no vector data",
            },
        )

    def _find_layer(self, layer_type: str) -> Optional[Dict[str, Any]]:
        """Find layer configuration by layer_type."""
        for layer in self.layers:
            if layer.get("layer_type") == layer_type:
                return layer
        return None

    def list_layer_types(self) -> List[str]:
        """Return all supported layer_type values."""
        return [layer.get("layer_type", "") for layer in self.layers]

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        return DataSourceMetadata(
            name=self.service_id,
            driver="tianditu_vector",
            crs=self.crs,
            source_url=self.gd.get_service_rest_url(self.service_id),
        )

    @property
    def supports_bbox_query(self) -> bool:
        return True


__all__ = ["TiandituVectorDriver"]
