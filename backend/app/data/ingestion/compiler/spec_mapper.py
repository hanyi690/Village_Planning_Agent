"""Deterministic rule-based mapper: PlanningIntervention -> SpatialReferenceSpec.

This mapper bridges L3 planning output to the closed-set spatial reference DSL.
It is fully deterministic: no LLM calls, no KG queries, and no geometry. When
an existing asset has one audited L1 exact-feature binding, it emits only a
named reference; the KG resolver remains responsible for uniqueness and WKT.
Direction hints are extracted from spatial_requirements string values (falling
back to problem_addressed and functions) via direction_from_location().
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.data.ingestion.spatial_language import direction_from_location
from app.evidence.identity.source_feature_binding import (
    build_existing_facility_source_binding,
    build_existing_road_source_binding,
)
from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.evidence.identity_contracts import (
    EvidenceObservation,
    GroundedEntityBinding,
)
from app.contracts.workflow.parse_result_contracts import ParseDiagnostic
from app.contracts.spatial.spatial_reference_contracts import (
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

_GENERIC_VILLAGE_WORDS = frozenset({
    "全村", "村庄", "村域", "村内", "村组", "各村", "该村", "本村",
    "村中", "村级", "村委会", "村民小组", "自然村",
})


def _attach_source_binding(
    spec: SpatialReferenceSpec,
    binding: object | None,
) -> SpatialReferenceSpec:
    if binding is None:
        return spec
    return spec.model_copy(update={
        "source_binding_ref": str(getattr(binding, "binding_id", "") or ""),
        "source_collection_key": str(
            getattr(binding, "source_collection_key", "") or ""
        ),
        "source_snapshot_ref": str(
            getattr(binding, "source_snapshot_ref", "") or ""
        ),
        "source_feature_digest": str(
            getattr(binding, "source_feature_digest", "") or ""
        ),
        "l1_fact_refs": list(
            dict.fromkeys(
                str(value)
                for value in (getattr(binding, "source_fact_refs", None) or [])
                if str(value).strip()
            )
        ),
    })


def _materialization_role(intervention: PlanningIntervention) -> str | None:
    """Return the L3 materialization role carried by a spatial spec.

    Only categories with one unambiguous role receive a compatibility
    default.  A zone without an explicit role remains unresolved because it
    may be either an authoritative land-use assignment or a non-exclusive
    functional/protection/restoration overlay.
    """

    if intervention.materialization_role:
        return intervention.materialization_role
    if intervention.category == "site_area":
        return "site_footprint"
    if intervention.category == "protection":
        return "protection_overlay"
    if intervention.category == "restoration":
        return "restoration_overlay"
    return None


def _finalize_spec(
    spec: SpatialReferenceSpec,
    intervention: PlanningIntervention,
) -> SpatialReferenceSpec:
    spec.intervention_id = intervention.intervention_id
    spec.target_id = intervention.target_id
    spec.spec_id = f"spatial-ref:{intervention.target_id}"
    spec.project_ref = intervention.intervention_id
    spec.materialization_role = _materialization_role(intervention)
    return spec


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
    # Conservative fallback for a root-village name: a Chinese span ending in
    # 村 that is not a generic scope word.
    matches: list[str] = []
    for segment in re.split(r"[、，,；;和及与]", text):
        match = re.search(r"([\u4e00-\u9fff]{1,6}村)", segment)
        if not match:
            continue
        token = match.group(1)
        for prefix in ("服务", "覆盖", "建设", "规划", "连接", "改善"):
            if token.startswith(prefix) and len(token) > len(prefix) + 1:
                token = token[len(prefix):]
        if token not in _GENERIC_VILLAGE_WORDS:
            matches.append(token)
    return list(dict.fromkeys(matches))


def _location_reference(intervention: PlanningIntervention) -> SpatialReferenceSpec | None:
    """Map the L3 claim's location evidence to a closed-set spatial reference.

    The place names come from the L1-derived ``location_hints`` (all place
    names, never a preset village list) or from the location cell itself.
    Every explicit place token becomes its own resolvable reference.
    """
    requirements = intervention.spatial_requirements
    raw_parcel_refs = requirements.get("affected_parcel_refs")
    parcel_refs = list(dict.fromkeys(
        str(item).strip()
        for item in (raw_parcel_refs if isinstance(raw_parcel_refs, list) else [])
        if str(item).strip()
    ))
    # An explicit parcel identity is stronger than a natural-language place
    # hint. Keep it in the closed-set DSL so GROUND can bind exact source
    # geometry and retain duplicate source records as separate alternatives.
    bsm_refs = [item for item in parcel_refs if item.isdigit()]
    if not bsm_refs:
        hint_text = " ".join(
            [
                str(item).strip()
                for item in (requirements.get("location_hints") or [])
                if str(item).strip()
            ]
            + [str(requirements.get("location") or "").strip()]
        )
        bsm_refs = re.findall(r"(?:BSM|bsm)\s*[=:：]\s*(\d{6,})", hint_text)
        bsm_refs = list(dict.fromkeys(bsm_refs))
    if bsm_refs:
        refs = [
            SpatialReferenceSpec(
                type="attributive",
                reference=RefObject(kind="bsm", filter={"bsm": bsm}),
            )
            for bsm in bsm_refs
        ]
        if len(refs) == 1:
            return refs[0]
        return SpatialReferenceSpec(type="composed", op="or", children=refs)
    raw_hints = requirements.get("location_hints")
    hints = [
        str(item).strip()
        for item in (raw_hints if isinstance(raw_hints, list) else [])
        if str(item).strip()
    ]
    location = str(requirements.get("location") or "").strip()
    if location in _UNKNOWN_LOCATIONS and not hints:
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

    tokens = list(dict.fromkeys(hints))
    if not tokens:
        tokens = [
            tok.strip()
            for tok in re.split(r"[、，,；;及和与]+", location)
            if tok.strip() and tok.strip() not in _GENERIC_VILLAGE_WORDS
        ]
    if not tokens:
        return None
    refs = [
        SpatialReferenceSpec(
            type="topological",
            topo="nearby",
            reference=RefObject(
                kind="place_name",
                filter={"label_contains": token},
            ),
        )
        for token in tokens
    ]
    if len(refs) == 1:
        return refs[0]
    return SpatialReferenceSpec(type="composed", op="or", children=refs)


def _facility_location_reference(
    intervention: PlanningIntervention,
) -> SpatialReferenceSpec | None:
    """Bind a typed facility mention to its explicit place scope.

    ``location_hints`` may contain both an administrative/place anchor and the
    facility mention itself (for example ``社前村`` + ``祠堂``). Treating all
    hints as alternatives loses that relation and lets the resolver search
    the whole village or every matching facility independently. Only use this
    stronger conjunction when L3 explicitly typed one hint as the facility
    type; ambiguous hints retain the ordinary alternative semantics.
    """
    if intervention.category != "facility":
        return None
    parameters = intervention.facility_parameters
    facility_type = str(
        getattr(parameters, "facility_type", "") or ""
    ).strip()
    requirements = intervention.spatial_requirements or {}
    raw_hints = requirements.get("location_hints")
    if not facility_type or not isinstance(raw_hints, list):
        return None
    hints = list(dict.fromkeys(
        str(item).strip() for item in raw_hints if str(item).strip()
    ))
    if facility_type not in hints:
        return None
    place_hints = [hint for hint in hints if hint != facility_type]
    if not place_hints:
        return None
    place_refs = [
        SpatialReferenceSpec(
            type="topological",
            topo="nearby",
            reference=RefObject(
                kind="place_name",
                filter={"label_contains": hint},
            ),
        )
        for hint in place_hints
    ]
    place_scope = place_refs[0] if len(place_refs) == 1 else SpatialReferenceSpec(
        type="composed",
        op="or",
        children=place_refs,
    )
    facility_ref = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(
            kind="entity_type",
            filter={"label_contains": facility_type},
        ),
    )
    return SpatialReferenceSpec(
        type="composed",
        op="and",
        children=[place_scope, facility_ref],
    )


def _semantic_location_reference(
    intervention: PlanningIntervention,
) -> SpatialReferenceSpec | None:
    """Extract a location reference from prose when the location cell is empty.

    L3 claim compilation frequently leaves ``spatial_requirements.location``
    empty while ``problem_addressed``/``name`` carry explicit spatial scope
    (e.g. 金田村全域 / 沿石窟河沿岸 / 园宅村).  Mapping that prose into a
    closed-set spec lets GROUND resolve it through EvidenceGraph
    instead of deferring the target as unresolved.
    """
    text = " ".join([
        str(intervention.problem_addressed or ""),
        intervention.name,
        *intervention.functions,
    ])
    if not text.strip():
        return None
    if any(token in text for token in ("全域", "全村域", "村域内", "村域范围", "各自然村")):
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
    if village_names:
        return SpatialReferenceSpec(
            type="topological",
            topo="nearby",
            reference=RefObject(
                kind="place_name",
                filter={"label_contains": village_names[0]},
            ),
        )
    # Do not turn an arbitrary first Chinese span into a place name.  That
    # previous fallback produced one-character false mentions and polluted
    # GROUND with candidates such as "?" or "?".  Only retain explicit
    # feature-name suffixes that can be resolved by a session gazetteer/index,
    # and clean the candidate so generic scope words never become place names.
    for suffix in _FEATURE_NAME_SUFFIXES:
        match = re.search(
            rf"([\u4e00-\u9fff]{{1,10}}{suffix})",
            text,
        )
        if not match:
            continue
        cleaned = _clean_feature_mention(match.group(1))
        if not cleaned:
            continue
        return SpatialReferenceSpec(
            type="topological",
            topo="nearby",
            reference=RefObject(
                kind="place_name",
                filter={"label_contains": cleaned},
            ),
        )
    return None


# Minimal deterministic feature-name suffixes.  Broad feature extraction is
# delegated to the GROUND flash-LLM mention enhancer (see
# ``app.spatial.grounding.flash_mention_extractor``); this table only keeps a
# couple of extremely safe suffixes so a fully deterministic fallback still
# works when the enhancer is disabled.
_FEATURE_NAME_SUFFIXES = (
    "河",
)

# Leading tokens that are positional words, not part of the feature name.
_LOCATION_PREFIXES_TO_STRIP = (
    "沿", "依", "临", "靠",
    "村口", "村内", "村中", "村前", "村后", "村旁",
    "村东", "村南", "村西", "村北",
)

# Whole-candidate strings that are generic scope words, never place names.
_GENERIC_LOCATION_EXCLUSIONS = frozenset({
    "全村", "村庄", "村域", "村内", "村组", "各村", "该村", "本村", "村中",
})


def _clean_feature_mention(candidate: str) -> str | None:
    """Strip positional/action prefixes and reject generic scope words."""
    token = (candidate or "").strip()
    for prefix in _LOCATION_PREFIXES_TO_STRIP:
        while token.startswith(prefix):
            token = token[len(prefix):].strip()
    if not token or len(token) < 2:
        return None
    if token in _GENERIC_LOCATION_EXCLUSIONS:
        return None
    # A candidate that is fully composed of generic scope words is not a
    # locatable feature (e.g. 村内道路).  Keep only real feature names.
    if all(
        word in token
        for word in ("村内", "道路", "现状", "机耕", "巷道", "村道", "乡道")
    ) and len(token) <= 6:
        return None
    return token


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


def _source_binding_reference(
    intervention: PlanningIntervention,
    observations: Sequence[EvidenceObservation],
    bindings: Sequence[GroundedEntityBinding],
) -> SpatialReferenceSpec | None:
    """Project one audited existing-feature binding into the closed DSL.

    A binding is only an eligibility hint here.  The KG resolver must still
    find one entity with the exact label and authoritative ``geo:hasGeometry``
    before geometry can become executable.  New/planned assets deliberately
    do not consume existing-feature bindings.
    """
    if intervention.intervention_action not in {"preserve", "upgrade", "repair"}:
        return None
    if intervention.category not in {"facility", "road", "axis"}:
        return None
    observation_by_id = {item.observation_id: item for item in observations}
    target_text = " ".join(
        [
            intervention.name,
            str(intervention.spatial_requirements.get("location") or ""),
            *[
                str(value)
                for value in intervention.spatial_requirements.get("location_hints", [])
                if str(value).strip()
            ],
            *[
                str(value)
                for value in (
                    intervention.road_parameters.alignment_refs
                    if intervention.road_parameters is not None
                    else []
                )
                if str(value).strip()
            ],
        ]
    )
    matches: list[tuple[GroundedEntityBinding, EvidenceObservation]] = []
    expected_type = "facility" if intervention.category == "facility" else "road"
    for binding in bindings:
        if binding.status != "resolved" or binding.geometry_granularity != "exact_feature":
            continue
        if not str(binding.geometry_ref or "").strip():
            continue
        observation = observation_by_id.get(binding.mention_ref)
        if observation is None or observation.observed_type != expected_type:
            continue
        mention = str(observation.normalized_name or observation.mention or "").strip()
        if not mention or mention not in target_text:
            continue
        if not binding.canonical_entity_ref:
            continue
        matches.append((binding, observation))
    if len(matches) != 1:
        return None
    _, observation = matches[0]
    mention = str(observation.normalized_name or observation.mention).strip()
    rdf_type = "Facility" if intervention.category == "facility" else "Road"
    return SpatialReferenceSpec(
        type="directional",
        reference=RefObject(
            kind="entity_type",
            filter={"rdf_type": rdf_type, "label_contains": mention},
        ),
    )


def _explicit_source_feature_reference(
    intervention: PlanningIntervention,
    *,
    source_features: Sequence[object] | None = None,
) -> SpatialReferenceSpec | None:
    """Project explicitly supplied source feature IDs without text inference.

    ``source_feature_ids`` is an auditable adapter field, not a free-text
    location hint.  Only facility/road existing-asset actions consume it;
    the KG resolver still verifies entity type and authoritative WKT.  Invalid
    or absent values deliberately return ``None`` so no exact geometry claim
    is manufactured here.
    """
    existing_actions = {"preserve", "upgrade", "widen", "harden", "repair"}
    typed_parameters = (
        intervention.road_parameters
        if intervention.category == "road" and intervention.road_parameters is not None
        else intervention.axis_parameters
        if intervention.category == "axis" and intervention.axis_parameters is not None
        else None
    )
    typed_action = str(getattr(typed_parameters, "action", "") or "")
    if intervention.intervention_action not in existing_actions and typed_action not in existing_actions:
        return None
    if intervention.category not in {"facility", "road", "axis"}:
        return None
    requirements = intervention.spatial_requirements or {}
    raw_ids = next(
        (
            requirements.get(key)
            for key in (
                "source_feature_ids",
                "existing_road_feature_ids",
                "road_feature_ids",
            )
            if key in requirements
        ),
        None,
    )
    if intervention.category in {"facility", "road", "axis"} and source_features:
        # If the current source layer is available, reject foreign/stale IDs
        # before they cross the exact-feature boundary. With no source layer,
        # the explicit-ID contract remains auditable and the KG resolver is
        # responsible for the authoritative geometry check.
        expected_geometry = (
            {"Point", "MultiPoint"}
            if intervention.category == "facility"
            else {"LineString", "MultiLineString"}
        )
        source_ids = {
            str((getattr(feature, "_raw", {}) or {}).get("source_feature_id") or "").strip()
            for feature in source_features
            if isinstance(getattr(feature, "geometry", None), dict)
            and getattr(feature, "geometry", {}).get("type")
            in expected_geometry
        }
        requested = raw_ids if isinstance(raw_ids, (list, tuple, set)) else []
        requested_ids = {str(item).strip() for item in requested if str(item).strip()}
        if not requested_ids or not requested_ids.issubset(source_ids):
            return None
    if not isinstance(raw_ids, (list, tuple)):
        return None
    source_ids = list(
        dict.fromkeys(
            str(item).strip()
            for item in raw_ids
            if isinstance(item, str) and item.strip()
        )
    )
    if not source_ids:
        return None
    rdf_type = "Facility" if intervention.category == "facility" else "Road"
    return SpatialReferenceSpec(
        type="directional",
        reference=RefObject(
            kind="entity_type",
            filter={
                "rdf_type": rdf_type,
                "source_feature_ids": source_ids,
                "allow_multiple_exact": len(source_ids) > 1,
            },
        ),
    )


def _build_candidates(
    intervention: PlanningIntervention,
    *,
    observations: Sequence[EvidenceObservation] = (),
    bindings: Sequence[GroundedEntityBinding] = (),
    source_features: dict[str, list[object]] | None = None,
    source_semantic_decisions: Mapping[str, object] | None = None,
) -> list[SpatialReferenceSpec]:
    candidates: list[SpatialReferenceSpec] = []

    source_map = source_features or {}
    collection_binding = (
        build_existing_facility_source_binding(
            intervention,
            source_map.get("facility", ()),
            source_semantic_decisions,
        )
        if intervention.category == "facility"
        else build_existing_road_source_binding(
            intervention,
            source_map.get("road", ()),
            source_semantic_decisions,
        )
        if intervention.category in {"road", "axis"}
        else None
    )
    explicit_source = _explicit_source_feature_reference(
        intervention,
        source_features=(
            source_map.get("facility", ())
            if intervention.category == "facility"
            else source_map.get("road", ())
            if intervention.category in {"road", "axis"}
            else None
        ),
    )
    if explicit_source is not None:
        # Explicit source IDs are stronger than prose and must be the only
        # location evidence used for this exact-feature path.
        candidates.append(_attach_source_binding(explicit_source, collection_binding))
        return candidates

    facility_binding = build_existing_facility_source_binding(
        intervention,
        source_map.get("facility", ()),
        source_semantic_decisions,
    )
    grouped_ids = list(facility_binding.source_feature_ids) if facility_binding else []
    if grouped_ids:
        candidates.append(_attach_source_binding(
            SpatialReferenceSpec(
                type="directional",
                reference=RefObject(
                    kind="entity_type",
                    filter={
                        "rdf_type": "Facility",
                        "source_feature_ids": grouped_ids,
                        "allow_multiple_exact": len(grouped_ids) > 1,
                    },
                ),
            ),
            facility_binding,
        ))
        return candidates

    road_binding = build_existing_road_source_binding(
        intervention,
        source_map.get("road", ()),
        source_semantic_decisions,
    )
    road_ids = list(road_binding.source_feature_ids) if road_binding else []
    if road_ids:
        candidates.append(_attach_source_binding(
            SpatialReferenceSpec(
                type="directional",
                reference=RefObject(
                    kind="entity_type",
                    filter={
                        "rdf_type": "Road",
                        "source_feature_ids": road_ids,
                        "allow_multiple_exact": len(road_ids) > 1,
                    },
                ),
            ),
            road_binding,
        ))
        return candidates

    source_binding = _source_binding_reference(intervention, observations, bindings)
    if source_binding is not None:
        # Existing-feature evidence is a stronger, auditable anchor than a
        # broad prose location.  KG uniqueness/geometry checks remain the
        # final authority; if they fail, GROUND stays candidate-only.
        candidates.append(source_binding)
        return candidates

    location_ref = _facility_location_reference(intervention)
    if location_ref is None:
        location_ref = _location_reference(intervention)
    if location_ref is None:
        location_ref = _semantic_location_reference(intervention)
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

    # Real L3 prose occasionally contains an explicit village name but no
    # structured location reference. Preserve that textual reference so the
    # normal resolver can locate the corresponding GIS feature. Do not invent
    # a location when the prose contains no named village.
    return candidates


def map_intervention_to_spec(
    intervention: PlanningIntervention,
    *,
    observations: Sequence[EvidenceObservation] = (),
    bindings: Sequence[GroundedEntityBinding] = (),
    source_features: dict[str, list[object]] | None = None,
    source_semantic_decisions: Mapping[str, object] | None = None,
) -> SpatialReferenceSpec | None:
    """Deterministically map a spatial intervention to one linked spec."""
    if intervention.execution_mode == "non_spatial":
        return None
    candidates = _build_candidates(
        intervention,
        observations=observations,
        bindings=bindings,
        source_features=source_features,
        source_semantic_decisions=source_semantic_decisions,
    )
    if not candidates:
        return _finalize_spec(SpatialReferenceSpec(
            type="composed",
            op="and",
            intervention_id=intervention.intervention_id,
            target_id=intervention.target_id,
            spec_id=f"spatial-ref:{intervention.target_id}",
            project_ref=intervention.intervention_id,
            unresolved_reason="missing_location_evidence",
        ), intervention)
    if len(candidates) == 1:
        spec = candidates[0]
        return _finalize_spec(spec, intervention)
    # A target's independent spatial requirements are conjunctive by default:
    # location, direction, allowed land-use and topology all constrain the
    # same candidate domain.  Alternatives must be represented explicitly by
    # the upstream typed contract; treating every extracted clue as OR makes a
    # candidate pass when it satisfies only one weak hint.
    spec = SpatialReferenceSpec(type="composed", op="and", children=candidates)
    return _finalize_spec(spec, intervention)


def map_interventions_to_specs(
    interventions: list[PlanningIntervention],
    *,
    observations: Sequence[EvidenceObservation] = (),
    bindings: Sequence[GroundedEntityBinding] = (),
    source_features: dict[str, list[object]] | None = None,
    source_semantic_decisions: Mapping[str, object] | None = None,
) -> tuple[list[SpatialReferenceSpec], list[ParseDiagnostic]]:
    """Batch map targets while retaining unresolved spatial requirements."""
    specs: list[SpatialReferenceSpec] = []
    diagnostics: list[ParseDiagnostic] = []
    for intervention in interventions:
        spec = map_intervention_to_spec(
            intervention,
            observations=observations,
            bindings=bindings,
            source_features=source_features,
            source_semantic_decisions=source_semantic_decisions,
        )
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
