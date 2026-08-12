"""Datasource module - unified data acquisition and management layer.

All spatial data (vector / raster / tiles) and non-spatial documents
(planning markdown / L3 reports) enter the system through this module.

Architecture (see README.md):
    Catalog (YAML) -> Source/Driver -> Connection -> Storage & Cache
                                                        |
                                                        v
                                              modules.schema.types.canonical

Public API:
    DataCatalog            - unified entry point
    DataResult             - result envelope for all fetch operations
    DataSourceDriver       - ABC for data source drivers
    DriverRegistry         - driver auto-discovery registry
    Connection             - ABC for API connections
    ConnectionRegistry     - connection instance registry
"""

from __future__ import annotations

from .catalog import DataCatalog
from .connections import Connection, ConnectionRegistry
from .contracts import DataResult, DataSourceMetadata
from .ingest import (
    ingest_current_landuse,
    ingest_feature,
    ingest_landuse,
    ingest_planned_landuse,
    ingest_raster,
    provider_to_parcel,
    result_to_features,
    result_to_parcels,
    result_to_raster,
)
from .sources import DataSourceDriver, DriverRegistry
from . import adapters

__all__ = [
    # Catalog
    "DataCatalog",
    # Contracts
    "DataResult",
    "DataSourceMetadata",
    # Ingest (raw -> typed schema models)
    "ingest_landuse",
    "ingest_current_landuse",
    "ingest_planned_landuse",
    "ingest_feature",
    "ingest_raster",
    "provider_to_parcel",
    "result_to_parcels",
    "result_to_features",
    "result_to_raster",
    # Sources
    "DataSourceDriver",
    "DriverRegistry",
    # Connections
    "Connection",
    "ConnectionRegistry",
    # Adapters
    "adapters",
]
