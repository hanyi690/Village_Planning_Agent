"""
File Processing Utilities - 文件处理工具模块

提供文档加载、文件类型检测、PDF 解析等基础设施。
"""

from .document_loader import (
    FileTypeDetector,
    MarkItDownLoader,
    MarkdownCleaner,
    DocToDocxConverter,
    classify_file_type,
    load_documents_from_directory,
    _create_loader,
)

from .mineru_loader import MinerULoader
from .docling_loader import DoclingLoader

from .pdf_fallback import (
    PDFFallbackParser,
    PyPDF2Extractor,
    pdfplumberExtractor,
    parse_pdf_with_fallback,
)

# ── Spatial/GIS utils (migrated from modules/gis/utils/) ──
from .geo_utils import haversine_distance, calculate_area_km2, calculate_areas_batch, safe_unary_union, safe_geo_series_union
from .geojson_utils import geojson_to_geodataframe, geodataframe_to_geojson, build_parcel_index
from .coord_utils import ensure_tuple_coord
from .crs_engine import (
    get_metric_crs,
    project_to_metric,
    project_to_wgs84,
    project_geometry,
    project_geometries_batch,
    meters_to_degrees_lon,
    meters_to_degrees_lat,
    degrees_to_meters_lon,
    degrees_to_meters_lat,
)
from .area_engine import (
    calculate_area_ha,
    calculate_areas_batch_ha,
    calculate_areas_batch_km2,
)
from .coord_transform import (
    gcj02_to_wgs84,
    wgs84_to_gcj02,
    gcj02_to_wgs84_batch,
    wgs84_to_gcj02_batch,
    cgcs2000_to_wgs84,
    wgs84_to_cgcs2000,
)

__all__ = [
    "FileTypeDetector",
    "MarkItDownLoader",
    "MinerULoader",
    "DoclingLoader",
    "MarkdownCleaner",
    "DocToDocxConverter",
    "classify_file_type",
    "load_documents_from_directory",
    "_create_loader",
    "PDFFallbackParser",
    "PyPDF2Extractor",
    "pdfplumberExtractor",
    "parse_pdf_with_fallback",
    # geo_utils
    "haversine_distance",
    "calculate_area_km2",
    "calculate_areas_batch",
    "safe_unary_union",
    "safe_geo_series_union",
    # geojson_utils
    "geojson_to_geodataframe",
    "geodataframe_to_geojson",
    "build_parcel_index",
    # coord_utils
    "ensure_tuple_coord",
    # crs_engine
    "get_metric_crs",
    "project_to_metric",
    "project_to_wgs84",
    "project_geometry",
    "project_geometries_batch",
    "meters_to_degrees_lon",
    "meters_to_degrees_lat",
    "degrees_to_meters_lon",
    "degrees_to_meters_lat",
    # area_engine
    "calculate_area_ha",
    "calculate_areas_batch_ha",
    "calculate_areas_batch_km2",
    # coord_transform
    "gcj02_to_wgs84",
    "wgs84_to_gcj02",
    "gcj02_to_wgs84_batch",
    "wgs84_to_gcj02_batch",
    "cgcs2000_to_wgs84",
    "wgs84_to_cgcs2000",
]
