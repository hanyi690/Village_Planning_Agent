"""
Spatial layout engine - orchestrates the full pipeline.

Phase 0: Conflict detection + resolution only.
Phase 1: + ZoneGenerator (function_zone GeoJSON)
Phase 2: + FacilityPlacer + AxisBuilder + ConstraintSolver
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from .conflict_detector import ConflictDetector, ConflictReport
from .conflict_resolver import ConflictResolver, ResolutionReport

logger = get_logger(__name__)


class SpatialLayoutEngine:
    """Orchestrates the spatial layout generation pipeline.

    Phase 0: Reports → ConflictDetection → ConflictResolution
    Phase 1: + UnifiedIntent → ZoneGenerator → GeoJSON
    Phase 2: + FacilityPlacer + AxisBuilder + ConstraintSolver
    """

    def __init__(self) -> None:
        self.conflict_detector = ConflictDetector()
        self.conflict_resolver = ConflictResolver()

    def detect_and_resolve(
        self,
        summaries: Dict[str, Dict[str, Any]],
    ) -> tuple[ConflictReport, ResolutionReport]:
        """Phase 0: Detect and resolve cross-dimension conflicts.

        Args:
            summaries: {dimension_key: {"metrics": {...}, ...}}

        Returns:
            Tuple of (conflict_report, resolution_report)
        """
        conflict_report = self.conflict_detector.detect_all(summaries)
        resolution_report = self.conflict_resolver.resolve(conflict_report)

        logger.info(
            f"[SpatialLayoutEngine] Phase 0 complete: "
            f"{conflict_report.total_count} conflicts detected, "
            f"{len(resolution_report.metric_resolutions)} metric resolutions, "
            f"{len(resolution_report.constraint_resolutions)} constraint resolutions"
        )

        return conflict_report, resolution_report


__all__ = ["SpatialLayoutEngine"]
