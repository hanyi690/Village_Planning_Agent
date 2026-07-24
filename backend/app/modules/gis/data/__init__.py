"""GIS data fetching and loading.

Unified data access layer:
  - drivers: DataSourceDriver implementations
  - catalog: DataCatalog with YAML configuration
  - providers: Low-level API wrappers (legacy)
  - loader: File-based data loading (legacy)
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
