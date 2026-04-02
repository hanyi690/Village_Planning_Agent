"""
地理编码模块

提供天地图地理编码、行政区划边界服务和扩展服务。
"""

from .base_provider import BaseGeocodingProvider, GeocodingResult, ProviderName
from .tianditu_provider import TiandituGeocodingProvider
from .tianditu_boundary import (
    TiandituBoundaryService,
    BoundaryResult,
    get_boundary_service,
)
from .tianditu_extended import (
    TiandituExtendedService,
    ReverseGeocodeResult,
    POIResult,
    WFSResult,
    RouteResult,
    RouteType,
    WFSLayerType,
    get_extended_service,
)

__all__ = [
    "BaseGeocodingProvider",
    "GeocodingResult",
    "ProviderName",
    "TiandituGeocodingProvider",
    "TiandituBoundaryService",
    "BoundaryResult",
    "get_boundary_service",
    "TiandituExtendedService",
    "ReverseGeocodeResult",
    "POIResult",
    "WFSResult",
    "RouteResult",
    "RouteType",
    "WFSLayerType",
    "get_extended_service",
]