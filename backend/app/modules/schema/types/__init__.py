"""Spatial feature types — Group A~F type definitions and canonical containers."""

from .base import *  # noqa: F401,F403  # SpatialFeature, PointFeature, LineFeature, PolygonFeature, RasterDataset
from .spatial_types import *  # noqa: F401,F403
from .canonical import *  # noqa: F401,F403
from .raster_types import *  # noqa: F401,F403
from .table_types import *  # noqa: F401,F403
from .document_types import *  # noqa: F401,F403
from .layer_registry import (  # noqa: F401
    GIS_LAYER_REGISTRY, GisLayerTypeEntry, register_gis_layer_type,
    get_gis_layer_entry, get_all_gis_layer_types,
)
