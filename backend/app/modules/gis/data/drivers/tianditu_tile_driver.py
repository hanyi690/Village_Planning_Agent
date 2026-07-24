"""Tianditu WMTS tile driver — batch download and mosaic.

Downloads tiles from Tianditu WMTS services within a bounding box,
caches them locally, and optionally mosaics into a single GeoTIFF.

Config keys:
    layer: str           # "img_c", "ter_c", "cia_c", etc.
    projection: str     # "c" (EPSG:4326) or "w" (EPSG:3857)
    zoom_range: list    # [min, max] zoom levels
    format: str         # "png"
    cache_dir: str      # local cache path
    crs: str            # "EPSG:4326"
    layer_type: str     # semantic type: "dom", "terrain_visual", etc.
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.modules.gis.schema.canonical import BBox
from app.modules.gis.data.providers.tianditu.tiles import TileService
from app.utils.logger import get_logger

from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("tianditu_tile")
class TiandituTileDriver(DataSourceDriver):
    """Tianditu WMTS tile driver.

    Supports:
      - img_c/w: imagery base map (DOM visualization)
      - ter_c/w: terrain hillshade (visualization)
      - cia_c/w: imagery annotation
      - ibo_c/w: global boundary
      - dom2023: Guangdong 2023 imagery (via service_id)

    Note: ter_c is terrain hillshade visualization, NOT raw DEM.
    Raw DEM requires LocalRasterDriver or RemoteRasterDriver.
    """

    driver_type = "raster_tile"

    def __init__(self, config: Dict[str, Any]):
        self.layer = config.get("layer", "img_c")
        self.projection = config.get("projection", "c")
        self.zoom_range = config.get("zoom_range", [1, 18])
        self.format = config.get("format", "png")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "dom")
        self.service_id = config.get("service_id")  # for Guangdong thematic tiles

        self.tile_service = TileService()
        self.cache_dir = Path(config.get("cache_dir", "data/cache/tiles"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Rate limiting
        self._last_request_time = 0.0
        self._min_interval = 0.1  # 10 req/sec max

    def fetch(
        self,
        bbox: Optional[BBox] = None,
        zoom: int = 16,
        mosaic: bool = False,
        **kwargs,
    ) -> DataSourceResult:
        """Download tiles for a bounding box.

        Args:
            bbox: Bounding box (required).
            zoom: Zoom level (1-18).
            mosaic: If True, merge tiles into single GeoTIFF.
            **kwargs: Unused.

        Returns:
            DataSourceResult with tile paths or mosaic path.
        """
        if bbox is None:
            return DataSourceResult.fail(error="bbox required for tile fetch")

        if not (self.zoom_range[0] <= zoom <= self.zoom_range[1]):
            return DataSourceResult.fail(
                error=f"zoom {zoom} out of range {self.zoom_range}"
            )

        # 1. Compute tile coordinates
        tiles = self._bbox_to_tiles(bbox, zoom)
        if not tiles:
            return DataSourceResult.fail(error="No tiles in bbox at this zoom")

        logger.info(
            "[TiandituTileDriver] Fetching %d tiles at z=%d for %s",
            len(tiles),
            zoom,
            self.layer,
        )

        # 2. Batch download with cache
        downloaded: List[Path] = []
        failed = 0
        for x, y, z in tiles:
            tile_path = self._get_cached_tile(x, y, z)
            if tile_path.exists():
                downloaded.append(tile_path)
                continue

            tile_path = self._download_tile(x, y, z)
            if tile_path:
                downloaded.append(tile_path)
            else:
                failed += 1

        if not downloaded:
            return DataSourceResult.fail(error="No tiles downloaded")

        if failed > 0:
            logger.warning(
                "[TiandituTileDriver] %d/%d tiles failed",
                failed,
                len(tiles),
            )

        # 3. Optional mosaic
        if mosaic:
            try:
                mosaic_path = self._mosaic_tiles(downloaded, bbox, zoom)
                return DataSourceResult.ok(
                    data=str(mosaic_path),
                    data_type="mosaic",
                    tile_count=len(downloaded),
                    failed_count=failed,
                    zoom=zoom,
                    layer=self.layer,
                    cache_path=str(mosaic_path),
                )
            except Exception as e:
                logger.error("[TiandituTileDriver] Mosaic failed: %s", e)
                # Fall through to returning individual tiles

        return DataSourceResult.ok(
            data=[str(p) for p in downloaded],
            data_type="tiles",
            tile_count=len(downloaded),
            failed_count=failed,
            zoom=zoom,
            layer=self.layer,
        )

    def _bbox_to_tiles(self, bbox: BBox, zoom: int) -> List[Tuple[int, int, int]]:
        """Convert bounding box to tile coordinate list."""

        def latlon_to_tile(
            lat: float, lon: float, z: int
        ) -> Tuple[int, int]:
            n = 2.0 ** z
            x = int((lon + 180.0) / 360.0 * n)
            lat_rad = math.radians(lat)
            y = int(
                (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
                / 2.0
                * n
            )
            return x, y

        min_x, max_y = latlon_to_tile(bbox.south, bbox.west, zoom)
        max_x, min_y = latlon_to_tile(bbox.north, bbox.east, zoom)

        tiles = []
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                tiles.append((x, y, zoom))
        return tiles

    def _get_cached_tile(self, x: int, y: int, z: int) -> Path:
        """Get cache path for a tile."""
        return (
            self.cache_dir
            / self.layer
            / str(z)
            / str(x)
            / f"{y}.{self.format}"
        )

    def _download_tile(self, x: int, y: int, z: int) -> Optional[Path]:
        """Download a single tile with rate limiting."""
        # Rate limit
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        if self.service_id:
            # Guangdong thematic service
            from app.modules.gis.data.providers.tianditu.gd_service import (
                GDSpecializedService,
            )

            gd = GDSpecializedService()
            url = gd.get_wmts_tile_url(
                self.service_id, x, y, z, self.projection
            )
        else:
            # National Tianditu service
            url = self.tile_service.get_tile_url(
                layer=self.layer,
                projection=self.projection,
                x=x,
                y=y,
                z=z,
            )

        tile_path = self._get_cached_tile(x, y, z)
        tile_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            resp = requests.get(url, timeout=30, headers={
                "Accept": "image/png",
                "User-Agent": "VillagePlanningAgent/1.0",
            })
            self._last_request_time = time.time()

            if resp.status_code == 200:
                tile_path.write_bytes(resp.content)
                return tile_path
            else:
                logger.warning(
                    "[TiandituTileDriver] HTTP %d for tile %d/%d/%d",
                    resp.status_code,
                    z,
                    x,
                    y,
                )
        except requests.Timeout:
            logger.warning("[TiandituTileDriver] Timeout for tile %d/%d/%d", z, x, y)
        except Exception as e:
            logger.warning("[TiandituTileDriver] Error downloading tile: %s", e)

        return None

    def _mosaic_tiles(
        self, tiles: List[Path], bbox: BBox, zoom: int
    ) -> Path:
        """Merge tiles into a single GeoTIFF using rasterio.

        Args:
            tiles: List of tile file paths.
            bbox: Target bounding box.
            zoom: Zoom level.

        Returns:
            Path to merged GeoTIFF.
        """
        try:
            import rasterio
            from rasterio.merge import merge
        except ImportError:
            raise ImportError(
                "rasterio required for mosaic. Install: pip install rasterio"
            )

        # Open all tile datasets
        datasets = []
        for p in tiles:
            try:
                ds = rasterio.open(p)
                datasets.append(ds)
            except Exception:
                continue

        if not datasets:
            raise ValueError("No valid tiles to mosaic")

        # Merge
        mosaic_data, mosaic_transform = merge(datasets)

        # Output path
        out_path = (
            self.cache_dir
            / self.layer
            / f"mosaic_z{zoom}_{bbox.west:.4f}_{bbox.south:.4f}.tif"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Write GeoTIFF
        with rasterio.open(
            out_path,
            "w",
            driver="GTiff",
            height=mosaic_data.shape[1],
            width=mosaic_data.shape[2],
            count=mosaic_data.shape[0],
            dtype=mosaic_data.dtype,
            crs="EPSG:4326",
            transform=mosaic_transform,
        ) as dst:
            dst.write(mosaic_data)

        # Close datasets
        for ds in datasets:
            ds.close()

        logger.info("[TiandituTileDriver] Mosaic saved: %s", out_path)
        return out_path

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        return DataSourceMetadata(
            name=f"tianditu_{self.layer}",
            driver="tianditu_tile",
            crs=self.crs,
        )

    @property
    def supports_bbox_query(self) -> bool:
        return True

    @property
    def is_cached(self) -> bool:
        """Check if any tiles exist in cache."""
        return any(self.cache_dir.iterdir()) if self.cache_dir.exists() else False


__all__ = ["TiandituTileDriver"]
