"""Semantic qualification system for cross-dimension metric comparison.

Solves the "same name, different meaning" problem:
- land_use.construction_area_ha = 30.17 (current observed value)
- settlement_planning.planned_construction_ha = 17.66 (planned target)
- superior_planning.urban_boundary_ha = 30.5 (constraint upper bound)

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


class ValueSemantics(str, Enum):
    CURRENT_OBSERVED = "current_observed"
    PLANNED_TARGET = "planned_target"
    CONSTRAINT_UPPER = "constraint_upper"
    CONSTRAINT_LOWER = "constraint_lower"
    BASELINE_YEAR = "baseline_year"
    PROJECTED = "projected"
    ALLOCATED = "allocated"


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
    for semantics, prefix in SEMANTICS_PREFIX.items():
        if field_name.startswith(prefix):
            return semantics
    return None


class SemanticField:
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
    result: Dict[str, SemanticField] = {}
    for name, field_info in model_cls.model_fields.items():
        for meta in field_info.metadata:
            if isinstance(meta, SemanticField):
                result[name] = meta
                break
    return result


@dataclass(frozen=True)
class FieldRef:
    dimension: str
    field: str
    semantics: ValueSemantics
    unit: str = ""


class MetricConcept(str, Enum):
    CONSTRUCTION_AREA = "construction_area"
    FARMLAND_AREA = "farmland_area"
    ECOLOGICAL_REDLINE = "ecological_redline"
    ECOLOGICAL_AREA = "ecological_area"
    FOREST_COVERAGE = "forest_coverage"
    POPULATION = "population"
    PER_CAPITA_CONSTRUCTION = "per_capita_construction"
    INDUSTRY_AREA = "industry_area"
    HAZARD_POINTS = "hazard_points"
    POWER_CAPACITY = "power_capacity"
    ROAD_LENGTH = "road_length"


CROSS_DIMENSION_METRICS: Dict[MetricConcept, List[FieldRef]] = {
    MetricConcept.CONSTRUCTION_AREA: [
        FieldRef("land_use", "current_construction_ha", ValueSemantics.CURRENT_OBSERVED, "ha"),
        FieldRef("land_use_planning", "planned_construction_ha", ValueSemantics.PLANNED_TARGET, "ha"),
        FieldRef("settlement_planning", "current_construction_ha", ValueSemantics.CURRENT_OBSERVED, "ha"),
        FieldRef("settlement_planning", "planned_construction_ha", ValueSemantics.PLANNED_TARGET, "ha"),
        FieldRef("superior_planning", "max_construction_ha", ValueSemantics.CONSTRAINT_UPPER, "ha"),
    ],
    MetricConcept.FARMLAND_AREA: [
        FieldRef("land_use", "current_farmland_ha", ValueSemantics.CURRENT_OBSERVED, "ha"),
        FieldRef("superior_planning", "min_farmland_protection_ha", ValueSemantics.CONSTRAINT_LOWER, "ha"),
        FieldRef("land_use_planning", "planned_farmland_ha", ValueSemantics.PLANNED_TARGET, "ha"),
    ],
    MetricConcept.ECOLOGICAL_REDLINE: [
        FieldRef("superior_planning", "min_ecological_redline_ha", ValueSemantics.CONSTRAINT_LOWER, "ha"),
        FieldRef("ecological_green", "min_ecological_redline_ha", ValueSemantics.CONSTRAINT_LOWER, "ha"),
        FieldRef("ecological", "min_ecological_redline_ha", ValueSemantics.CONSTRAINT_LOWER, "ha"),
    ],
    MetricConcept.ECOLOGICAL_AREA: [
        FieldRef("land_use", "ecological_area_ha", ValueSemantics.CURRENT_OBSERVED, "ha"),
        FieldRef("land_use_planning", "planned_ecological_ha", ValueSemantics.PLANNED_TARGET, "ha"),
        FieldRef("ecological", "planned_ecological_area_ha", ValueSemantics.PLANNED_TARGET, "ha"),
    ],
    MetricConcept.FOREST_COVERAGE: [
        FieldRef("natural_environment", "forest_coverage_rate", ValueSemantics.CURRENT_OBSERVED, "%"),
        FieldRef("land_use", "forest_coverage_rate", ValueSemantics.CURRENT_OBSERVED, "%"),
    ],
    MetricConcept.POPULATION: [
        FieldRef("socio_economic", "registered_population", ValueSemantics.CURRENT_OBSERVED, "人"),
        FieldRef("socio_economic", "resident_population", ValueSemantics.CURRENT_OBSERVED, "人"),
        FieldRef("settlement_planning", "planned_population", ValueSemantics.PLANNED_TARGET, "人"),
    ],
    MetricConcept.PER_CAPITA_CONSTRUCTION: [
        FieldRef("settlement_planning", "per_capita_construction_sqm", ValueSemantics.CURRENT_OBSERVED, "sqm/人"),
    ],
    MetricConcept.INDUSTRY_AREA: [
        FieldRef("industry", "industry_area_ha", ValueSemantics.CURRENT_OBSERVED, "ha"),
        FieldRef("industry", "planned_industry_area_ha", ValueSemantics.PLANNED_TARGET, "ha"),
        FieldRef("land_use_planning", "planned_industry_ha", ValueSemantics.PLANNED_TARGET, "ha"),
    ],
    MetricConcept.HAZARD_POINTS: [
        FieldRef("natural_environment", "hazard_points_count", ValueSemantics.CURRENT_OBSERVED, "处"),
        FieldRef("disaster_prevention", "hazard_points_count", ValueSemantics.CURRENT_OBSERVED, "处"),
    ],
    MetricConcept.POWER_CAPACITY: [
        FieldRef("infrastructure", "power_capacity_kva", ValueSemantics.CURRENT_OBSERVED, "kVA"),
        FieldRef("infrastructure_planning", "planned_power_capacity_kva", ValueSemantics.PLANNED_TARGET, "kVA"),
    ],
    MetricConcept.ROAD_LENGTH: [
        FieldRef("traffic", "road_network_length_km", ValueSemantics.CURRENT_OBSERVED, "km"),
        FieldRef("traffic_planning", "planned_road_length_km", ValueSemantics.PLANNED_TARGET, "km"),
    ],
}


def get_comparable_fields(
    concept: MetricConcept,
    semantics: ValueSemantics,
) -> List[FieldRef]:
    return [
        ref
        for ref in CROSS_DIMENSION_METRICS.get(concept, [])
        if ref.semantics == semantics
    ]


def get_constraint_fields(
    concept: MetricConcept,
) -> List[FieldRef]:
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
