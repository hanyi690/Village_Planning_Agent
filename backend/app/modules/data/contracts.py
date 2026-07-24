"""Data contracts - unified result envelope and metadata for all data sources.

All DataSourceDriver.fetch() returns DataResult, never raises.
Canonical geometry types (BBox) are imported from gis.schema.canonical
to avoid duplicating the normative data shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.modules.schema.canonical import BBox


@dataclass
class DataResult:
    """Unified result envelope for all data source operations.

    Every driver method returns this type. Callers check ``success``
    before accessing ``data``. Never raises on data fetch failure.

    Attributes:
        success: whether the operation succeeded.
        data: payload - GeoJSON dict | tile path list | raster path | document text.
        data_type: payload category - "geojson" | "tiles" | "mosaic" | "raster" | "url" | "document".
        metadata: provenance and stats (feature_count, source, crs, etc).
        error: human-readable failure reason when success is False.
        cache_path: local cache file path if the result was served from cache.
    """

    success: bool
    data: Any = None
    data_type: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    cache_path: Optional[str] = None

    @classmethod
    def ok(cls, data: Any, data_type: str = "", **metadata: Any) -> "DataResult":
        return cls(success=True, data=data, data_type=data_type, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata: Any) -> "DataResult":
        return cls(success=False, error=error, metadata=metadata)


@dataclass
class DataSourceMetadata:
    """Static metadata describing a configured data source."""

    name: str
    driver: str
    crs: str = "EPSG:4326"
    layer_type: str = ""
    bbox: Optional[BBox] = None
    resolution: Optional[float] = None
    feature_count: Optional[int] = None
    update_time: Optional[str] = None
    source_url: Optional[str] = None


__all__ = ["DataResult", "DataSourceMetadata"]
