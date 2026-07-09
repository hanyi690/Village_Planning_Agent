"""Legacy compatibility wrapper."""

from app.services.modules.gis.spatial_analysis import calculate_buffer_zones, geojson_to_geodataframe, run_spatial_query

__all__ = ["calculate_buffer_zones", "geojson_to_geodataframe", "run_spatial_query"]
