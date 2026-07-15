"""
Cross-dimension conflict detector based on semantic qualifiers.

Detects three types of conflicts:
1. Metric conflicts: same concept + same semantics, different values
2. Constraint violations: planned value exceeds constraint bound
3. Spatial direction conflicts: inconsistent spatial structure definitions

Uses CROSS_DIMENSION_METRICS registry to know which fields across
which dimensions represent the same canonical concept, and only
compares fields with matching ValueSemantics.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger
from ...zone_schema import ZONE_TYPE_COLORS
from app.modules.parsing.semantics import (
    CROSS_DIMENSION_METRICS,
    FieldRef,
    MetricConcept,
    ValueSemantics,
    get_comparable_fields,
    get_constraint_fields,
)

logger = get_logger(__name__)

# Threshold for reporting a metric conflict (5% relative difference)
DEFAULT_RELATIVE_THRESHOLD = 0.05


# ============================================
# Conflict Data Models
# ============================================

@dataclass
class MetricConflict:
    """A detected metric value conflict between two dimensions."""
    concept: MetricConcept
    semantics: ValueSemantics
    dimension_a: str
    field_a: str
    value_a: float
    dimension_b: str
    field_b: str
    value_b: float
    relative_diff: float
    unit: str = ""

    @property
    def description(self) -> str:
        return (
            f"{self.concept.value}[{self.semantics.value}]: "
            f"{self.dimension_a}.{self.field_a}={self.value_a} vs "
            f"{self.dimension_b}.{self.field_b}={self.value_b} "
            f"(diff={self.relative_diff:.1%})"
        )


@dataclass
class ConstraintViolation:
    """A planned value that violates a constraint bound."""
    concept: MetricConcept
    planned_dimension: str
    planned_field: str
    planned_value: float
    constraint_dimension: str
    constraint_field: str
    constraint_value: float
    constraint_type: ValueSemantics  # CONSTRAINT_UPPER or CONSTRAINT_LOWER
    unit: str = ""

    @property
    def description(self) -> str:
        direction = "exceeds" if self.constraint_type == ValueSemantics.CONSTRAINT_UPPER else "below"
        return (
            f"{self.concept.value}: {self.planned_dimension}.{self.planned_field}="
            f"{self.planned_value} {direction} {self.constraint_dimension}."
            f"{self.constraint_field}={self.constraint_value}"
        )


@dataclass
class SpatialConflict:
    """A detected spatial direction/structure conflict."""
    dimension_a: str
    structure_a: str  # e.g., "一核一带三区"
    dimension_b: str
    structure_b: str  # e.g., "三心五区"
    detail: str = ""


@dataclass
class ConflictReport:
    """Complete conflict detection results."""
    metric_conflicts: List[MetricConflict] = field(default_factory=list)
    constraint_violations: List[ConstraintViolation] = field(default_factory=list)
    spatial_conflicts: List[SpatialConflict] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.metric_conflicts or self.constraint_violations or self.spatial_conflicts)

    @property
    def total_count(self) -> int:
        return len(self.metric_conflicts) + len(self.constraint_violations) + len(self.spatial_conflicts)

    def summary(self) -> str:
        lines = [f"Conflict Report: {self.total_count} issues found"]
        if self.metric_conflicts:
            lines.append(f"\n  Metric Conflicts ({len(self.metric_conflicts)}):")
            for c in self.metric_conflicts:
                lines.append(f"    - {c.description}")
        if self.constraint_violations:
            lines.append(f"\n  Constraint Violations ({len(self.constraint_violations)}):")
            for v in self.constraint_violations:
                lines.append(f"    - {v.description}")
        if self.spatial_conflicts:
            lines.append(f"\n  Spatial Conflicts ({len(self.spatial_conflicts)}):")
            for s in self.spatial_conflicts:
                lines.append(f"    - {s.dimension_a}: {s.structure_a} vs {s.dimension_b}: {s.structure_b}")
        if not self.has_conflicts:
            lines.append("  No conflicts detected.")
        return "\n".join(lines)


# ============================================
# Conflict Detector
# ============================================

class ConflictDetector:
    """Detect cross-dimension conflicts from dimension report data.

    Uses CROSS_DIMENSION_METRICS registry for semantic-aware comparison.
    Only compares fields with matching ValueSemantics (same concept + same
    semantics = potential conflict; different semantics = constraint check).
    """

    def __init__(self, relative_threshold: float = DEFAULT_RELATIVE_THRESHOLD):
        self.relative_threshold = relative_threshold

    def detect_all(
        self,
        summaries: Dict[str, Dict[str, Any]],
    ) -> ConflictReport:
        """Run all conflict detection on a set of dimension summaries.

        Args:
            summaries: {dimension_key: {"metrics": {...}, "summary": "..."}}

        Returns:
            ConflictReport with all detected conflicts.
        """
        report = ConflictReport()
        report.metric_conflicts = self.detect_metric_conflicts(summaries)
        report.constraint_violations = self.detect_constraint_violations(summaries)
        report.spatial_conflicts = self.detect_spatial_conflicts(summaries)
        return report

    def detect_metric_conflicts(
        self,
        summaries: Dict[str, Dict[str, Any]],
    ) -> List[MetricConflict]:
        """Detect metric value conflicts (same concept + same semantics, different values).

        Only fields with matching ValueSemantics are compared.
        E.g., current_construction_ha in land_use vs settlement_planning.
        """
        conflicts: List[MetricConflict] = []

        for concept, field_refs in CROSS_DIMENSION_METRICS.items():
            # Group by semantics
            by_semantics: Dict[ValueSemantics, List[Tuple[FieldRef, Optional[float]]]] = {}

            for ref in field_refs:
                value = self._get_metric_value(summaries, ref.dimension, ref.field)
                if value is None:
                    continue
                by_semantics.setdefault(ref.semantics, []).append((ref, value))

            # Compare same-semantics values pairwise
            for semantics, entries in by_semantics.items():
                if len(entries) < 2:
                    continue
                for i in range(len(entries)):
                    for j in range(i + 1, len(entries)):
                        ref_a, val_a = entries[i]
                        ref_b, val_b = entries[j]

                        # Compute relative difference
                        if val_a == 0 and val_b == 0:
                            continue
                        denom = max(abs(val_a), abs(val_b))
                        rel_diff = abs(val_a - val_b) / denom if denom > 0 else 0

                        if rel_diff > self.relative_threshold:
                            conflicts.append(MetricConflict(
                                concept=concept,
                                semantics=semantics,
                                dimension_a=ref_a.dimension,
                                field_a=ref_a.field,
                                value_a=val_a,
                                dimension_b=ref_b.dimension,
                                field_b=ref_b.field,
                                value_b=val_b,
                                relative_diff=rel_diff,
                                unit=ref_a.unit,
                            ))
                            logger.info(
                                f"[ConflictDetector] Metric conflict: {concept.value} "
                                f"({ref_a.dimension}={val_a} vs {ref_b.dimension}={val_b}, "
                                f"diff={rel_diff:.1%})"
                            )

        return conflicts

    def detect_constraint_violations(
        self,
        summaries: Dict[str, Dict[str, Any]],
    ) -> List[ConstraintViolation]:
        """Detect constraint violations (planned value exceeds constraint bound).

        Checks:
        - PLANNED_TARGET <= CONSTRAINT_UPPER
        - PLANNED_TARGET >= CONSTRAINT_LOWER
        """
        violations: List[ConstraintViolation] = []

        for concept, field_refs in CROSS_DIMENSION_METRICS.items():
            planned_entries = []
            constraint_entries = []

            for ref in field_refs:
                value = self._get_metric_value(summaries, ref.dimension, ref.field)
                if value is None:
                    continue
                if ref.semantics == ValueSemantics.PLANNED_TARGET:
                    planned_entries.append((ref, value))
                elif ref.semantics in (ValueSemantics.CONSTRAINT_UPPER, ValueSemantics.CONSTRAINT_LOWER):
                    constraint_entries.append((ref, value))

            # Check each planned value against each constraint
            for planned_ref, planned_val in planned_entries:
                for constraint_ref, constraint_val in constraint_entries:
                    violated = False
                    if constraint_ref.semantics == ValueSemantics.CONSTRAINT_UPPER:
                        violated = planned_val > constraint_val
                    elif constraint_ref.semantics == ValueSemantics.CONSTRAINT_LOWER:
                        violated = planned_val < constraint_val

                    if violated:
                        violations.append(ConstraintViolation(
                            concept=concept,
                            planned_dimension=planned_ref.dimension,
                            planned_field=planned_ref.field,
                            planned_value=planned_val,
                            constraint_dimension=constraint_ref.dimension,
                            constraint_field=constraint_ref.field,
                            constraint_value=constraint_val,
                            constraint_type=constraint_ref.semantics,
                            unit=planned_ref.unit,
                        ))
                        logger.info(
                            f"[ConflictDetector] Constraint violation: {concept.value} "
                            f"planned={planned_val} ({planned_ref.dimension}) "
                            f"vs {constraint_ref.semantics.value}={constraint_val} "
                            f"({constraint_ref.dimension})"
                        )

        return violations

    def detect_spatial_conflicts(
        self,
        summaries: Dict[str, Dict[str, Any]],
    ) -> List[SpatialConflict]:
        """Detect spatial structure direction conflicts.

        Compares spatial_structure's structure pattern with industry's
        layout direction to check for inconsistency.
        """
        conflicts: List[SpatialConflict] = []

        # Extract structure patterns from spatial_structure and industry
        spatial_data = summaries.get("spatial_structure", {})
        industry_data = summaries.get("industry", {})

        spatial_pattern = spatial_data.get("metrics", {}).get("structure_pattern", "")
        industry_direction = industry_data.get("metrics", {}).get("layout_direction", "")

        if spatial_pattern and industry_direction:
            # Simple heuristic: if both define structural patterns,
            # check for obvious conflicts (different zone counts, etc.)
            spatial_zones = spatial_data.get("metrics", {}).get("zone_names", [])
            if spatial_zones and industry_direction:
                # If spatial_structure defines zones but industry has a different layout
                # This is a soft conflict - log but don't block
                industry_zone_count = industry_data.get("metrics", {}).get("zone_count", 0)
                spatial_zone_count = len(spatial_zones)
                if industry_zone_count > 0 and spatial_zone_count > 0:
                    if abs(industry_zone_count - spatial_zone_count) >= 2:
                        conflicts.append(SpatialConflict(
                            dimension_a="spatial_structure",
                            structure_a=f"{spatial_pattern} ({spatial_zone_count} zones)",
                            dimension_b="industry",
                            structure_b=f"{industry_direction} ({industry_zone_count} zones)",
                            detail="Zone count mismatch >= 2",
                        ))

        return conflicts

    def _get_metric_value(
        self,
        summaries: Dict[str, Dict[str, Any]],
        dimension: str,
        field_name: str,
    ) -> Optional[float]:
        """Extract a metric value from summaries — supports nested format.

        Accepts both flat {dk: {"metrics": ...}} and nested
        {dk: {"summary": {"metrics": ...}}} formats.
        """
        dim_summary = summaries.get(dimension)
        if not dim_summary:
            return None

        # Nested format: dim_summary.summary.metrics
        summary_obj = dim_summary.get("summary", {})
        metrics = summary_obj.get("metrics") if summary_obj else None
        if metrics is None:
            # Flat format fallback: dim_summary.metrics
            metrics = dim_summary.get("metrics", {})

        val = metrics.get(field_name)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        return None


__all__ = [
    "ConflictDetector",
    "ConflictReport",
    "MetricConflict",
    "ConstraintViolation",
    "SpatialConflict",
]
