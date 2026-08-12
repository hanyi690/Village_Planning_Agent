"""Local vector file driver - GeoJSON, Shapefile, GDB.

Loads vector files from local disk and returns GeoJSON FeatureCollections.
Migrated from gis/data/drivers/file_vector_driver.py. Source files in this
project are already WGS-84/CGCS2000, so no CRS conversion is needed here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.data.model.canonical import BBox
from app.infrastructure.logging import get_logger

from ..contracts import DataResult, DataSourceMetadata
from .base import DataSourceDriver
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("file_vector")
class FileVectorDriver(DataSourceDriver):
    """Local vector file driver.

    Supports:
      - GeoJSON (.geojson, .json)
      - Shapefile (.shp) via geopandas (optional)
      - FileGDB (.gdb) via geopandas (optional)

    Config keys:
        path: str          # file path
        format: str        # "geojson" | "shapefile" | "gdb"
        crs: str           # default "EPSG:4326"
        layer_type: str    # semantic layer type
        encoding: str      # file encoding (geojson only)
    """

    driver_type = "vector"

    def __init__(self, config: dict[str, Any]):
        self.path = Path(config["path"])
        self.format = config.get("format", "geojson")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "")
        self.encoding = config.get("encoding", "utf-8")

    def fetch(self, bbox: Optional[BBox] = None, **kwargs: Any) -> DataResult:
        """Load vector file and return GeoJSON.

        Args:
            bbox: Ignored for local files (no spatial filtering).
            **kwargs: Unused.

        Returns:
            DataResult with geojson data_type.
        """
        if not self.path.exists():
            return DataResult.fail(error=f"File not found: {self.path}")

        try:
            if self.format == "geojson":
                return self._load_geojson()
            return self._load_via_geopandas()
        except Exception as e:
            logger.error("[FileVectorDriver] Failed to load %s: %s", self.path, e)
            return DataResult.fail(error=str(e))

    def _load_geojson(self) -> DataResult:
        """Load a GeoJSON file."""
        with open(self.path, "r", encoding=self.encoding) as f:
            geojson = json.load(f)

        features = geojson.get("features", [])
        return DataResult.ok(
            data=geojson,
            data_type="geojson",
            path=str(self.path),
            format=self.format,
            feature_count=len(features),
        )

    def _load_via_geopandas(self) -> DataResult:
        """Load Shapefile or GDB via geopandas."""
        try:
            import geopandas as gpd
        except ImportError:
            return DataResult.fail(
                error="geopandas not installed. Install with: pip install geopandas"
            )

        gdf = gpd.read_file(self.path)
        geojson = gdf.__geo_interface__

        return DataResult.ok(
            data=geojson,
            data_type="geojson",
            path=str(self.path),
            format=self.format,
            feature_count=len(gdf),
        )

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        feature_count = None
        if self.path.exists() and self.format == "geojson":
            try:
                with open(self.path, "r", encoding=self.encoding) as f:
                    data = json.load(f)
                feature_count = len(data.get("features", []))
            except Exception:
                pass

        return DataSourceMetadata(
            name=self.path.stem,
            driver="file_vector",
            crs=self.crs,
            layer_type=self.layer_type,
            feature_count=feature_count,
        )

    @property
    def supports_bbox_query(self) -> bool:
        return False


__all__ = ["FileVectorDriver"]
