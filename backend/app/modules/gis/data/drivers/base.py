"""GIS data source driver base classes.

All data source drivers MUST implement DataSourceDriver ABC.
Results are wrapped in DataSourceResult for uniform handling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.modules.schema.types.canonical import BBox


@dataclass
class DataSourceResult:
    """Unified result wrapper for all driver operations."""

    success: bool
    data: Any = None
    data_type: str = ""  # "geojson" | "tiles" | "mosaic" | "raster" | "url"
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    cache_path: Optional[str] = None

    @classmethod
    def ok(cls, data: Any, data_type: str = "", **metadata) -> "DataSourceResult":
        return cls(success=True, data=data, data_type=data_type, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata) -> "DataSourceResult":
        return cls(success=False, error=error, metadata=metadata)


@dataclass
class DataSourceMetadata:
    """Unified metadata for a data source."""

    name: str
    driver: str
    crs: str = "EPSG:4326"
    bbox: Optional[BBox] = None
    resolution: Optional[float] = None
    feature_count: Optional[int] = None
    update_time: Optional[str] = None
    source_url: Optional[str] = None


class DataSourceDriver(ABC):
    """Abstract base for all GIS data source drivers.

    Drivers handle one type of data source:
      - vector: GeoJSON, Shapefile, WFS, MapServer REST
      - raster_tile: WMTS tiles
      - raster_file: GeoTIFF, IMG
    """

    @property
    @abstractmethod
    def driver_type(self) -> str:
        """Driver category: vector | raster_tile | raster_file."""
        ...

    @abstractmethod
    def fetch(self, bbox: Optional[BBox] = None, **kwargs) -> DataSourceResult:
        """Fetch data from the source.

        Args:
            bbox: Optional bounding box for spatial queries.
            **kwargs: Driver-specific parameters.

        Returns:
            DataSourceResult with success flag and data.
        """
        ...

    @abstractmethod
    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata about this data source."""
        ...

    @property
    def supports_bbox_query(self) -> bool:
        """Whether this driver supports bbox-based spatial queries."""
        return False

    @property
    def is_cached(self) -> bool:
        """Whether data is available from local cache."""
        return False


__all__ = ["DataSourceDriver", "DataSourceResult", "DataSourceMetadata"]
