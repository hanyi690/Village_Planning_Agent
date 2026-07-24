"""GIS data catalog package.

Exports DataCatalog and configuration models.
"""

from __future__ import annotations

from .catalog import DataCatalog
from .config import (
    BaseSourceConfig,
    CatalogConfig,
    FileVectorSourceConfig,
    LocalRasterSourceConfig,
    RemoteRasterSourceConfig,
    TiandituTileSourceConfig,
    TiandituVectorSourceConfig,
    VectorLayerConfig,
)

__all__ = [
    "DataCatalog",
    "BaseSourceConfig",
    "CatalogConfig",
    "FileVectorSourceConfig",
    "LocalRasterSourceConfig",
    "RemoteRasterSourceConfig",
    "TiandituTileSourceConfig",
    "TiandituVectorSourceConfig",
    "VectorLayerConfig",
]
