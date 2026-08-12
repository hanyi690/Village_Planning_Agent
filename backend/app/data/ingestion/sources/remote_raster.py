"""Remote raster download driver - DEM/DOM download guides.

Manages external raster sources that require manual download. Returns
download instructions when data is not available locally; falls back to
LocalRasterDriver if the file exists. Migrated from
gis/data/drivers/remote_raster_driver.py.

Providers:
  - alos_aw3d30: JAXA ALOS World 3D, 12.5m, free (research)
  - gdem_v3: ASTER GDEM V3, 30m, free via gscloud.cn
  - srtm: USGS SRTM, 30m, free
  - sentinel2: Copernicus Sentinel-2, 10m, free
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app.data.model.canonical import BBox
from app.utils.logger import get_logger

from ..contracts import DataResult, DataSourceMetadata
from .base import DataSourceDriver
from .local_raster import LocalRasterDriver
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("remote_raster")
class RemoteRasterDriver(DataSourceDriver):
    """Remote raster download guide driver.

    When local file exists: delegates to LocalRasterDriver.
    When missing: returns download guide with source URL and steps.
    """

    driver_type = "raster_file"

    def __init__(self, config: dict[str, Any]):
        self.provider = config["provider"]
        self.resolution = config.get("resolution", "")
        self.format = config.get("format", "GeoTIFF")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "")
        self.download_guide = config.get("download_guide", {})
        self.local_path = Path(config.get("local_path", ""))

    def fetch(self, bbox: Optional[BBox] = None, **kwargs: Any) -> DataResult:
        """Check local file or return download guide.

        Args:
            bbox: Unused (remote rasters are pre-downloaded).
            **kwargs: Passed to LocalRasterDriver if file exists.

        Returns:
            DataResult with raster path (data_type="raster") or
            download guide (data_type="download_guide", success=False).
        """
        if self.local_path.exists():
            local = LocalRasterDriver({
                "path": str(self.local_path),
                "format": self.format,
                "crs": self.crs,
                "layer_type": self.layer_type,
            })
            result = local.fetch(bbox, **kwargs)
            if result.success:
                result.metadata["source"] = "remote_raster"
                result.metadata["provider"] = self.provider
            return result

        return DataResult(
            success=False,
            data={
                "provider": self.provider,
                "resolution": self.resolution,
                "format": self.format,
                "download_guide": self.download_guide,
                "local_path": str(self.local_path),
            },
            data_type="download_guide",
            error=f"Raster not available locally: {self.provider}",
            metadata={
                "provider": self.provider,
                "resolution": self.resolution,
                "format": self.format,
                "download_guide": self.download_guide,
                "local_path": str(self.local_path),
                "layer_type": self.layer_type,
            },
        )

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        return DataSourceMetadata(
            name=self.provider,
            driver="remote_raster",
            crs=self.crs,
            layer_type=self.layer_type,
            resolution=self._parse_resolution(),
        )

    def _parse_resolution(self) -> Optional[float]:
        """Parse resolution string (e.g. '12.5m') to meters."""
        try:
            val = self.resolution.lower().replace("m", "").strip()
            return float(val)
        except (ValueError, AttributeError):
            return None

    @property
    def supports_bbox_query(self) -> bool:
        return False

    @property
    def is_cached(self) -> bool:
        return self.local_path.exists()

    def get_download_guide(self) -> dict[str, Any]:
        """Return structured download instructions."""
        return {
            "provider": self.provider,
            "resolution": self.resolution,
            "format": self.format,
            **self.download_guide,
            "local_path": str(self.local_path),
        }


__all__ = ["RemoteRasterDriver"]
