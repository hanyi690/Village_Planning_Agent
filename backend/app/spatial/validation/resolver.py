"""
Conflict resolver with dimension priority-based resolution.

Resolves conflicts detected by ConflictDetector using:
1. Metric conflicts: take value from highest-priority dimension
2. Constraint violations: flag for adjustment (reduce planned or expand constraint)
3. Spatial conflicts: take structure from highest-priority dimension
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger
from .detector import (
    ConflictReport,
    ConstraintViolation,
    MetricConflict,
    SpatialConflict,
)
from app.data.ingestion.semantics import MetricConcept, ValueSemantics

logger = get_logger(__name__)


# ============================================
# Resolution Data Models
# ============================================

@dataclass
class MetricResolution:
    """Resolution of a metric conflict."""
    concept: MetricConcept
    semantics: ValueSemantics
    winner_dimension: str
    winner_field: str
    winner_value: float
    loser_dimension: str
    loser_field: str
    loser_value: float
    deviation: float
    reason: str

    @property
    def description(self) -> str:
        return (
            f"{self.concept.value}[{self.semantics.value}]: "
            f"adopted {self.winner_dimension}.{self.winner_field}={self.winner_value} "
            f"over {self.loser_dimension}.{self.loser_field}={self.loser_value} "
            f"(deviation={self.deviation:.2f}, reason={self.reason})"
        )


@dataclass
class ConstraintResolution:
    """Resolution of a constraint violation."""
    concept: MetricConcept
    planned_dimension: str
    planned_value: float
    constraint_dimension: str
    constraint_value: float
    constraint_type: ValueSemantics
    action: str  # "adjust_planned" | "flag_for_review"
    adjusted_value: Optional[float] = None

    @property
    def description(self) -> str:
        if self.action == "adjust_planned" and self.adjusted_value is not None:
            return (
                f"{self.concept.value}: adjusted {self.planned_dimension} "
                f"from {self.planned_value} to {self.adjusted_value} "
                f"to satisfy {self.constraint_dimension}={self.constraint_value}"
            )
        return (
            f"{self.concept.value}: {self.planned_dimension}={self.planned_value} "
            f"violates {self.constraint_dimension}={self.constraint_value} "
            f"(flagged for review)"
        )


@dataclass
class SpatialResolution:
    """Resolution of a spatial direction conflict."""
    winner_dimension: str
    winner_structure: str
    loser_dimension: str
    loser_structure: str
    reason: str


@dataclass
class ResolutionReport:
    """Complete conflict resolution results."""
    metric_resolutions: List[MetricResolution] = field(default_factory=list)
    constraint_resolutions: List[ConstraintResolution] = field(default_factory=list)
    spatial_resolutions: List[SpatialResolution] = field(default_factory=list)

    @property
    def resolved_values(self) -> Dict[str, float]:
        """Get all resolved metric values for downstream use."""
        result: Dict[str, float] = {}
        for r in self.metric_resolutions:
            key = f"{r.concept.value}.{r.semantics.value}"
            result[key] = r.winner_value
        return result

    def summary(self) -> str:
        lines = [f"Resolution Report: {len(self.metric_resolutions)} metric, "
                 f"{len(self.constraint_resolutions)} constraint, "
                 f"{len(self.spatial_resolutions)} spatial"]
        for r in self.metric_resolutions:
            lines.append(f"  [Metric] {r.description}")
        for r in self.constraint_resolutions:
            lines.append(f"  [Constraint] {r.description}")
        for r in self.spatial_resolutions:
            lines.append(f"  [Spatial] {r.winner_dimension}({r.winner_structure}) "
                        f"over {r.loser_dimension}({r.loser_structure})")
        return "\n".join(lines)


# ============================================
# Conflict Resolver
# ============================================

class ConflictResolver:
    """Resolve cross-dimension conflicts using dimension priority."""

    # Metric conflict priority (higher = more authoritative)
    METRIC_PRIORITY: Dict[str, int] = {
        "land_use_planning": 10,
        "superior_planning": 9,
        "land_use": 8,
        "socio_economic": 7,
        "settlement_planning": 6,
        "natural_environment": 5,
        "industry": 4,
        "ecological": 3,
    }

    # Spatial conflict priority
    SPATIAL_PRIORITY: Dict[str, int] = {
        "spatial_structure": 10,
        "land_use_planning": 9,
        "ecological": 8,
        "superior_planning": 7,
        "industry": 6,
        "settlement_planning": 5,
    }

    def resolve(self, conflict_report: ConflictReport) -> ResolutionReport:
        """Resolve all detected conflicts.

        Args:
            conflict_report: Output from ConflictDetector.detect_all()

        Returns:
            ResolutionReport with all resolution decisions.
        """
        report = ResolutionReport()
        report.metric_resolutions = self._resolve_metrics(conflict_report.metric_conflicts)
        report.constraint_resolutions = self._resolve_constraints(conflict_report.constraint_violations)
        report.spatial_resolutions = self._resolve_spatial(conflict_report.spatial_conflicts)
        return report

    def _resolve_metrics(
        self,
        conflicts: List[MetricConflict],
    ) -> List[MetricResolution]:
        """Resolve metric conflicts: take highest-priority dimension's value."""
        resolutions: List[MetricResolution] = []

        for conflict in conflicts:
            pri_a = self.METRIC_PRIORITY.get(conflict.dimension_a, 0)
            pri_b = self.METRIC_PRIORITY.get(conflict.dimension_b, 0)

            if pri_a >= pri_b:
                winner_dim, winner_field, winner_val = (
                    conflict.dimension_a, conflict.field_a, conflict.value_a)
                loser_dim, loser_field, loser_val = (
                    conflict.dimension_b, conflict.field_b, conflict.value_b)
            else:
                winner_dim, winner_field, winner_val = (
                    conflict.dimension_b, conflict.field_b, conflict.value_b)
                loser_dim, loser_field, loser_val = (
                    conflict.dimension_a, conflict.field_a, conflict.value_a)

            deviation = abs(winner_val - loser_val)
            reason = (
                f"{winner_dim} (priority={pri_a if pri_a >= pri_b else pri_b}) "
                f"over {loser_dim} (priority={pri_b if pri_a >= pri_b else pri_a})"
            )

            resolutions.append(MetricResolution(
                concept=conflict.concept,
                semantics=conflict.semantics,
                winner_dimension=winner_dim,
                winner_field=winner_field,
                winner_value=winner_val,
                loser_dimension=loser_dim,
                loser_field=loser_field,
                loser_value=loser_val,
                deviation=deviation,
                reason=reason,
            ))
            logger.info(
                f"[ConflictResolver] Metric resolved: {winner_dim}.{winner_field}={winner_val} "
                f"over {loser_dim}.{loser_field}={loser_val} ({reason})"
            )

        return resolutions

    def _resolve_constraints(
        self,
        violations: List[ConstraintViolation],
    ) -> List[ConstraintResolution]:
        """Resolve constraint violations: adjust planned value or flag for review.

        Constraint values always take priority over planned values.
        If planned exceeds constraint upper, reduce to constraint value.
        If planned belows constraint lower, flag for review (rare case).
        """
        resolutions: List[ConstraintResolution] = []

        for violation in violations:
            if violation.constraint_type == ValueSemantics.CONSTRAINT_UPPER:
                # Planned exceeds upper bound: adjust down
                adjusted = violation.constraint_value
                resolutions.append(ConstraintResolution(
                    concept=violation.concept,
                    planned_dimension=violation.planned_dimension,
                    planned_value=violation.planned_value,
                    constraint_dimension=violation.constraint_dimension,
                    constraint_value=violation.constraint_value,
                    constraint_type=violation.constraint_type,
                    action="adjust_planned",
                    adjusted_value=adjusted,
                ))
                logger.info(
                    f"[ConflictResolver] Constraint adjusted: "
                    f"{violation.planned_dimension} from {violation.planned_value} "
                    f"to {adjusted} (upper bound from {violation.constraint_dimension})"
                )
            elif violation.constraint_type == ValueSemantics.CONSTRAINT_LOWER:
                # Planned belows lower bound: flag for review
                resolutions.append(ConstraintResolution(
                    concept=violation.concept,
                    planned_dimension=violation.planned_dimension,
                    planned_value=violation.planned_value,
                    constraint_dimension=violation.constraint_dimension,
                    constraint_value=violation.constraint_value,
                    constraint_type=violation.constraint_type,
                    action="flag_for_review",
                ))
                logger.warning(
                    f"[ConflictResolver] Constraint violation: "
                    f"{violation.planned_dimension}={violation.planned_value} "
                    f"below minimum {violation.constraint_dimension}={violation.constraint_value} "
                    f"(flagged for review)"
                )

        return resolutions

    def _resolve_spatial(
        self,
        conflicts: List[SpatialConflict],
    ) -> List[SpatialResolution]:
        """Resolve spatial conflicts: take highest-priority dimension's structure."""
        resolutions: List[SpatialResolution] = []

        for conflict in conflicts:
            pri_a = self.SPATIAL_PRIORITY.get(conflict.dimension_a, 0)
            pri_b = self.SPATIAL_PRIORITY.get(conflict.dimension_b, 0)

            if pri_a >= pri_b:
                winner_dim, winner_struct = conflict.dimension_a, conflict.structure_a
                loser_dim, loser_struct = conflict.dimension_b, conflict.structure_b
            else:
                winner_dim, winner_struct = conflict.dimension_b, conflict.structure_b
                loser_dim, loser_struct = conflict.dimension_a, conflict.structure_a

            resolutions.append(SpatialResolution(
                winner_dimension=winner_dim,
                winner_structure=winner_struct,
                loser_dimension=loser_dim,
                loser_structure=loser_struct,
                reason=f"Priority: {winner_dim}({max(pri_a, pri_b)}) > {loser_dim}({min(pri_a, pri_b)})",
            ))

        return resolutions


__all__ = [
    "ConflictResolver",
    "ResolutionReport",
    "MetricResolution",
    "ConstraintResolution",
    "SpatialResolution",
]
