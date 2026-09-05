"""Data source driver base class.

All data source drivers MUST implement DataSourceDriver. Drivers handle
one category of data source (vector file, API vector, WMTS tile, raster
file, document). Results are wrapped in DataResult for uniform handling.

Design references (see README.md section 2.1):
  - QGIS Data Provider: one driver per source type
  - DriverRegistry: decorator-based auto-discovery, no manual registration
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.contracts.data.geometry_contracts import BBox

from ..contracts import DataResult, DataSourceMetadata


class DataSourceDriver(ABC):
    """Abstract base for all data source drivers.

    Driver categories (``driver_type``):
      - ``vector``:       GeoJSON / Shapefile / GDB / WFS / MapServer REST
      - ``raster_tile``:  WMTS tile batches
      - ``raster_file``:  GeoTIFF / IMG
      - ``document``:     MinerU Markdown only
    """

    @property
    @abstractmethod
    def driver_type(self) -> str:
        """Driver category: vector | raster_tile | raster_file | document."""
        ...

    @abstractmethod
    def fetch(self, bbox: Optional[BBox] = None, **kwargs: Any) -> DataResult:
        """Fetch data from the source.

        Args:
            bbox: optional spatial filter (WGS84). Ignored by non-spatial sources.
            **kwargs: driver-specific parameters (layer_type, zoom, etc).

        Returns:
            DataResult. Never raises on data failure - check ``success``.
        """
        ...

    @abstractmethod
    def get_metadata(self) -> DataSourceMetadata:
        """Return static metadata for this data source."""
        ...

    @property
    def supports_bbox_query(self) -> bool:
        """Whether this driver supports bbox-based spatial queries."""
        return False

    @property
    def is_cached(self) -> bool:
        """Whether data is available from local cache without network."""
        return False

    _admission_receipt: Any = None

    def bind_remote_admission(self, receipt: Any, *, expected_kinds: set[str]) -> None:
        """Bind an admitted remote declaration before a network-capable fetch."""

        from app.contracts.data.remote_admission_contracts import RemoteSourceAdmissionReceipt

        if not isinstance(receipt, RemoteSourceAdmissionReceipt):
            raise TypeError("remote source requires RemoteSourceAdmissionReceipt")
        if receipt.status != "ADMITTED" or receipt.kind not in expected_kinds:
            raise ValueError("remote source admission receipt is not valid for this driver")
        self._admission_receipt = receipt

    def _require_remote_admission(self, *, expected_kinds: set[str]) -> DataResult | None:
        receipt = self._admission_receipt
        if receipt is None:
            return DataResult.fail(error="remote source requires an admitted declaration receipt")
        if receipt.status != "ADMITTED" or receipt.kind not in expected_kinds:
            return DataResult.fail(error="remote source admission receipt is invalid or stale")
        return None


__all__ = ["DataSourceDriver"]
