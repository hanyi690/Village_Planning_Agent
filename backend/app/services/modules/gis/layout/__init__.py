"""Spatial layout generation engine.

Four-stage pipeline:
  Reports → ConflictDetection → ConflictResolution → GeometryGeneration → MapRender
"""

from .engine import SpatialLayoutEngine
from .conflict_detector import ConflictDetector
from .conflict_resolver import ConflictResolver

__all__ = [
    "SpatialLayoutEngine",
    "ConflictDetector",
    "ConflictResolver",
]
