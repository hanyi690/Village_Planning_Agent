"""Data catalog package - declarative data source management.

Exports DataCatalog, configuration models. Sources YAML
(``sources.yaml``) is migrated here in Phase 2 from
``gis/data/catalog/sources.yaml``.
"""

from __future__ import annotations

from .catalog import DataCatalog
from .config import (
    ApiVectorSourceConfig,
    BaseSourceConfig,
    CatalogConfig,
    ConnectionConfig,
    DocumentSourceConfig,
    FileVectorSourceConfig,
    LocalRasterSourceConfig,
    RemoteRasterSourceConfig,
    VectorLayerConfig,
    WmtsTileSourceConfig,
)

__all__ = [
    "DataCatalog",
    "ConnectionConfig",
    "VectorLayerConfig",
    "BaseSourceConfig",
    "FileVectorSourceConfig",
    "ApiVectorSourceConfig",
    "WmtsTileSourceConfig",
    "LocalRasterSourceConfig",
    "RemoteRasterSourceConfig",
    "DocumentSourceConfig",
    "CatalogConfig",
]
