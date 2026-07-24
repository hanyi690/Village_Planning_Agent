"""Local raster file driver — GeoTIFF, IMG, etc.

Loads local raster files and returns metadata via rasterio.
Does NOT load the full raster array into memory.

Config keys:
    path: str          # file path
    format: str        # "GeoTIFF" | "IMG" | "HFA"
    crs: str           # default "EPSG:4326"
    layer_type: str    # semantic type: "dem", "dom", etc.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from app.modules.schema.types.canonical import BBox
from app.utils.logger import get_logger

from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("local_raster")
class LocalRasterDriver(DataSourceDriver):
    """Local raster file driver.

    Uses rasterio for metadata extraction. Full data loading
    is deferred to consumers (e.g., slope analysis tools).
    """

    driver_type = "raster_file"

    def __init__(self, config: Dict[str, Any]):
        self.path = Path(config["path"])
        self.format = config.get("format", "GeoTIFF")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "")

    def fetch(self, bbox: Optional[BBox] = None, **kwargs) -> DataSourceResult:
        """Return raster file path and metadata.

        Args:
            bbox: Optional bounding box for spatial subset (not implemented).
            **kwargs: Unused.

        Returns:
            DataSourceResult with file path and metadata.
        """
        if not self.path.exists():
            return DataSourceResult.fail(
                error=f"Raster file not found: {self.path}"
            )

        try:
            metadata = self._read_metadata()
            return DataSourceResult.ok(
                data=str(self.path),
                data_type="raster",
                path=str(self.path),
                format=self.format,
                crs=metadata.get("crs", self.crs),
                resolution=metadata.get("resolution"),
                width=metadata.get("width"),
                height=metadata.get("height"),
                bands=metadata.get("bands"),
                dtype=metadata.get("dtype"),
                bounds=metadata.get("bounds"),
            )
        except Exception as e:
            logger.error("[LocalRasterDriver] Failed to read %s: %s", self.path, e)
            return DataSourceResult.fail(error=str(e))

    def _read_metadata(self) -> Dict[str, Any]:
        """Read raster metadata using rasterio."""
        try:
            import rasterio
        except ImportError:
            # Fallback: return basic file info
            return {
                "crs": self.crs,
                "resolution": None,
                "width": None,
                "height": None,
                "bands": None,
                "dtype": None,
                "bounds": None,
                "note": "rasterio not installed",
            }

        with rasterio.open(self.path) as ds:
            res = ds.res[0] if ds.res else None
            bounds = {
                "west": ds.bounds.left,
                "south": ds.bounds.bottom,
                "east": ds.bounds.right,
                "north": ds.bounds.top,
            }
            return {
                "crs": str(ds.crs) if ds.crs else self.crs,
                "resolution": res,
                "width": ds.width,
                "height": ds.height,
                "bands": ds.count,
                "dtype": str(ds.dtypes[0]) if ds.dtypes else None,
                "bounds": bounds,
            }

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        feature_count = None
        resolution = None

        if self.path.exists():
            try:
                meta = self._read_metadata()
                resolution = meta.get("resolution")
            except Exception:
                pass

        return DataSourceMetadata(
            name=self.path.stem,
            driver="local_raster",
            crs=self.crs,
            resolution=resolution,
        )

    @property
    def supports_bbox_query(self) -> bool:
        return False

    @property
    def is_cached(self) -> bool:
        return self.path.exists()


__all__ = ["LocalRasterDriver"]
