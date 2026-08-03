"""Spatial Ops module — spatial computation utilities.

Peer module alongside Schema and Data in the four-layer architecture:
    Schema <- Data <- SpatialOps <- KG <- Agent

Provides compute_context_blocks() and supporting geometry/relation helpers.
Depends on: Schema types, app.utils (geojson_utils, area_engine, crs_engine).
Does NOT depend on: Agent, KG, Tools.

[v4.3] Monolithic SpatialContext replaced by modular ContextBlock architecture.
compute_context_blocks(VillageBundle) is the sole public entry point.

[v4.7] Added grounding.py (Responsibility B: PARSE spatial grounding).
[v5.0] Added constraint_compiler.py (Responsibility D: constraint compilation).
[v5.0] Added parcel_ops.py (Responsibility E: parcel geometry operations).
[v5.0] Added road_planner.py (Responsibility F: planned road network generation).
[v5.0] Added land_balance.py (Responsibility G: land balance table + delivery gate).
[v5.1] Added map_layers.py (pure frontend layer contract conversion).
[v5.1] Added export_package.py (validated session output packaging).
"""

from .bridge import (
    SpatialIndex, OverlapResult, build_spatial_index,
    ConstraintIndex, ConstraintOverlap, build_constraint_index,
)
from .constraint_compiler import ConstraintCompiler
from .context import compute_context_blocks
from .bundle_binder import DeterministicBundleBinder, bind_exploration_to_bundle

# Backward compat alias: compute_spatial_context → compute_context_blocks
compute_spatial_context = compute_context_blocks
from .grounding import (
    ZoneSpatialAnchor,
    resolve_directional_bbox,
    query_parcels_in_bbox,
    query_parcels_near_entity,
    query_excluded_parcels,
    compute_proximity_weights,
    compute_target_area,
    ground_zone_spatial_preference,
)
from .land_balance import check_delivery_gate, compute_land_balance
from .parcel_ops import (
    apply_operations,
    create_parcel,
    merge_parcels,
    modify_parcel,
    reclassify_parcel,
    split_parcel_by_geometry,
    split_parcel_by_ratio,
)
from .road_planner import plan_roads

__all__ = [
    "compute_context_blocks",
    "compute_spatial_context",
    "SpatialIndex",
    "OverlapResult",
    "build_spatial_index",
    "ConstraintIndex",
    "ConstraintOverlap",
    "build_constraint_index",
    "ConstraintCompiler",
    "DeterministicBundleBinder",
    "bind_exploration_to_bundle",
    # grounding.py exports
    "ZoneSpatialAnchor",
    "resolve_directional_bbox",
    "query_parcels_in_bbox",
    "query_parcels_near_entity",
    "query_excluded_parcels",
    "compute_proximity_weights",
    "compute_target_area",
    "ground_zone_spatial_preference",
    # parcel_ops.py exports
    "reclassify_parcel",
    "modify_parcel",
    "merge_parcels",
    "split_parcel_by_ratio",
    "split_parcel_by_geometry",
    "create_parcel",
    "apply_operations",
    # road_planner.py exports
    "plan_roads",
    # land_balance.py exports
    "compute_land_balance",
    "check_delivery_gate",
]
