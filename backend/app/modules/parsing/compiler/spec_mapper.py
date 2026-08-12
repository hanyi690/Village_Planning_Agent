"""Deterministic rule-based mapper: PlanningIntervention -> SpatialReferenceSpec.

This mapper bridges L3 planning output to the closed-set spatial reference DSL.
It is fully deterministic: no LLM calls, no KG queries, and no geometry.
Direction hints are extracted from spatial_requirements string values (falling
back to problem_addressed and functions) via direction_from_location().
"""
from __future__ import annotations

import re

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
_UNKNOWN_LOCATIONS = frozenset({"", "待定", "待补充", "待 GIS 校核", "待GIS校核", "无"})
_VILLAGE_SCOPE_LOCATIONS = frozenset({
    "全村", "村域", "村域范围", "各自然村", "各村", "各组", "各村民小组",
})


def _explicit_village_names(intervention: PlanningIntervention) -> list[str]:
    """Extract only a village name explicitly present in the model text.

    This is a textual reference, not a coordinate guess. Generic phrases
    such as ``全村`` are ignored because they do not identify a GIS entity.
    """
    text = " ".join([
        str(intervention.spatial_requirements.get("location") or ""),
        intervention.name,
        intervention.problem_addressed,
        *intervention.functions,
    ])
    # Prefer the closed-set natural-village names produced by KG enrichment.
    # This prevents a greedy regex from turning phrases such as
    # “主要功能为村庄服务” into a fake place name.
    try:
        from app.modules.parsing.natural_villages import _KNOWN_NATURAL_VILLAGES

        matches = [
            (text.find(village), village)
            for village in _KNOWN_NATURAL_VILLAGES
            if village in text
        ]
        if matches:
            return [
                village if village.endswith("村") else village + "村"
                for _, village in sorted(matches, key=lambda item: item[0])
            ]
    except Exception:
        pass

    # Conservative fallback for a root-village name explicitly delimited by
    # punctuation/whitespace. Never infer from an arbitrary long Chinese span.
    match = re.search(r"(?:^|[，。；：、\s(（])([\u4e00-\u9fff]{2,4}村)(?=$|[，。；：、\s)）])", text)
    if match and match.group(1) not in {"全村", "村庄", "村域"}:
        return [match.group(1)]
    return []


def _location_reference(intervention: PlanningIntervention) -> SpatialReferenceSpec | None:
    """Map the source-backed INSTRUCTION location cell without inventing a site."""
    requirements = intervention.spatial_requirements
    location_value = requirements.get("location")
    if not location_value:
        hints = requirements.get("location_hints")
        if isinstance(hints, list):
            location_value = "、".join(str(item).strip() for item in hints if str(item).strip())
    location = str(location_value or "").strip()
    if location in _UNKNOWN_LOCATIONS:
        return None
    normalized = re.sub(r"[\s，,、；;及和与]+", "", location)
    if normalized in _VILLAGE_SCOPE_LOCATIONS or any(
        token in location for token in ("全村范围", "村域内", "全域", "各自然村")
    ):
        return SpatialReferenceSpec(
            type="topological",
            topo="sfWithin",
            reference=RefObject(kind="village"),
        )

    village_names = _explicit_village_names(intervention)
    if len(village_names) > 1:
        return SpatialReferenceSpec(
            type="composed",
            op="or",
            children=[
                SpatialReferenceSpec(
                    type="topological",
                    topo="nearby",
                    reference=RefObject(
                        kind="place_name",
                        filter={"label_contains": village_name},
                    ),
                )
                for village_name in village_names
            ],
        )
    label = village_names[0] if village_names else location
    return SpatialReferenceSpec(
        type="topological",
        topo="nearby",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": label},
        ),
    )


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

    location_ref = _location_reference(intervention)
    if location_ref is not None:
        candidates.append(location_ref)

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

    # Real L3 prose occasionally contains an explicit village name but omits
    # the private INSTRUCTION table. Preserve that textual reference so the
    # normal resolver can locate the corresponding GIS feature. Do not invent
    # a location when the prose contains no named village.
    return candidates


def map_intervention_to_spec(
    intervention: PlanningIntervention,
) -> SpatialReferenceSpec | None:
    """Deterministically map a spatial intervention to one linked spec."""
    if intervention.execution_mode == "non_spatial":
        return None
    candidates = _build_candidates(intervention)
    if not candidates:
        return SpatialReferenceSpec(
            type="composed",
            op="and",
            intervention_id=intervention.intervention_id,
            target_id=intervention.target_id,
            spec_id=f"spatial-ref:{intervention.target_id}",
            project_ref=intervention.intervention_id,
            unresolved_reason="missing_location_evidence",
        )
    if len(candidates) == 1:
        spec = candidates[0]
        spec.intervention_id = intervention.intervention_id
        spec.target_id = intervention.target_id
        spec.spec_id = f"spatial-ref:{intervention.target_id}"
        spec.project_ref = intervention.intervention_id
        return spec
    spec = SpatialReferenceSpec(type="composed", op="and", children=candidates)
    spec.intervention_id = intervention.intervention_id
    spec.target_id = intervention.target_id
    spec.spec_id = f"spatial-ref:{intervention.target_id}"
    spec.project_ref = intervention.intervention_id
    return spec


def map_interventions_to_specs(
    interventions: list[PlanningIntervention],
) -> tuple[list[SpatialReferenceSpec], list[ParseDiagnostic]]:
    """Batch map targets while retaining unresolved spatial requirements."""
    specs: list[SpatialReferenceSpec] = []
    diagnostics: list[ParseDiagnostic] = []
    for intervention in interventions:
        spec = map_intervention_to_spec(intervention)
        if spec is None:
            continue
        else:
            spec.intervention_id = intervention.intervention_id
            spec.target_id = intervention.target_id
            spec.spec_id = f"spatial-ref:{intervention.target_id}"
            spec.project_ref = intervention.intervention_id
            specs.append(spec)
            if spec.unresolved_reason:
                diagnostics.append(
                    ParseDiagnostic(
                        diagnostic_id=f"spec-{intervention.target_id}-unresolved",
                        severity="warning",
                        code="UNRESOLVED_SPATIAL_REFERENCE",
                        message=(
                            "Spatial target has no source-backed location evidence: "
                            f"'{intervention.target_id}'"
                        ),
                        field_path=(
                            f"interventions.{intervention.intervention_id}.spatial_requirements"
                        ),
                        target_id=intervention.target_id,
                        spec_id=spec.spec_id,
                    )
                )
    return specs, diagnostics


__all__ = ["_DIRECTION_TO_8WIND", "map_intervention_to_spec", "map_interventions_to_specs"]
