"""Pydantic models for data catalog YAML configuration.

Type-validated configuration for all data source types.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class VectorLayerConfig(BaseModel):
    """Layer configuration within a vector service."""

    id: int
    name: str = ""
    layer_type: str


class BaseSourceConfig(BaseModel):
    """Base configuration shared by all source types."""

    driver: str
    layer_type: str = ""
    crs: str = "EPSG:4326"


class FileVectorSourceConfig(BaseSourceConfig):
    """Local vector file source configuration."""

    driver: str = "file_vector"
    path: str
    format: str = "geojson"
    encoding: str = "utf-8"


class TiandituVectorSourceConfig(BaseSourceConfig):
    """Tianditu vector service source configuration."""

    driver: str = "tianditu_vector"
    service_id: str
    protocol: str = "mapserver_rest"
    layers: List[VectorLayerConfig] = Field(default_factory=list)


class TiandituTileSourceConfig(BaseSourceConfig):
    """Tianditu WMTS tile source configuration."""

    driver: str = "tianditu_tile"
    layer: str = "img_c"
    projection: str = "c"
    zoom_range: List[int] = Field(default_factory=lambda: [1, 18])
    format: str = "png"
    cache_dir: str = "data/cache/tiles"


class LocalRasterSourceConfig(BaseSourceConfig):
    """Local raster file source configuration."""

    driver: str = "local_raster"
    path: str
    format: str = "GeoTIFF"


class RemoteRasterSourceConfig(BaseSourceConfig):
    """Remote raster download source configuration."""

    driver: str = "remote_raster"
    provider: str
    resolution: str = ""
    format: str = "GeoTIFF"
    download_guide: Dict[str, Any] = Field(default_factory=dict)
    local_path: str = ""


# Union type for all source configs
SourceConfig = (
    FileVectorSourceConfig
    | TiandituVectorSourceConfig
    | TiandituTileSourceConfig
    | LocalRasterSourceConfig
    | RemoteRasterSourceConfig
)


class CatalogConfig(BaseModel):
    """Root catalog configuration from YAML."""

    version: str = "1.0"
    sources: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, v: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Validate that each source has a recognized driver."""
        valid_drivers = {
            "file_vector",
            "tianditu_vector",
            "tianditu_tile",
            "local_raster",
            "remote_raster",
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
    "BaseSourceConfig",
    "FileVectorSourceConfig",
    "TiandituVectorSourceConfig",
    "TiandituTileSourceConfig",
    "LocalRasterSourceConfig",
    "RemoteRasterSourceConfig",
    "CatalogConfig",
]
