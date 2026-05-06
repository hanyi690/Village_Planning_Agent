"""
Analysis Module - 分析功能模块

整合可达性分析、空间分析和 GIS 分析功能。
"""

from .accessibility import (
    haversine_distance,
    run_accessibility_analysis,
    generate_isochrones,
    calculate_isochrone_coverage,
    analyze_service_area_gap,
    format_accessibility_result,
    format_isochrone_result,
    SERVICE_RADIUS_STANDARDS,
    TRAVEL_SPEEDS,
)

from .spatial_ops import (
    geojson_to_geodataframe,
    geodataframe_to_geojson,
    run_spatial_overlay,
    run_gis_analysis,
    format_gis_result,
)

__all__ = [
    # Accessibility
    'haversine_distance',
    'run_accessibility_analysis',
    'generate_isochrones',
    'calculate_isochrone_coverage',
    'analyze_service_area_gap',
    'format_accessibility_result',
    'format_isochrone_result',
    'SERVICE_RADIUS_STANDARDS',
    'TRAVEL_SPEEDS',
    # Spatial ops
    'geojson_to_geodataframe',
    'geodataframe_to_geojson',
    'run_spatial_overlay',
    'run_gis_analysis',
    'format_gis_result',
]