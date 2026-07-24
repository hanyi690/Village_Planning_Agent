"""GIS Provider abstract base class.

All GIS data providers MUST implement this interface. The base class enforces:
1. CRS normalization — all outputs in WGS84 (EPSG:4326)
2. Type coercion — raw API responses normalized to canonical Pydantic models
3. Error handling — GeoProviderResult envelope with success/failure metadata
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.modules.schema.types.canonical import BBox, GeoFeature, ProviderLandParcel


@dataclass
class GeoProviderResult:
    """Standardized result envelope for all provider operations.

    Every provider method returns this type, never throws.
    Caller checks .success before accessing .data.
    """

    success: bool
    data: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @classmethod
    def ok(cls, data: Any, **metadata) -> "GeoProviderResult":
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata) -> "GeoProviderResult":
        return cls(success=False, error=error, metadata=metadata)


class GISProvider(ABC):
    """Abstract base for all GIS data providers.

    Responsibilities:
      1. Fetch raw data from external API
      2. Normalize CRS to WGS84 (EPSG:4326)
      3. Coerce fields to canonical model types (GeoFeature, ProviderLandParcel)
      4. Return GeoProviderResult envelope (never throw)

    Implementations:
      - TiandituProvider: EPSG:4527 (Gauss-Kruger) → WGS84
      - AmapProvider: GCJ02 → WGS84
      - OSMProvider: already WGS84, no conversion needed
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier: 'tianditu', 'amap', 'osm'."""
        ...

    @abstractmethod
    async def fetch_landuse(self, bbox: BBox) -> GeoProviderResult:
        """Fetch land use parcels within bbox → List[ProviderLandParcel].

        CRS: input bbox is WGS84, provider handles internal CRS conversion.
        Output: all ProviderLandParcel geometries in WGS84.
        DLBM codes resolved via EncodingRegistry.
        """
        ...

    @abstractmethod
    async def fetch_boundary(self, village_name: str) -> GeoProviderResult:
        """Fetch village administrative boundary → GeoFeature (WGS84)."""
        ...

    @abstractmethod
    async def fetch_roads(self, bbox: BBox) -> GeoProviderResult:
        """Fetch road network within bbox → List[GeoFeature] (WGS84)."""
        ...

    @abstractmethod
    async def fetch_water_bodies(self, bbox: BBox) -> GeoProviderResult:
        """Fetch water features within bbox → List[GeoFeature] (WGS84)."""
        ...

    def is_available(self) -> bool:
        """Check if provider is configured and reachable."""
        return True


__all__ = ["GeoProviderResult", "GISProvider"]
