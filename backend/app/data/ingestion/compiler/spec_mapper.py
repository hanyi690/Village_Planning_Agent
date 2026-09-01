"""Map typed L3 spatial intent to the closed-set spatial reference DSL.

This boundary is deliberately narrow.  It consumes only typed location hints,
parcel/source-feature references, audited bindings, and typed parameter blocks
already present on ``PlanningIntervention``.  It does not reinterpret
``name``/``problem_addressed``/``functions`` prose, infer a village or a
direction from free text, or manufacture a geometry.  GROUND remains the
authority for entity uniqueness and geometry.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json

from app.contracts.l3.l3_contracts import PlanningIntervention
from app.contracts.evidence.identity_contracts import (
    EvidenceObservation,
    GroundedEntityBinding,
    SourceFeatureSetBinding,
)
from app.contracts.target_projection.parse_result_contracts import ParseDiagnostic
from app.contracts.ground.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
)

_VILLAGE_SCOPE_LOCATIONS = frozenset({
    "全村", "村域", "村域范围", "各自然村", "各村", "各组", "各村民小组",
})

_GENERIC_VILLAGE_WORDS = frozenset({
    "全村", "村庄", "村域", "村内", "村组", "各村", "该村", "本村",
    "村中", "村级", "村委会", "村民小组", "自然村",
})


def _binding_requirements(intervention: PlanningIntervention) -> dict[str, object]:
    return dict(getattr(intervention, "spatial_requirements", {}) or {})


def _binding_operation(intervention: PlanningIntervention) -> str:
    params = getattr(intervention, "facility_parameters", None)
    if getattr(intervention, "category", "") in {"road", "axis"}:
        params = (
            getattr(intervention, "road_parameters", None)
            or getattr(intervention, "axis_parameters", None)
            or getattr(intervention, "linear_parameters", None)
        )
    action = str(
        getattr(intervention, "intervention_action", "")
        or getattr(params, "action", "")
        or ""
    ).strip().lower()
    if action in {"preserve", "upgrade", "repair", "widen", "harden"}:
        return "harden" if action == "upgrade" else action
    if (
        action == "new"
        and getattr(intervention, "category", "") == "facility"
        and _binding_requirements(intervention).get("source_fact_refs")
    ):
        return "reference"
    return "reference" if action == "reference" else ""


def _binding_feature_identity(feature: object) -> tuple[str, str, str]:
    raw = getattr(feature, "_raw", {}) or {}
    source_id = str(raw.get("source_feature_id") or "").strip()
    snapshot = str(
        raw.get("source_snapshot_ref")
        or raw.get("source_content_digest")
        or ""
    ).strip()
    geometry = getattr(feature, "geometry", None)
    geometry_type = (
        str(geometry.get("type") or "")
        if isinstance(geometry, dict)
        else ""
    )
    return source_id, snapshot, geometry_type


def _build_existing_source_binding(
    intervention: PlanningIntervention,
    source_features: Sequence[object],
    *,
    collection_key: str,
    expected_geometry: set[str],
    semantic_group: str = "",
    semantic_decisions: Mapping[str, object] | None = None,
) -> SourceFeatureSetBinding | None:
    operation = _binding_operation(intervention)
    if not operation:
        return None
    requirements = _binding_requirements(intervention)
    valid: dict[str, tuple[object, str]] = {}
    for feature in source_features:
        source_id, snapshot, geometry_type = _binding_feature_identity(feature)
        if not source_id or not snapshot or geometry_type not in expected_geometry:
            continue
        raw = getattr(feature, "_raw", {}) or {}
        if semantic_group:
            semantic_value = str(
                raw.get("source_label")
                or raw.get("text")
                or getattr(feature, "text", "")
                or ""
            ).strip()
            decision = (semantic_decisions or {}).get(source_id)
            decision_status = str(
                getattr(decision, "status", "")
                or (
                    decision.get("status", "")
                    if isinstance(decision, Mapping)
                    else ""
                )
            ).strip()
            if decision_status == "accepted":
                semantic_value = str(
                    getattr(decision, "semantic_type", "")
                    or (
                        decision.get("semantic_type", "")
                        if isinstance(decision, Mapping)
                        else ""
                    )
                    or semantic_value
                ).strip()
            if semantic_value != semantic_group:
                continue
        valid.setdefault(source_id, (feature, snapshot))
    if not valid:
        return None
    requested = (
        requirements.get("source_feature_ids")
        or requirements.get("existing_road_feature_ids")
        or requirements.get("road_feature_ids")
    )
    if requested is not None:
        requested_ids = (
            list(
                dict.fromkeys(
                    str(item).strip()
                    for item in requested
                    if str(item).strip()
                )
            )
            if isinstance(requested, (list, tuple, set))
            else []
        )
        if not requested_ids or any(item not in valid for item in requested_ids):
            return None
        member_ids = requested_ids
        binding_mode = "explicit_subset"
    else:
        declared_collection = str(
            requirements.get("source_collection_key") or ""
        ).strip()
        required_facts = [
            str(item).strip()
            for item in (requirements.get("source_fact_refs") or [])
            if str(item).strip()
        ]
        if declared_collection != collection_key and not required_facts:
            return None
        member_ids = sorted(valid)
        binding_mode = "semantic_fact_subset" if required_facts else "all_in_scope"
    snapshots = {valid[item][1] for item in member_ids}
    if len(snapshots) != 1:
        return None
    snapshot = next(iter(snapshots))
    membership = str(requirements.get("membership") or "required").strip()
    if membership not in {"required", "alternative", "eligible_subset"}:
        return None
    source_feature_digest = hashlib.sha256(
        "|".join([collection_key, snapshot, *sorted(member_ids)]).encode("utf-8")
    ).hexdigest()
    seed = {
        "target_id": str(getattr(intervention, "target_id", "") or ""),
        "collection": collection_key,
        "snapshot": snapshot,
        "ids": sorted(member_ids),
        "operation": operation,
    }
    binding_id = "source-binding:" + hashlib.sha256(
        json.dumps(seed, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    fact_refs = [
        str(item).strip()
        for item in (requirements.get("source_fact_refs") or [])
        if str(item).strip()
    ]
    if not fact_refs:
        fact_refs = [f"bundle:collection:{collection_key}:{snapshot}"]
    semantic_refs = requirements.get("source_semantic_decision_refs") or []
    return SourceFeatureSetBinding(
        binding_id=binding_id,
        target_id=str(getattr(intervention, "target_id", "") or ""),
        source_collection_key=collection_key,
        source_snapshot_ref=snapshot,
        source_feature_digest=source_feature_digest,
        source_feature_ids=member_ids,
        binding_mode=binding_mode,
        membership=membership,
        operation=operation,
        source_fact_refs=fact_refs,
        source_semantic_decision_refs=(
            [str(item) for item in semantic_refs]
            if isinstance(semantic_refs, (list, tuple, set))
            else []
        ),
    )


def build_existing_facility_source_binding(
    intervention: PlanningIntervention,
    source_features: Sequence[object] = (),
    semantic_decisions: Mapping[str, object] | None = None,
) -> SourceFeatureSetBinding | None:
    if getattr(intervention, "category", "") != "facility":
        return None
    params = getattr(intervention, "facility_parameters", None)
    target_type = str(getattr(params, "facility_type", "") or "").strip()
    groups = {
        "公交站": "公交站",
        "公交站点": "公交站",
        "公交站亭": "公交站",
        "文化展示设施": "祠堂",
        "文化活动中心": "祠堂",
        "祠堂": "祠堂",
    }
    requirements = _binding_requirements(intervention)
    if target_type not in groups and not requirements.get("source_fact_refs"):
        return None
    return _build_existing_source_binding(
        intervention,
        source_features,
        collection_key=str(
            requirements.get("source_collection_key") or "current_facility"
        ),
        expected_geometry={"Point", "MultiPoint"},
        semantic_group=groups.get(target_type, ""),
        semantic_decisions=semantic_decisions,
    )


def build_existing_road_source_binding(
    intervention: PlanningIntervention,
    source_features: Sequence[object] = (),
    semantic_decisions: Mapping[str, object] | None = None,
) -> SourceFeatureSetBinding | None:
    if getattr(intervention, "category", "") not in {"road", "axis"}:
        return None
    requirements = _binding_requirements(intervention)
    return _build_existing_source_binding(
        intervention,
        source_features,
        collection_key=str(
            requirements.get("source_collection_key") or "current_road"
        ),
        expected_geometry={"LineString", "MultiLineString"},
        semantic_decisions=semantic_decisions,
    )


def _attach_source_binding(
    spec: SpatialReferenceSpec,
    binding: object | None,
) -> SpatialReferenceSpec:
    if binding is None:
        return spec
    snapshot_ref = str(
        getattr(binding, "source_snapshot_ref", "") or ""
    ).strip()
    snapshot_digest = str(
        getattr(binding, "source_snapshot_digest", "") or ""
    ).strip()
    if not snapshot_digest:
        raw_digest = snapshot_ref.removeprefix("sha256:")
        if len(raw_digest) == 64 and all(
            char in "0123456789abcdefABCDEF" for char in raw_digest
        ):
            snapshot_digest = snapshot_ref
    return spec.model_copy(update={
        "source_binding_ref": str(getattr(binding, "binding_id", "") or ""),
        "source_collection_key": str(
            getattr(binding, "source_collection_key", "") or ""
        ),
        "source_snapshot_ref": str(
            snapshot_ref
        ),
        "source_snapshot_digest": snapshot_digest,
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

    Only categories with one unambiguous domain default receive a role.  A
    zone without an explicit role remains unresolved because it
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
    declared_fact_refs = [
        str(value).strip()
        for value in (getattr(intervention, "source_fact_refs", None) or [])
        if str(value).strip()
    ]
    spec.intervention_id = intervention.intervention_id
    spec.target_id = intervention.target_id
    spec.spec_id = f"spatial-ref:{intervention.target_id}"
    spec.project_ref = intervention.intervention_id
    spec.materialization_role = _materialization_role(intervention)
    spec.l1_fact_refs = list(dict.fromkeys([
        *spec.l1_fact_refs,
        *declared_fact_refs,
    ]))
    return spec


def _location_reference(intervention: PlanningIntervention) -> SpatialReferenceSpec | None:
    """Map explicit typed location/parcel references to a spatial spec.

    ``location_hints`` is an L3 semantic input, not a resolved geometry.  The
    exact closed-set tokens below are the only scope interpretation performed
    here; all other hints remain place-name queries for GROUND to resolve.
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
    if not hints:
        return None
    normalized_hints = {
        "".join(str(item).split()) for item in hints
    }
    if normalized_hints.intersection(_VILLAGE_SCOPE_LOCATIONS):
        return SpatialReferenceSpec(
            type="topological",
            topo="sfWithin",
            reference=RefObject(kind="village"),
        )

    tokens = [
        token for token in hints
        if token not in _GENERIC_VILLAGE_WORDS
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
    if location_ref is not None:
        candidates.append(location_ref)

    # Relations, attributes, and network prerequisites are already typed on
    # ``PlanningSpatialRequirements`` and are compiled into the intent/task
    # graph.  They must not be rediscovered from arbitrary mapping keys here.
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


__all__ = ["map_intervention_to_spec", "map_interventions_to_specs"]
