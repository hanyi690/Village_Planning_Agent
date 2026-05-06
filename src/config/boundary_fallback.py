"""
Boundary Fallback Configuration

Defines strategies and parameters for proxy boundary generation
when user-uploaded boundary data is unavailable.

Reference: GIS Planning Visualization Architecture - Boundary Fallback Mechanism
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional

BoundaryStrategy = Literal[
    "user_uploaded",       # User uploaded data (highest priority)
    "isochrone",           # Isochrone boundary from accessibility analysis
    "polygonize_fusion",   # Geometric stitching with road/water lines
    "morphological_convex",# Morphological envelope (convex/concave hull)
    "bbox_buffer",         # bbox buffer rectangle (final fallback)
]


@dataclass
class BoundaryFallbackConfig:
    """Configuration for boundary generation fallback mechanism"""

    # Strategy priority order
    strategy_priority: List[BoundaryStrategy] = field(default_factory=lambda: [
        "user_uploaded",
        "isochrone",
        "polygonize_fusion",
        "morphological_convex",
        "bbox_buffer",
    ])

    # IoU thresholds for quality assessment
    iou_threshold_good: float = 0.3       # Good quality threshold
    iou_threshold_acceptable: float = 0.15  # Acceptable quality threshold

    # Isochrone parameters
    isochrone_time_minutes: int = 15      # 15-minute walking isochrone
    isochrone_travel_mode: str = "walk"   # Walking mode for village context
    isochrone_sample_points: int = 16     # Radial sample points

    # Polygonize Fusion parameters
    polygonize_min_lines: int = 5         # Minimum line features required
    polygonize_min_area_km2: float = 0.1  # Minimum polygon area
    polygonize_extend_lines: bool = True  # Extend lines to boundary

    # Morphological parameters
    morphological_min_features: int = 3   # Minimum features for hull computation
    morphological_alpha: float = 0.5      # Alpha parameter for concave hull
    morphological_use_concave: bool = True  # Prefer concave hull over convex

    # bbox buffer parameters (final fallback)
    bbox_buffer_km: float = 2.0           # Buffer distance in km

    # Flow control
    continue_on_failure: bool = True      # Continue to next strategy on failure
    log_fallback_steps: bool = True       # Log each fallback step

    def get_next_strategy(self, current: BoundaryStrategy) -> Optional[BoundaryStrategy]:
        """Get the next fallback strategy after current"""
        idx = self.strategy_priority.index(current)
        if idx < len(self.strategy_priority) - 1:
            return self.strategy_priority[idx + 1]
        return None

    def is_final_strategy(self, strategy: BoundaryStrategy) -> bool:
        """Check if this is the final fallback strategy"""
        return strategy == self.strategy_priority[-1]


# Default configuration instance
BOUNDARY_FALLBACK_CONFIG = BoundaryFallbackConfig()


__all__ = [
    "BoundaryStrategy",
    "BoundaryFallbackConfig",
    "BOUNDARY_FALLBACK_CONFIG",
]