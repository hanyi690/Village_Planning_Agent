"""GIS data catalog package.

Exports DataCatalog, configuration models, and loaders.
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
from .loaders import (
    load_all,
    load_current,
    load_gis_data_full,
    load_planned,
    load_typed_annotations,
    load_typed_roads,
    load_village_data,
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
    # Loaders
    "load_all",
    "load_current",
    "load_planned",
    "load_gis_data_full",
    "load_typed_annotations",
    "load_typed_roads",
    "load_village_data",
]
