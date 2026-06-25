"""
Semantic qualification system for cross-dimension metric comparison.

Solves the "same name, different meaning" problem:
- land_use.construction_area_ha = 30.17 (current observed value)
- settlement_planning.planned_construction_ha = 17.66 (planned target)
- superior_planning.urban_boundary_ha = 30.5 (constraint upper bound)

These are fundamentally different values despite similar field names.
Direct comparison produces false conflicts; semantic qualifiers prevent this.

Three-layer architecture:
  Layer 1: ValueSemantics enum + naming convention (current_/planned_/max_/min_/...)
  Layer 2: SemanticField Annotated metadata on Pydantic model fields
  Layer 3: CROSS_DIMENSION_METRICS registry for cross-dimension field mapping
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel


# ============================================
# Layer 1: ValueSemantics Enum + Naming Convention
# ============================================

class ValueSemantics(str, Enum):
    """Semantic qualifier for numeric metric values.

    Every cross-dimension comparable numeric field MUST be prefixed
    according to its semantics:
        CURRENT_OBSERVED -> current_
        PLANNED_TARGET   -> planned_
        CONSTRAINT_UPPER -> max_
        CONSTRAINT_LOWER -> min_
        BASELINE_YEAR    -> baseline_
        PROJECTED        -> projected_
        ALLOCATED        -> allocated_
    """
    CURRENT_OBSERVED = "current_observed"
    PLANNED_TARGET = "planned_target"
    CONSTRAINT_UPPER = "constraint_upper"
    CONSTRAINT_LOWER = "constraint_lower"
    BASELINE_YEAR = "baseline_year"
    PROJECTED = "projected"
    ALLOCATED = "allocated"


# Naming convention mapping: semantics -> field prefix
SEMANTICS_PREFIX: Dict[ValueSemantics, str] = {
    ValueSemantics.CURRENT_OBSERVED: "current_",
    ValueSemantics.PLANNED_TARGET: "planned_",
    ValueSemantics.CONSTRAINT_UPPER: "max_",
    ValueSemantics.CONSTRAINT_LOWER: "min_",
    ValueSemantics.BASELINE_YEAR: "baseline_",
    ValueSemantics.PROJECTED: "projected_",
    ValueSemantics.ALLOCATED: "allocated_",
}


def infer_semantics_from_field_name(field_name: str) -> Optional[ValueSemantics]:
    """Infer ValueSemantics from field name prefix.

    Returns None for fields without a recognized qualifier prefix.
    """
    for semantics, prefix in SEMANTICS_PREFIX.items():
        if field_name.startswith(prefix):
            return semantics
    return None


# ============================================
# Layer 2: SemanticField Annotated Metadata
# ============================================

class SemanticField:
    """Metadata marker for field semantic context.

    Attach to Pydantic fields via Annotated:

        class MySummary(BaseDimensionSummary):
            current_construction_ha: Annotated[
                Optional[float],
                SemanticField(ValueSemantics.CURRENT_OBSERVED, "ha", "三调", True),
                Field(default=None, description="...")
            ]
    """

    def __init__(
        self,
        semantics: ValueSemantics,
        unit: str = "",
        data_source: str = "",
        comparable: bool = True,
    ):
        self.semantics = semantics
        self.unit = unit
        self.data_source = data_source
        self.comparable = comparable

    def __repr__(self) -> str:
        return (
            f"SemanticField(semantics={self.semantics.value!r}, "
            f"unit={self.unit!r}, data_source={self.data_source!r}, "
            f"comparable={self.comparable})"
        )


def get_field_semantics(
    model_cls: Type[BaseModel], field_name: str
) -> Optional[SemanticField]:
    """Extract SemanticField from a Pydantic model field's metadata."""
    field_info = model_cls.model_fields.get(field_name)
    if not field_info:
        return None
    for meta in field_info.metadata:
        if isinstance(meta, SemanticField):
            return meta
    return None


def get_all_semantic_fields(
    model_cls: Type[BaseModel],
) -> Dict[str, SemanticField]:
    """Extract all SemanticField-annotated fields from a Pydantic model."""
    result: Dict[str, SemanticField] = {}
    for name, field_info in model_cls.model_fields.items():
        for meta in field_info.metadata:
            if isinstance(meta, SemanticField):
                result[name] = meta
                break
    return result


# ============================================
# Layer 3: Cross-Dimension Metric Registry
# ============================================

@dataclass(frozen=True)
class FieldRef:
    """Reference to a specific field in a specific dimension."""
    dimension: str
    field: str
    semantics: ValueSemantics
    unit: str = ""


