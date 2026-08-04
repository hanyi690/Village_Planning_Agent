"""Deterministic rule-based mapper: PlanningIntervention -> SpatialReferenceSpec.

This mapper bridges L3 planning output to the closed-set spatial reference DSL.
It is fully deterministic: no LLM calls, no KG queries, and no geometry.
Direction hints are extracted from spatial_requirements string values (falling
back to problem_addressed and functions) via direction_from_location().
"""
from __future__ import annotations

from app.modules.parsing.spatial_language import direction_from_location
from app.modules.schema.contracts.l3_contracts import PlanningIntervention
from app.modules.schema.contracts.parse_result_contracts import ParseDiagnostic
from app.modules.schema.contracts.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
)

_DIRECTION_TO_8WIND = {
    "north": "N",
    "south": "S",
    "east": "E",
    "west": "W",
    "northeast": "NE",
    "southeast": "SE",
    "northwest": "NW",
    "southwest": "SW",
}

_ATTR_KEYS = ("dlbm_in", "land_use")
_TOPO_KEYS = ("adjacent_to", "near", "within")


def _direction_from_requirements(intervention: PlanningIntervention) -> str:
    """Return an 8-wind-mappable english direction or '' ('' = none)."""
    for value in intervention.spatial_requirements.values():
        if isinstance(value, str):
            direction = direction_from_location(value)
            if direction in _DIRECTION_TO_8WIND:
                return direction
    for text in [intervention.problem_addressed, *intervention.functions]:
        if isinstance(text, str):
            direction = direction_from_location(text)
            if direction in _DIRECTION_TO_8WIND:
                return direction
    return ""


def _build_candidates(
    intervention: PlanningIntervention,
) -> list[SpatialReferenceSpec]:
    candidates: list[SpatialReferenceSpec] = []

    direction = _direction_from_requirements(intervention)
    if direction:
        candidates.append(
            SpatialReferenceSpec(
                type="directional",
                reference=RefObject(kind="village"),
                direction=_DIRECTION_TO_8WIND[direction],
            )
        )

    for key in _ATTR_KEYS:
        if key not in intervention.spatial_requirements:
            continue
        value = intervention.spatial_requirements[key]
        if key == "dlbm_in" and isinstance(value, list):
            candidates.append(
                SpatialReferenceSpec(type="attributive", attr_filter={"dlbm_in": value})
            )
        elif key == "land_use":
            candidates.append(
                SpatialReferenceSpec(type="attributive", attr_filter={"land_use": value})
            )

    for key in _TOPO_KEYS:
        if key not in intervention.spatial_requirements:
            continue
        value = intervention.spatial_requirements[key]
        if not isinstance(value, str):
            continue
        if key == "within":
            candidates.append(SpatialReferenceSpec(type="topological", topo="sfWithin"))
        else:
            topo = "sfTouches" if key == "adjacent_to" else "nearby"
            candidates.append(
                SpatialReferenceSpec(
                    type="topological",
                    topo=topo,
                    reference=RefObject(
                        kind="entity_type",
                        filter={"label_contains": value},
                    ),
                )
            )

    return candidates


def map_intervention_to_spec(
    intervention: PlanningIntervention,
) -> SpatialReferenceSpec | None:
    """Deterministic rule-based mapping. Returns None if unmappable."""
    candidates = _build_candidates(intervention)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return SpatialReferenceSpec(type="composed", op="and", children=candidates)


def map_interventions_to_specs(
    interventions: list[PlanningIntervention],
) -> tuple[list[SpatialReferenceSpec], list[ParseDiagnostic]]:
    """Batch mapping. Returns (specs, diagnostics) - one diagnostic per unmappable."""
    specs: list[SpatialReferenceSpec] = []
    diagnostics: list[ParseDiagnostic] = []
    for intervention in interventions:
        spec = map_intervention_to_spec(intervention)
        if spec is None:
            diagnostics.append(
                ParseDiagnostic(
                    diagnostic_id=f"spec-{intervention.intervention_id}-ambiguous",
                    severity="warning",
                    code="AMBIGUOUS_REFERENCE",
                    message=(
                        "No spatial reference detected for intervention "
                        f"'{intervention.intervention_id}'"
                    ),
                    field_path=(
                        f"interventions.{intervention.intervention_id}.spatial_requirements"
                    ),
                )
            )
        else:
            specs.append(spec)
    return specs, diagnostics


__all__ = ["_DIRECTION_TO_8WIND", "map_intervention_to_spec", "map_interventions_to_specs"]
