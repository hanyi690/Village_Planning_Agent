"""Spatial Ops module — spatial computation utilities.

Peer module alongside Schema and Data in the four-layer architecture:
    Schema <- Data <- SpatialOps <- KG <- Agent

Provides compute_context_blocks() and supporting geometry/relation helpers.
Depends on: Schema types, app.utils (geojson_utils, area_engine, crs_engine).
Does NOT depend on: Agent, KG, Tools.

[v4.3] Monolithic SpatialContext replaced by modular ContextBlock architecture.
compute_context_blocks(VillageBundle) is the sole public entry point.
"""

from .bridge import SpatialIndex, OverlapResult, build_spatial_index
from .context import compute_context_blocks

__all__ = [
    "compute_context_blocks",
    "SpatialIndex",
    "OverlapResult",
    "build_spatial_index",
]
