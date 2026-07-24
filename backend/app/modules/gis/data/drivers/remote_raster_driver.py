"""Remote raster download driver — DEM/DOM download guides.

Manages external raster data sources that require manual download.
Returns download instructions when data is not available locally.
Falls back to LocalRasterDriver if file exists.

Config keys:
    provider: str          # e.g. "alos_aw3d30", "gdem_v3"
    resolution: str         # e.g. "12.5m", "30m"
    format: str             # "GeoTIFF"
    crs: str                # "EPSG:4326"
    layer_type: str         # "dem" | "dom"
    download_guide: dict   # {url, steps: list}
    local_path: str         # expected local file path
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from app.modules.gis.schema.canonical import BBox
from app.utils.logger import get_logger

from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry
from .local_raster_driver import LocalRasterDriver

logger = get_logger(__name__)


@DriverRegistry.register("remote_raster")
class RemoteRasterDriver(DataSourceDriver):
    """Remote raster download guide driver.

    When local file exists: delegates to LocalRasterDriver.
    When missing: returns download guide with source URL and steps.

    Providers:
      - alos_aw3d30: JAXA ALOS World 3D, 12.5m, free (research)
      - gdem_v3: ASTER GDEM V3, 30m, free via gscloud.cn
      - srtm: USGS SRTM, 30m, free
      - sentinel2: Copernicus Sentinel-2, 10m, free
    """

    driver_type = "raster_file"

    def __init__(self, config: Dict[str, Any]):
        self.provider = config["provider"]
        self.resolution = config.get("resolution", "")
        self.format = config.get("format", "GeoTIFF")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "")
        self.download_guide = config.get("download_guide", {})
        self.local_path = Path(config.get("local_path", ""))

    def fetch(self, bbox: Optional[BBox] = None, **kwargs) -> DataSourceResult:
        """Check local file or return download guide.

        Args:
            bbox: Unused (remote rasters are pre-downloaded).
            **kwargs: Passed to LocalRasterDriver if file exists.

        Returns:
            DataSourceResult with raster path or download guide.
        """
        # Check if already downloaded
        if self.local_path.exists():
            # Delegate to local driver
            local = LocalRasterDriver({
                "path": str(self.local_path),
                "format": self.format,
                "crs": self.crs,
                "layer_type": self.layer_type,
            })
            result = local.fetch(bbox, **kwargs)
            # Tag as remote source even though local
            if result.success:
                result.metadata["source"] = "remote_raster"
                result.metadata["provider"] = self.provider
            return result

        # Not available — return download guide
        return DataSourceResult(
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
            resolution=self._parse_resolution(),
        )

    def _parse_resolution(self) -> Optional[float]:
        """Parse resolution string to meters."""
        try:
            # Handle "12.5m", "30m", "10m", etc.
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

    def get_download_guide(self) -> Dict[str, Any]:
        """Return structured download instructions."""
        return {
            "provider": self.provider,
            "resolution": self.resolution,
            "format": self.format,
            **self.download_guide,
            "local_path": str(self.local_path),
        }


__all__ = ["RemoteRasterDriver"]
