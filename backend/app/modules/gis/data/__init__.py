"""GIS data layer - legacy module (Phase 4: superseded by app.modules.data).

New code should import from ``app.modules.data`` directly. This module is
preserved for backward compatibility during migration.

Deep-path imports (gis.data.fetcher, gis.data.providers, gis.data.loader,
gis.data.catalog.loaders) continue to work unchanged.

See: backend/app/modules/data/README.md
"""

from .catalog import DataCatalog
from .drivers import (
    DataSourceDriver,
    DataSourceMetadata,
    DataSourceResult,
    DriverRegistry,
    FileVectorDriver,
    LocalRasterDriver,
    RemoteRasterDriver,
    TiandituTileDriver,
    TiandituVectorDriver,
)
from .fetcher import GISDataFetcher, get_fetcher

__all__ = [
    # Catalog
    "DataCatalog",
    # Drivers
    "DataSourceDriver",
    "DataSourceResult",
    "DataSourceMetadata",
    "DriverRegistry",
    "FileVectorDriver",
    "TiandituVectorDriver",
    "TiandituTileDriver",
    "LocalRasterDriver",
    "RemoteRasterDriver",
    # Legacy
    "GISDataFetcher",
    "get_fetcher",
]
