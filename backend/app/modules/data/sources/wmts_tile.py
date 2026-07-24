"""WMTS tile driver - batch download and mosaic.

Downloads tiles from WMTS services (Tianditu img_c / ter_c / cia_c,
Guangdong thematic dom2023) within a bounding box, caches them locally,
and optionally mosaics into a single GeoTIFF. Migrated from
gis/data/drivers/tianditu_tile_driver.py.

Uses the bound Connection's rate_limiter and requests.Session instead of
a per-driver limiter, so QPS is shared across all tile drivers targeting
the same service family.

Config keys:
    connection: str      # ConnectionRegistry name ('tianditu' or 'gd_tianditu')
    layer: str           # 'img_c', 'ter_c', 'cia_c', etc.
    projection: str      # 'c' (EPSG:4326) or 'w' (EPSG:3857)
    zoom_range: list     # [min, max] zoom levels
    format: str          # 'png'
    cache_dir: str       # local cache path
    service_id: str      # optional Guangdong thematic service ID (e.g. 'dom2023')
    crs: str             # 'EPSG:4326'
    layer_type: str      # 'dom', 'terrain_visual', 'annotation'
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

from app.modules.schema.types.canonical import BBox
from app.utils.logger import get_logger

from ..contracts import DataResult, DataSourceMetadata
from .base import DataSourceDriver
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("wmts_tile")
class WmtsTileDriver(DataSourceDriver):
    """WMTS tile driver with batch download, cache, and optional mosaic.

    Note: ter_c is terrain hillshade visualization, NOT raw DEM.
    Raw DEM requires LocalRasterDriver or RemoteRasterDriver.
    """

    driver_type = "raster_tile"

    def __init__(self, config: dict[str, Any]):
        self.connection_name = config.get("connection", "")
        self.layer = config.get("layer", "img_c")
        self.projection = config.get("projection", "c")
        self.zoom_range = config.get("zoom_range", [1, 18])
        self.format = config.get("format", "png")
        self.crs = config.get("crs", "EPSG:4326")
        self.layer_type = config.get("layer_type", "dom")
        self.service_id = config.get("service_id")
        self.cache_dir = Path(config.get("cache_dir", "data/cache/tiles"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_connection(self):
        from app.modules.data.connections import ConnectionRegistry

        return ConnectionRegistry.require(self.connection_name)

    def fetch(
        self,
        bbox: Optional[BBox] = None,
        zoom: int = 16,
        mosaic: bool = False,
        **kwargs: Any,
    ) -> DataResult:
        """Download tiles for a bounding box.

        Args:
            bbox: Bounding box (required).
            zoom: Zoom level (1-18).
            mosaic: If True, merge tiles into single GeoTIFF.
            **kwargs: Unused.

        Returns:
            DataResult with tile paths (data_type="tiles") or mosaic
            path (data_type="mosaic").
        """
        if bbox is None:
            return DataResult.fail(error="bbox required for tile fetch")

        if not (self.zoom_range[0] <= zoom <= self.zoom_range[1]):
            return DataResult.fail(
                error=f"zoom {zoom} out of range {self.zoom_range}"
            )

        tiles = self._bbox_to_tiles(bbox, zoom)
        if not tiles:
            return DataResult.fail(error="No tiles in bbox at this zoom")

        logger.info(
            "[WmtsTileDriver] Fetching %d tiles at z=%d for %s",
            len(tiles),
            zoom,
            self.layer,
        )

        conn = self._get_connection()
        downloaded: list[Path] = []
        failed = 0
        for x, y, z in tiles:
            tile_path = self._get_cached_tile(x, y, z)
            if tile_path.exists():
                downloaded.append(tile_path)
                continue

            tile_path = self._download_tile(x, y, z, conn)
            if tile_path:
                downloaded.append(tile_path)
            else:
                failed += 1

        if not downloaded:
            return DataResult.fail(error="No tiles downloaded")

        if failed > 0:
            logger.warning(
                "[WmtsTileDriver] %d/%d tiles failed", failed, len(tiles)
            )

        if mosaic:
            try:
                mosaic_path = self._mosaic_tiles(downloaded, bbox, zoom)
                return DataResult.ok(
                    data=str(mosaic_path),
                    data_type="mosaic",
                    tile_count=len(downloaded),
                    failed_count=failed,
                    zoom=zoom,
                    layer=self.layer,
                    cache_path=str(mosaic_path),
                )
            except Exception as e:
                logger.error("[WmtsTileDriver] Mosaic failed: %s", e)

        return DataResult.ok(
            data=[str(p) for p in downloaded],
            data_type="tiles",
            tile_count=len(downloaded),
            failed_count=failed,
            zoom=zoom,
            layer=self.layer,
        )

    def _bbox_to_tiles(self, bbox: BBox, zoom: int) -> list[tuple[int, int, int]]:
        """Convert bounding box to tile coordinate list."""

        def latlon_to_tile(lat: float, lon: float, z: int) -> tuple[int, int]:
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

    def _download_tile(self, x: int, y: int, z: int, conn: Any) -> Optional[Path]:
        """Download a single tile using the Connection's limiter and session."""
        conn.rate_limiter.wait()

        url = self._build_tile_url(x, y, z, conn)
        if not url:
            return None

        tile_path = self._get_cached_tile(x, y, z)
        tile_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            resp = conn.get_session().get(
                url,
                timeout=conn.timeout,
                headers={
                    "Accept": f"image/{self.format}",
                    "User-Agent": "VillagePlanningAgent/1.0",
                },
            )
            if resp.status_code == 200:
                tile_path.write_bytes(resp.content)
                return tile_path
            logger.warning(
                "[WmtsTileDriver] HTTP %d for tile %d/%d/%d",
                resp.status_code,
                z,
                x,
                y,
            )
        except Exception as e:
            logger.warning("[WmtsTileDriver] Error downloading tile %d/%d/%d: %s", z, x, y, e)

        return None

    def _build_tile_url(self, x: int, y: int, z: int, conn: Any) -> Optional[str]:
        """Build tile URL based on service_id (Guangdong) or layer (national)."""
        if self.service_id:
            # Guangdong thematic tile - needs base_url + token
            from app.modules.data.providers.tianditu.gd_service import (
                GDSpecializedService,
            )

            base_url = getattr(conn, "base_url", "")
            token = getattr(conn, "token", getattr(conn, "api_key", ""))
            if not base_url or not token:
                logger.warning("[WmtsTileDriver] Guangdong tile needs base_url+token on connection")
                return None
            gd = GDSpecializedService(gd_token=token, base_url=base_url)
            return gd.get_wmts_tile_url(self.service_id, x, y, z, self.projection)

        # National Tianditu tile - needs api_key
        from app.modules.data.providers.tianditu.tiles import TileService

        api_key = getattr(conn, "api_key", "")
        tile_service = TileService(api_key)
        return tile_service.get_tile_url(
            layer=self.layer,
            projection=self.projection,
            x=x,
            y=y,
            z=z,
        )

    def _mosaic_tiles(self, tiles: list[Path], bbox: BBox, zoom: int) -> Path:
        """Merge tiles into a single GeoTIFF using rasterio."""
        try:
            import rasterio
            from rasterio.merge import merge
        except ImportError as e:
            raise ImportError(
                "rasterio required for mosaic. Install: pip install rasterio"
            ) from e

        datasets = []
        for p in tiles:
            try:
                ds = rasterio.open(p)
                datasets.append(ds)
            except Exception:
                continue

        if not datasets:
            raise ValueError("No valid tiles to mosaic")

        mosaic_data, mosaic_transform = merge(datasets)

        out_path = (
            self.cache_dir
            / self.layer
            / f"mosaic_z{zoom}_{bbox.west:.4f}_{bbox.south:.4f}.tif"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

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

        for ds in datasets:
            ds.close()

        logger.info("[WmtsTileDriver] Mosaic saved: %s", out_path)
        return out_path

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        return DataSourceMetadata(
            name=f"tianditu_{self.layer}",
            driver="wmts_tile",
            crs=self.crs,
            layer_type=self.layer_type,
        )

    @property
    def supports_bbox_query(self) -> bool:
        return True

    @property
    def is_cached(self) -> bool:
        """Check if any tiles exist in cache."""
        return any(self.cache_dir.iterdir()) if self.cache_dir.exists() else False


__all__ = ["WmtsTileDriver"]
