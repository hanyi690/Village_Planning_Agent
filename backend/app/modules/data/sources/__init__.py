"""Data source drivers.

All drivers auto-register via the DriverRegistry decorator. Importing
this package ensures built-in drivers are discovered.

Phase 3 complete: file_vector / api_vector / wmts_tile / local_raster /
remote_raster / document drivers all registered.
"""

from __future__ import annotations

from .api_vector import ApiVectorDriver
from .base import DataSourceDriver
from .document import DocumentDriver
from .file_vector import FileVectorDriver
from .local_raster import LocalRasterDriver
from .registry import DriverRegistry
from .remote_raster import RemoteRasterDriver
from .wmts_tile import WmtsTileDriver

__all__ = [
    "DataSourceDriver",
    "DriverRegistry",
    "FileVectorDriver",
    "ApiVectorDriver",
    "WmtsTileDriver",
    "LocalRasterDriver",
    "RemoteRasterDriver",
    "DocumentDriver",
]
