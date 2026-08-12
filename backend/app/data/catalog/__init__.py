"""Catalog package owned by the data layer.

Declarative data source management (sources.yaml) plus the session
collection registry. Sources YAML (``sources.yaml``) lives here.
"""

from __future__ import annotations

from .catalog import DataCatalog
from .collection_registry import CollectionRecord, CollectionRegistry
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
    "CollectionRecord",
    "CollectionRegistry",
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
