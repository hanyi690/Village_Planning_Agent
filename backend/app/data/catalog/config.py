"""Pydantic models for data catalog YAML configuration.

Type-validated configuration for connections and data sources.
Supports both v1.0 (sources only) and v2.0 (connections + sources) YAML.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator


class VectorLayerConfig(BaseModel):
    """Layer configuration within a multi-layer vector service."""

    id: int
    name: str = ""
    layer_type: str


class ConnectionConfig(BaseModel):
    """API connection configuration.

    Credentials are referenced by environment variable name and resolved
    at connection instantiation time (Phase 2), not stored in YAML.
    """

    type: str  # 'tianditu' | 'amap' | 'gd_tianditu'
    api_key_env: str = ""  # env var name, e.g. "TIANDITU_API_KEY"
    rate_limit: float = 5.0  # QPS
    timeout: int = 30
    max_retries: int = 3
    base_url: str = ""


class BaseSourceConfig(BaseModel):
    """Base configuration shared by all source types."""

    driver: str
    layer_type: str = ""
    crs: str = "EPSG:4326"
    connection: str = ""  # bind to a named ConnectionConfig entry


class FileVectorSourceConfig(BaseSourceConfig):
    driver: str = "file_vector"
    path: str
    format: str = "geojson"
    encoding: str = "utf-8"


class ApiVectorSourceConfig(BaseSourceConfig):
    driver: str = "api_vector"
    protocol: str = "wfs"  # "wfs" | "mapserver_rest"
    service_id: str = ""
    layer: str = ""
    layers: List[VectorLayerConfig] = Field(default_factory=list)


class WmtsTileSourceConfig(BaseSourceConfig):
    driver: str = "wmts_tile"
    layer: str = "img_c"
    projection: str = "c"
    zoom_range: List[int] = Field(default_factory=lambda: [1, 18])
    format: str = "png"
    cache_dir: str = "data/cache/tiles"


class LocalRasterSourceConfig(BaseSourceConfig):
    driver: str = "local_raster"
    path: str
    format: str = "GeoTIFF"


class RemoteRasterSourceConfig(BaseSourceConfig):
    driver: str = "remote_raster"
    provider: str
    resolution: str = ""
    format: str = "GeoTIFF"
    download_guide: Dict[str, Any] = Field(default_factory=dict)
    local_path: str = ""


class DocumentSourceConfig(BaseSourceConfig):
    driver: str = "document"
    path: str
    doc_type: str = "text"  # "planning_markdown" | "l3_report" | "text" (Markdown only)


class CatalogConfig(BaseModel):
    """Root catalog configuration from YAML."""

    version: str = "1.0"
    connections: Dict[str, ConnectionConfig] = Field(default_factory=dict)
    sources: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, v: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        valid_drivers = {
            "file_vector",
            "api_vector",
            "wmts_tile",
            "local_raster",
            "remote_raster",
            "document",
        }
        for name, cfg in v.items():
            driver = cfg.get("driver", "")
            if driver not in valid_drivers:
                raise ValueError(
                    f"Source '{name}': unknown driver '{driver}'. "
                    f"Valid: {valid_drivers}"
                )
        return v


__all__ = [
    "VectorLayerConfig",
    "ConnectionConfig",
    "BaseSourceConfig",
    "FileVectorSourceConfig",
    "ApiVectorSourceConfig",
    "WmtsTileSourceConfig",
    "LocalRasterSourceConfig",
    "RemoteRasterSourceConfig",
    "DocumentSourceConfig",
    "CatalogConfig",
]
