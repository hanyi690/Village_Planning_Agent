"""Unified data acquisition + session input ingestion adapters.

Folded from the former modules/data package (catalog / sources /
connections / providers / documents / adapters / ingest) and the parsing
modules (gazetteer / tables / schemas / semantics / compiler).

All spatial data (vector / raster / tiles) and non-spatial documents
(planning markdown / L3 reports) enter the system through this package.

Architecture (see README.md):
    Catalog (YAML) -> Source/Driver -> Connection -> Storage & Cache
                                                        |
                                                        v
                                              modules.schema.types.canonical

Key components:
  - upload.py:                Session input file upload handling
  - gazetteer.py:             Place name resolution (Tier 0-2)
  - semantics.py:             MetricConcept + ValueSemantics for conflict detection
  - schemas.py:               Pydantic input/data schemas
  - tables.py:                Structured table detection/extraction (unit-level)
  - spatial_language.py:      Spatial relation language parsing
  - summary_generator.py:     Structured summary generation
  - summary_parser.py:        Structured summary parsing
  - table_schema_inference.py: Table schema inference

Public API:
    DataCatalog            - unified entry point (re-exported lazily)
    DataResult             - result envelope for all fetch operations
    DataSourceDriver       - ABC for data source drivers
    DriverRegistry         - driver auto-discovery registry
    Connection             - ABC for API connections
    ConnectionRegistry     - connection instance registry
"""

from __future__ import annotations

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
from .upload import process_uploaded_file
from . import adapters

__all__ = [
    # Catalog (lazily re-exported)
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
    # Upload
    "process_uploaded_file",
]


def __getattr__(name: str):
    if name == "DataCatalog":
        from ..catalog import DataCatalog

        return DataCatalog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