class MetricConcept(str, Enum):
    """Canonical metric concepts that appear across multiple dimensions."""
    CONSTRUCTION_AREA = "construction_area"
    FARMLAND_AREA = "farmland_area"
    ECOLOGICAL_REDLINE = "ecological_redline"
    FOREST_COVERAGE = "forest_coverage"
    POPULATION = "population"
    PER_CAPITA_CONSTRUCTION = "per_capita_construction"


CROSS_DIMENSION_METRICS: Dict[MetricConcept, List[FieldRef]] = {
    MetricConcept.CONSTRUCTION_AREA: [
        FieldRef("land_use", "current_construction_ha", ValueSemantics.CURRENT_OBSERVED, "ha"),
        FieldRef(
            "land_use_planning", "planned_construction_ha",
            ValueSemantics.PLANNED_TARGET, "ha",
        ),
        FieldRef(
            "settlement_planning", "current_construction_ha",
            ValueSemantics.CURRENT_OBSERVED, "ha",
        ),
        FieldRef(
            "settlement_planning", "planned_construction_ha",
            ValueSemantics.PLANNED_TARGET, "ha",
        ),
        FieldRef(
            "development_goals", "construction_land_target_ha",
            ValueSemantics.CONSTRAINT_UPPER, "ha",
        ),
    ],
    MetricConcept.FARMLAND_AREA: [
        FieldRef("land_use", "current_farmland_ha", ValueSemantics.CURRENT_OBSERVED, "ha"),
        FieldRef(
            "superior_planning", "min_farmland_protection_ha",
            ValueSemantics.CONSTRAINT_LOWER, "ha",
        ),
        FieldRef(
            "land_use_planning", "planned_farmland_ha",
            ValueSemantics.PLANNED_TARGET, "ha",
        ),
    ],
    MetricConcept.ECOLOGICAL_REDLINE: [
        FieldRef(
            "superior_planning", "min_ecological_redline_ha",
            ValueSemantics.CONSTRAINT_LOWER, "ha",
        ),
        FieldRef(
            "ecological_green", "min_ecological_redline_ha",
            ValueSemantics.CONSTRAINT_LOWER, "ha",
        ),
        FieldRef(
            "ecological", "min_ecological_redline_ha",
            ValueSemantics.CONSTRAINT_LOWER, "ha",
        ),
    ],
    MetricConcept.FOREST_COVERAGE: [
        FieldRef(
            "natural_environment", "forest_coverage_rate",
            ValueSemantics.CURRENT_OBSERVED, "%",
        ),
        FieldRef("land_use", "forest_coverage_rate", ValueSemantics.CURRENT_OBSERVED, "%"),
    ],
    MetricConcept.POPULATION: [
        FieldRef(
            "socio_economic", "registered_population",
            ValueSemantics.CURRENT_OBSERVED, "人",
        ),
        FieldRef(
            "settlement_planning", "planned_population",
            ValueSemantics.PLANNED_TARGET, "人",
        ),
    ],
    MetricConcept.PER_CAPITA_CONSTRUCTION: [
        FieldRef(
            "settlement_planning", "per_capita_construction_sqm",
            ValueSemantics.CURRENT_OBSERVED, "sqm/人",
        ),
    ],
}


def get_comparable_fields(
    concept: MetricConcept,
    semantics: ValueSemantics,
) -> List[FieldRef]:
    """Get all fields for a concept that share the same semantics.

    Only same-semantics fields should be compared for consistency.
    Cross-semantics comparisons are constraint validations, not conflicts.
    """
    return [
        ref
        for ref in CROSS_DIMENSION_METRICS.get(concept, [])
        if ref.semantics == semantics
    ]


def get_constraint_fields(
    concept: MetricConcept,
) -> List[FieldRef]:
    """Get constraint-type fields (upper/lower bounds) for a concept."""
    return [
        ref
        for ref in CROSS_DIMENSION_METRICS.get(concept, [])
        if ref.semantics in (ValueSemantics.CONSTRAINT_UPPER, ValueSemantics.CONSTRAINT_LOWER)
    ]


__all__ = [
    "ValueSemantics",
    "SEMANTICS_PREFIX",
    "SemanticField",
    "get_field_semantics",
    "get_all_semantic_fields",
    "infer_semantics_from_field_name",
    "FieldRef",
    "MetricConcept",
    "CROSS_DIMENSION_METRICS",
    "get_comparable_fields",
    "get_constraint_fields",
]
