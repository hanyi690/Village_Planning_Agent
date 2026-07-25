"""Spatial Ops module — spatial computation utilities.

Peer module alongside Schema and Data in the four-layer architecture:
    Schema <- Data <- SpatialOps <- KG <- Agent

Provides compute_spatial_context() and supporting geometry/relation helpers.
Depends on: Schema types, app.utils (geojson_utils, area_engine, crs_engine).
Does NOT depend on: Agent, KG, Tools.
"""

from .context import compute_spatial_context, compute_spatial_context_from_bundle

__all__ = ["compute_spatial_context", "compute_spatial_context_from_bundle"]
