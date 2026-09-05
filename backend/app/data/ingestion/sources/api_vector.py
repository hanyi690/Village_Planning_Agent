"""API vector driver for declared WFS and MapServer REST services.

Fetches vector data from a single declared remote protocol. Uses a named
Connection for credentials and rate limiting. The remote admission receipt
must be bound before fetch; protocol failure is terminal for this driver.

Config keys:
    connection: str       # ConnectionRegistry name ('gd_tianditu', 'tianditu')
    service_id: str       # e.g. 'SQSXWPSJ' (Guangdong thematic service ID)
    protocol: str         # 'mapserver_rest' | 'wfs'
    layers: list[dict]    # [{id, name, layer_type}]
    crs: str              # default 'EPSG:4490'
"""

from __future__ import annotations

from typing import Any, Optional

from app.contracts.data.geometry_contracts import BBox
from app.infrastructure.logging import get_logger

from ..contracts import DataResult, DataSourceMetadata
from .base import DataSourceDriver
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("api_vector")
class ApiVectorDriver(DataSourceDriver):
    """API vector service driver.

    Fetches declared layers as GeoJSON via exactly one declared protocol.
    """

    driver_type = "vector"

    def __init__(self, config: dict[str, Any]):
        self.connection_name = config.get("connection", "")
        self.service_id = config.get("service_id", "")
        self.protocol = config.get("protocol", "mapserver_rest")
        self.layers: list[dict[str, Any]] = config.get("layers", [])
        self.crs = config.get("crs", "EPSG:4490")
        self.layer_type = config.get("layer_type", "")
        self.source_id = str(config.get("source_id") or "")

    def _get_service(self):
        """Build a GDSpecializedService bound to this driver's Connection.

        The specialized service is the protocol client; admission and
        publication remain outside this driver.
        """
        from app.data.ingestion.connections import ConnectionRegistry
        from app.data.ingestion.providers.tianditu.gd_service import GDSpecializedService

        conn = ConnectionRegistry.require(self.connection_name)
        return GDSpecializedService(gd_token=conn.token, base_url=conn.base_url)

    def fetch(
        self,
        bbox: Optional[BBox] = None,
        layer_type: Optional[str] = None,
        **kwargs: Any,
    ) -> DataResult:
        """Fetch vector data for a specific layer type.

        Args:
            bbox: Bounding box for spatial query (required).
            layer_type: Semantic layer type to fetch (required).
            **kwargs: Passed to underlying service.

        Returns:
            DataResult with GeoJSON (data_type="geojson") or WMS URL
            (data_type="url") when only imagery is available.
        """
        if bbox is None:
            return DataResult.fail(error="bbox required for api_vector fetch")
        if layer_type is None:
            return DataResult.fail(error="layer_type required")
        admission_error = self._require_remote_admission(
            expected_kinds={
                "api_vector",
                self.protocol,
                "mapserver" if self.protocol == "mapserver_rest" else self.protocol,
            }
        )
        if admission_error is not None:
            return admission_error

        layer_config = self._find_layer(layer_type)
        if not layer_config:
            return DataResult.fail(
                error=f"Layer type '{layer_type}' not found in service {self.service_id}"
            )

        layer_id = layer_config["id"]
        gd = self._get_service()

        if self.protocol == "mapserver_rest":
            result = gd.query_mapserver_layer(self.service_id, layer_id, bbox.as_tuple)
            if result.success and result.data:
                geojson = result.data.get("geojson")
                if geojson:
                    return DataResult.ok(
                        data=geojson,
                        data_type="geojson",
                        service_id=self.service_id,
                        layer_id=layer_id,
                        layer_name=layer_config.get("name", ""),
                        source="mapserver_rest",
                    )
            return DataResult.fail(
                error=(
                    result.error
                    or f"MapServer REST returned no vector data for {self.service_id}:{layer_id}"
                )
            )

        if self.protocol == "wfs":
            result = gd.fetch_constraint_data(layer_type, bbox.as_tuple)
            if result.success and result.data and result.data.get("geojson"):
                return DataResult.ok(
                    data=result.data["geojson"],
                    data_type="geojson",
                    service_id=self.service_id,
                    layer_type=layer_type,
                    source="wfs",
                )
            return DataResult.fail(
                error=(
                    result.error
                    or f"WFS returned no vector data for {self.service_id}:{layer_type}"
                )
            )

        return DataResult.fail(error=f"unsupported declared vector protocol: {self.protocol}")

    def _find_layer(self, layer_type: str) -> Optional[dict[str, Any]]:
        """Find layer configuration by layer_type."""
        for layer in self.layers:
            if layer.get("layer_type") == layer_type:
                return layer
        return None

    def list_layer_types(self) -> list[str]:
        """Return all supported layer_type values."""
        return [layer.get("layer_type", "") for layer in self.layers]

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        return DataSourceMetadata(
            name=self.service_id,
            driver="api_vector",
            crs=self.crs,
            layer_type=self.layer_type,
        )

    @property
    def supports_bbox_query(self) -> bool:
        return True


__all__ = ["ApiVectorDriver"]
