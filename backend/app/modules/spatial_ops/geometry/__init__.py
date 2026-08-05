"""Geometry computation subpackage — pure geometry, relations, subdivision, axes.

Dependency cluster: geometry helpers (centroid/area/near-point), parcel
relations, parcel subdivision, and development-axis generation.
"""
from .geometry import *  # noqa: F401,F403
from .geometry import __all__  # noqa: F401
from .relations import *  # noqa: F401,F403
from .relations import (  # noqa: F401
    _compute_spatial_relations,
    _compute_zone_adjacency,
)
from .subdivision import *  # noqa: F401,F403
from .axis_builder import *  # noqa: F401,F403
