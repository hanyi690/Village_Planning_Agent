"""Boundary fallback configuration.

Provides the BoundaryFallbackConfig class referenced by SharedGISContext.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BoundaryFallbackConfig:
    """Configuration for proxy boundary generation."""

    default_radius_m: float = 800.0
    min_radius_m: float = 250.0
    max_radius_m: float = 2500.0
    road_buffer_m: float = 30.0
    water_buffer_m: float = 50.0
    simplify_tolerance: float = 0.00005
    min_area_km2: float = 0.05
