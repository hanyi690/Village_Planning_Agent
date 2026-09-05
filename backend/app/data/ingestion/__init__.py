"""DATA ingestion public surface.

The DATA write boundary is ``DataAdmissionFacade``. This package exposes
upload transport handling, source drivers, connection primitives and the
result envelope. Typed Bundle-era ingest/adapters and provider anchor
aggregators are retired and intentionally not re-exported.
"""

from __future__ import annotations

from .connections import Connection, ConnectionRegistry
from .contracts import DataResult, DataSourceMetadata
from .sources import DataSourceDriver, DriverRegistry
from .upload import process_uploaded_file

__all__ = [
    "DataResult",
    "DataSourceMetadata",
    "DataSourceDriver",
    "DriverRegistry",
    "Connection",
    "ConnectionRegistry",
    "process_uploaded_file",
]
