"""GIS data source drivers.

All drivers are auto-registered via DriverRegistry decorator.
Import this module to ensure all drivers are discovered.
"""

from __future__ import annotations

# Import to trigger decorator registration
from .base import DataSourceDriver, DataSourceResult, DataSourceMetadata
from .registry import DriverRegistry
from .file_vector_driver import FileVectorDriver
from .tianditu_vector_driver import TiandituVectorDriver
from .tianditu_tile_driver import TiandituTileDriver
from .local_raster_driver import LocalRasterDriver
from .remote_raster_driver import RemoteRasterDriver

__all__ = [
    "DataSourceDriver",
    "DataSourceResult",
    "DataSourceMetadata",
    "DriverRegistry",
    "FileVectorDriver",
    "TiandituVectorDriver",
    "TiandituTileDriver",
    "LocalRasterDriver",
    "RemoteRasterDriver",
]
