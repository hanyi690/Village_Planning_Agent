"""Close GROUND candidates against the frozen DATA catalog at SELECT.

This module is intentionally deterministic.  It does not search providers,
infer geometry from names, or accept a candidate WKT as authority.  A selected
row must resolve through an available DATA representation and capability in
the same catalog snapshot that GROUND recorded.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.data.admission import (
    build_admission_index,
    feature_admission_verdict,
    is_admitted_capability,
    is_admitted_representation,
)
from app.contracts.select.selection_decision import (
    SelectionDecision,
    SelectionDecisionSet,
)


class SelectionBindingError(ValueError):
    """A candidate cannot be promoted into an executable resource binding."""

    def __init__(self, diagnostics: list[dict[str, Any]]):
        self.diagnostics = diagnostics
        codes = sorted({str(item.get("code") or "selection_binding_invalid") for item in diagnostics})
        super().__init__("; ".join(codes) or "selection_binding_invalid")


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return sorted({str(item).strip() for item in (value or []) if str(item).strip()})


def _geometry_kind(geometry: Mapping[str, Any] | None) -> str:
    value = str((geometry or {}).get("type") or "").casefold()
    return {
        "point": "point",
        "multipoint": "point",
        "linestring": "line",
        "multilinestring": "line",
        "polygon": "polygon",
        "multipolygon": "polygon",
        "multipatch": "multipatch",
    }.get(value, "unknown")


def _geometry_loadable(geometry: Mapping[str, Any] | None, kind: str) -> bool:
    if not isinstance(geometry, Mapping) or not geometry.get("type"):
        return False
    if kind == "multipatch":
        return bool(geometry.get("coordinates") or geometry.get("parts"))
    try:
        from shapely.geometry import shape

        resolved = shape(dict(geometry))
    except Exception:
        return False
    return not resolved.is_empty and resolved.is_valid


def _candidate_geometry_matches_data(
    candidate: Any,
    geometry: Mapping[str, Any] | None,
) -> bool:
    try:
        from shapely import wkt
        from shapely.geometry import shape

        candidate_geometry = wkt.loads(str(_value(candidate, "wkt", "") or ""))
        data_geometry = shape(dict(geometry or {}))
    except Exception:
        return False
    return (
        not candidate_geometry.is_empty
        and candidate_geometry.is_valid
        and candidate_geometry.equals(data_geometry)
    )


def _operation(candidate: Any, selection: Any) -> tuple[str, str, dict[str, Any]]:
    """Return approved operation, required capability, and closed parameters."""

    generation = str(_value(candidate, "generation_operation", "") or "")
    subgeometry = str(_value(candidate, "subgeometry_operation", "") or "")
    candidate_operation = str(_value(candidate, "operation", "") or "read")
    operation = str(_value(selection, "operation", "") or "").strip()
    required = str(_value(selection, "required_capability", "") or "").strip()
    parameters: dict[str, Any] = dict(
        _value(selection, "operation_parameters", {}) or {}
    )
    if generation == "select_parcel_representative_point":
        operation = "point_placement"
        required = "point_placement"
        parameters = {"method": "representative_point"}
    elif subgeometry == "shared_parcel_capacity_partition":
        # The current SELECT implementation has already cut this geometry but
        # does not publish enough parameters for EXECUTE to replay the split.
        # Refuse to bless that WKT as if it were a DATA source geometry.
        operation = "split"
        required = "split"
        parameters = {}
    elif candidate_operation not in {"", "select", "select_resource"}:
        operation = candidate_operation
        required = (
            candidate_operation
            if required in {"", "read"}
            else required
        )
    else:
        operation = "representation_derivation" if operation in {"", "select", "select_resource"} else operation
        required = required or "read"
    return operation, required or "read", parameters


def _candidate_diagnostics(
    candidate: Any,
    *,
    target_ref: str,
) -> list[dict[str, Any]]:
    candidate_ref = str(_value(candidate, "candidate_id", "") or "")
    common = {"target_ref": target_ref, "candidate_ref": candidate_ref}
    diagnostics: list[dict[str, Any]] = []
    checks = (
        (bool(candidate_ref), "candidate_ref_missing"),
        (str(_value(candidate, "role", "") or "") == "execution_geometry", "candidate_not_execution_geometry"),
        (bool(_value(candidate, "is_executable", False)), "candidate_not_executable"),
        (str(_value(candidate, "schema_status", "") or "") == "valid", "candidate_schema_not_valid"),
        (str(_value(candidate, "hard_constraint_status", "") or "") == "passed", "hard_constraints_not_passed"),
        (
            str(_value(candidate, "availability_status", "") or "")
            in {"fully_available", "partially_available"},
            "availability_not_resolved",
        ),
        (len(_strings(_value(candidate, "entity_refs", []))) == 1, "entity_ref_missing_or_ambiguous"),
        (bool(str(_value(candidate, "part_ref", "") or "").strip()), "part_ref_missing"),
        (len(_strings(_value(candidate, "resource_refs", []))) == 1, "resource_ref_missing_or_ambiguous"),
        (len(_strings(_value(candidate, "representation_refs", []))) == 1, "representation_ref_missing_or_ambiguous"),
        (len(_strings(_value(candidate, "source_feature_ids", []))) == 1, "geometry_ref_missing_or_ambiguous"),
        (bool(str(_value(candidate, "source_snapshot_ref", "") or "").strip()), "source_snapshot_ref_missing"),
        (bool(str(_value(candidate, "resource_digest", "") or "").strip()), "resource_digest_missing"),
        (bool(str(_value(candidate, "crs", "") or "").strip()), "input_crs_missing"),
        (
            str(_value(candidate, "spatial_domain_kind", "") or "")
            == "exact_feature",
            "coarse_scope_not_selectable",
        ),
    )
    for passed, code in checks:
        if not passed:
            diagnostics.append({"code": code, **common})
    authority_refs = [
        *_strings(_value(candidate, "resource_refs", [])),
        *_strings(_value(candidate, "representation_refs", [])),
        *_strings(_value(candidate, "source_feature_ids", [])),
    ]
    if any(
        value.startswith("external-observation:")
        or ":external-observation:" in value
        for value in authority_refs
    ):
        diagnostics.append({"code": "external_observation_geometry_forbidden", **common})
    return diagnostics


def _binding_matches_candidate(binding: Any, candidate: Any, *, target_ref: str) -> bool:
    """Check that a resolved GROUND binding is the parent of this candidate."""

    if str(_value(binding, "target_id", "") or "") != target_ref:
        return False
    candidate_entities = _strings(_value(candidate, "entity_refs", []))
    candidate_resources = _strings(_value(candidate, "resource_refs", []))
    candidate_representations = _strings(_value(candidate, "representation_refs", []))
    candidate_features = _strings(_value(candidate, "source_feature_ids", []))
    binding_entity = str(_value(binding, "entity_ref", "") or "").strip()
    binding_resource = str(_value(binding, "resource_ref", "") or "").strip()
    binding_representation = str(_value(binding, "representation_ref", "") or "").strip()
    binding_feature = _strings(_value(binding, "source_feature_refs", []))
    if not binding_entity or candidate_entities != [binding_entity]:
        return False
    if not binding_resource or candidate_resources != [binding_resource]:
        return False
    if not binding_representation or candidate_representations != [binding_representation]:
        return False
    if len(binding_feature) != 1 or candidate_features != binding_feature:
        return False
    if str(_value(binding, "part_ref", "") or "").strip() != str(_value(candidate, "part_ref", "") or "").strip():
        return False
    for field_name in ("source_snapshot_ref", "resource_digest", "crs"):
        if str(_value(binding, field_name, "") or "").strip() != str(_value(candidate, field_name, "") or "").strip():
            return False
    if str(_value(binding, "hard_constraint_status", "") or "") != "passed":
        return False
    if str(_value(binding, "availability_status", "") or "") not in {
        "fully_available",
        "partially_available",
    }:
        return False
    return bool(str(_value(binding, "geometry_ref", "") or "").strip())


def _resolved_grounding_binding(
    problem: Any,
    candidate: Any,
    *,
    target_ref: str,
) -> tuple[Any | None, list[dict[str, Any]]]:
    """Join a SELECT candidate to exactly one resolved GROUND binding.

    Suitability may derive a new candidate ID (for example a clipped parcel
    footprint), so the join first honours an explicit source binding and then
    uses the complete identity/resource/feature tuple.  It never treats a
    candidate's WKT or a KG entity alone as a binding.
    """

    candidate_ref = str(_value(candidate, "candidate_id", "") or "").strip()
    common = {"target_ref": target_ref, "candidate_ref": candidate_ref}
    bindings = [
        item
        for item in list(_value(problem, "bindings", []) or [])
        if str(_value(item, "status", "") or "") == "resolved"
    ]
    if not bindings:
        return None, [{"code": "resolved_grounding_binding_missing", **common}]
    source_binding_ref = str(_value(candidate, "source_binding_ref", "") or "").strip()
    explicit = [
        item
        for item in bindings
        if str(_value(item, "binding_id", "") or "") == source_binding_ref
        or str(_value(item, "candidate_ref", "") or "") == candidate_ref
    ]
    if explicit:
        matches = [
            item for item in explicit
            if _binding_matches_candidate(item, candidate, target_ref=target_ref)
        ]
    else:
        matches = [
            item for item in bindings
            if _binding_matches_candidate(item, candidate, target_ref=target_ref)
        ]
    if len(matches) == 1:
        return matches[0], []
    if len(matches) > 1:
        return None, [{"code": "resolved_grounding_binding_ambiguous", **common}]
    return None, [{"code": "candidate_not_joined_to_resolved_grounding", **common}]


def build_selection_decision_set(
    scenario: Any,
    problem: Any,
    data_catalog: Any,
) -> SelectionDecisionSet:
    """Compile selected scenario members into DATA-closed decisions.

    Every representation is checked against the current immutable catalog;
    there is no Bundle/BSM fallback. Each selected row joins one and only one
    resolved GROUND binding, DATA representation, resource and capability.
    """

    if data_catalog is None or getattr(data_catalog, "snapshot", None) is None:
        raise SelectionBindingError([{"code": "data_resource_catalog_missing"}])
    snapshot = data_catalog.snapshot
    if not str(getattr(snapshot, "snapshot_id", "") or "").strip():
        raise SelectionBindingError([{"code": "data_snapshot_ref_missing"}])
    if not str(getattr(snapshot, "digest", "") or "").strip():
        raise SelectionBindingError([{"code": "data_catalog_digest_missing"}])
    try:
        admission_index = build_admission_index(snapshot)
    except (TypeError, ValueError) as exc:
        raise SelectionBindingError([{
            "code": "data_admission_index_unavailable",
            "detail": type(exc).__name__,
        }]) from exc
    scenario_problem_fingerprint = str(
        _value(scenario, "problem_fingerprint", "") or ""
    ).strip()
    problem_fingerprint = str(_value(problem, "fingerprint", "") or "").strip()
    if (
        not scenario_problem_fingerprint
        or scenario_problem_fingerprint != problem_fingerprint
    ):
        raise SelectionBindingError([{"code": "scenario_ground_problem_mismatch"}])
    completeness = _value(problem, "candidate_completeness", None)
    if str(_value(completeness, "status", "incomplete") or "incomplete") != "candidate_complete":
        raise SelectionBindingError([{"code": "ground_candidate_completeness_blocked"}])
    candidates = {
        str(_value(item, "candidate_id", "") or ""): item
        for item in list(_value(problem, "candidate_geometries", []) or [])
        if str(_value(item, "candidate_id", "") or "").strip()
    }
    decisions: list[SelectionDecision] = []
    diagnostics: list[dict[str, Any]] = []
    target_statuses = {
        str(_value(item, "target_id", "") or ""): str(
            _value(item, "status", "unresolved") or "unresolved"
        )
        for item in list(_value(problem, "target_domains", []) or [])
    }
    candidate_domain_statuses = {
        str(_value(item, "target_id", "") or ""): str(
            _value(item, "status", "unresolved") or "unresolved"
        )
        for item in list(_value(problem, "candidate_domains", []) or [])
    }
    expected_output_kinds = {
        str(_value(item, "target_id", "") or ""): str(
            _value(item, "expected_output_kind", "unknown") or "unknown"
        ).casefold()
        for item in list(_value(problem, "target_domains", []) or [])
    }
    for selection in list(_value(scenario, "target_selections", []) or []):
        target_ref = str(_value(selection, "target_id", "") or "")
        for candidate_ref in _strings(_value(selection, "candidate_ids", [])):
            if target_statuses.get(target_ref) != "resolved":
                diagnostics.append({
                    "code": "ground_target_not_resolved",
                    "target_ref": target_ref,
                    "candidate_ref": candidate_ref,
                })
                continue
            if candidate_domain_statuses.get(target_ref) != "resolved":
                diagnostics.append({
                    "code": "ground_candidate_domain_not_resolved",
                    "target_ref": target_ref,
                    "candidate_ref": candidate_ref,
                })
                continue
            candidate = candidates.get(candidate_ref)
            if candidate is None:
                diagnostics.append({
                    "code": "selected_candidate_missing",
                    "target_ref": target_ref,
                    "candidate_ref": candidate_ref,
                })
                continue
            grounding_binding, binding_diagnostics = _resolved_grounding_binding(
                problem,
                candidate,
                target_ref=target_ref,
            )
            diagnostics.extend(binding_diagnostics)
            if binding_diagnostics:
                continue
            candidate_diagnostics = _candidate_diagnostics(
                candidate,
                target_ref=target_ref,
            )
            diagnostics.extend(candidate_diagnostics)
            if candidate_diagnostics:
                continue
            operation, required_capability, operation_parameters = _operation(candidate, selection)
            if operation == "split" and not operation_parameters:
                diagnostics.append({
                    "code": "approved_operation_parameters_missing",
                    "operation": operation,
                    "target_ref": target_ref,
                    "candidate_ref": candidate_ref,
                })
            resources = _strings(_value(candidate, "resource_refs", []))
            representations = _strings(_value(candidate, "representation_refs", []))
            entity_refs = [str(_value(grounding_binding, "entity_ref", "") or "").strip()]
            part_ref = str(_value(grounding_binding, "part_ref", "") or "").strip()
            candidate_kind = str(_value(candidate, "kind", "") or "").casefold()
            expected_kind = expected_output_kinds.get(target_ref, "unknown")
            if expected_kind == "parcel":
                expected_kind = "polygon"
            if expected_kind not in {"", "unknown", candidate_kind}:
                diagnostics.append({
                    "code": "target_geometry_kind_mismatch",
                    "target_ref": target_ref,
                    "candidate_ref": candidate_ref,
                    "expected_geometry_kind": expected_kind,
                    "candidate_geometry_kind": candidate_kind,
                })
                continue
            candidate_crs = str(_value(candidate, "crs", "") or "")
            candidate_snapshot = str(_value(candidate, "source_snapshot_ref", "") or "")
            candidate_digest = str(_value(candidate, "resource_digest", "") or "")
            for index, representation_ref in enumerate(representations):
                representation = data_catalog.get_representation(representation_ref)
                common = {
                    "target_ref": target_ref,
                    "candidate_ref": candidate_ref,
                    "representation_ref": representation_ref,
                }
                if representation is None:
                    diagnostics.append({"code": "representation_not_in_data_catalog", **common})
                    continue
                if not is_admitted_representation(
                    snapshot,
                    representation,
                    index=admission_index,
                ):
                    diagnostics.append({
                        "code": "representation_not_admitted_to_current_world",
                        "dataset_ref": str(representation.dataset_ref or ""),
                        **common,
                    })
                    continue
                resource_ref = str(representation.resource_ref or "")
                if resources != [resource_ref]:
                    diagnostics.append({"code": "representation_resource_not_bound", "resource_ref": resource_ref, **common})
                    continue
                admitted_resource_refs = (
                    admission_index.resource_refs
                    | admission_index.representation_resource_refs
                )
                if resource_ref not in admitted_resource_refs:
                    diagnostics.append({
                        "code": "resource_not_admitted_to_current_world",
                        "resource_ref": resource_ref,
                        **common,
                    })
                    continue
                binding_checks = {
                    "binding_representation_mismatch": (
                        str(_value(grounding_binding, "representation_ref", "") or "")
                        == representation_ref
                    ),
                    "binding_resource_mismatch": (
                        str(_value(grounding_binding, "resource_ref", "") or "")
                        == resource_ref
                    ),
                    "binding_geometry_ref_mismatch": (
                        str(_value(grounding_binding, "geometry_ref", "") or "")
                        == str(representation.geometry_ref or "")
                    ),
                    "binding_source_feature_mismatch": (
                        _strings(_value(grounding_binding, "source_feature_refs", []))
                        == [str(representation.source_feature_ref or "")]
                    ),
                }
                failed_binding_checks = [
                    code for code, passed in binding_checks.items() if not passed
                ]
                if failed_binding_checks:
                    diagnostics.extend(
                        {"code": code, **common} for code in failed_binding_checks
                    )
                    continue
                if str(representation.status or "") != "available":
                    diagnostics.append({"code": "representation_not_available", **common})
                    continue
                if str(representation.source_snapshot_ref or "") != str(snapshot.snapshot_id or ""):
                    diagnostics.append({"code": "representation_snapshot_stale", **common})
                    continue
                if candidate_snapshot != str(representation.source_snapshot_ref or ""):
                    diagnostics.append({"code": "candidate_snapshot_mismatch", **common})
                    continue
                if candidate_digest != str(representation.content_digest or ""):
                    diagnostics.append({"code": "candidate_resource_digest_mismatch", **common})
                    continue
                if candidate_crs != str(representation.crs or ""):
                    diagnostics.append({"code": "candidate_crs_mismatch", **common})
                    continue
                dataset_ref = str(representation.dataset_ref or "").strip()
                source_feature_ref = str(
                    representation.source_feature_ref or ""
                ).strip()
                if not dataset_ref or not source_feature_ref:
                    diagnostics.append({
                        "code": "data_feature_ref_not_dataset_qualified",
                        "dataset_ref": dataset_ref,
                        "source_feature_ref": source_feature_ref,
                        **common,
                    })
                    continue
                # A bare feature id is not authoritative at SELECT: the same
                # id may exist in several DATA datasets.  Keep this lookup
                # explicitly dataset-qualified and do not fall back to the
                # catalog's ambiguous bare-ref path.
                feature = data_catalog.get_feature(
                    source_feature_ref,
                    dataset_ref=dataset_ref,
                )
                if feature is None:
                    diagnostics.append({
                        "code": "data_feature_not_found_for_representation",
                        "dataset_ref": dataset_ref,
                        "source_feature_ref": source_feature_ref,
                        **common,
                    })
                    continue
                feature_verdict = feature_admission_verdict(snapshot, feature)
                if not feature_verdict.admitted:
                    diagnostics.append({
                        "code": "source_feature_not_admitted_to_current_world",
                        "admission_reason": feature_verdict.reason,
                        "admission_input_role": feature_verdict.input_role,
                        "admission_status": feature_verdict.status,
                        "admission_decision_refs": list(feature_verdict.decision_refs),
                        "dataset_ref": dataset_ref,
                        "source_feature_ref": source_feature_ref,
                        **common,
                    })
                    continue
                geometry = _value(feature, "normalized_geometry")
                input_kind = _geometry_kind(geometry)
                if not _geometry_loadable(geometry, input_kind):
                    diagnostics.append({"code": "data_geometry_not_loadable", **common})
                    continue
                if operation == "read" and candidate_kind != input_kind:
                    diagnostics.append({
                        "code": "read_geometry_kind_mismatch",
                        "input_geometry_kind": input_kind,
                        "candidate_geometry_kind": candidate_kind,
                        **common,
                    })
                    continue
                if (
                    operation in {"read", "representation_derivation"}
                    and not operation_parameters
                    and not _candidate_geometry_matches_data(candidate, geometry)
                ):
                    diagnostics.append({
                        "code": "candidate_geometry_not_current_data_geometry",
                        **common,
                    })
                    continue
                capabilities = list(data_catalog.capabilities_for(resource_ref, required_capability) or [])
                matching_capabilities = [
                    item
                    for item in capabilities
                    if str(item.geometry_kind or "") == input_kind
                    and str(item.crs or "") == str(representation.crs or "")
                    and str(item.source_snapshot_ref or "")
                    == str(snapshot.snapshot_id or "")
                    and str(item.source_snapshot_ref or "")
                    == str(representation.source_snapshot_ref or "")
                    and str(item.content_digest or "")
                    == str(representation.content_digest or "")
                ]
                admitted_capabilities = [
                    item
                    for item in matching_capabilities
                    if is_admitted_capability(
                        snapshot,
                        item,
                        index=admission_index,
                    )
                ]
                capability = admitted_capabilities[0] if admitted_capabilities else None
                if capability is None:
                    if matching_capabilities:
                        diagnostics.append({
                            "code": "capability_not_admitted_to_current_world",
                            "resource_ref": resource_ref,
                            "required_capability": required_capability,
                            "capability_refs": [
                                str(item.capability_ref or "")
                                for item in matching_capabilities
                            ],
                            **common,
                        })
                    else:
                        diagnostics.append({
                            "code": "required_data_capability_missing",
                            "resource_ref": resource_ref,
                            "required_capability": required_capability,
                            **common,
                        })
                    continue
                output_kind = str(
                    (getattr(capability, "parameters_schema", None) or {}).get(
                        "output_geometry_kind", ""
                    )
                    or ""
                ).casefold()
                if output_kind and output_kind != candidate_kind:
                    diagnostics.append({
                        "code": "capability_output_geometry_kind_mismatch",
                        "capability_ref": str(capability.capability_ref or ""),
                        "capability_output_geometry_kind": output_kind,
                        "candidate_geometry_kind": candidate_kind,
                        **common,
                    })
                    continue
                decisions.append(SelectionDecision(
                    selection_ref=f"selection:{target_ref}:{candidate_ref}:{index}",
                    candidate_ref=candidate_ref,
                    target_ref=target_ref,
                    entity_ref=str((entity_refs or [str(representation.entity_ref or "")])[0]),
                    part_ref=part_ref,
                    representation_ref=representation_ref,
                    resource_ref=resource_ref,
                    geometry_ref=str(representation.geometry_ref or ""),
                    input_geometry_kind=input_kind,
                    geometry_kind=candidate_kind,
                    operation=operation,
                    operation_parameters=operation_parameters,
                    input_crs=str(representation.crs or ""),
                    output_crs=candidate_crs,
                    source_snapshot_ref=str(representation.source_snapshot_ref or ""),
                    resource_digest=str(representation.content_digest or ""),
                    capability_ref=str(capability.capability_ref or ""),
                    constraint_refs=_strings(_value(candidate, "relation_refs", [])),
                    evidence_refs=_strings([
                        *_strings(_value(grounding_binding, "evidence_refs", [])),
                        *_strings(_value(candidate, "evidence_refs", [])),
                    ]),
                    hard_constraint_status=str(_value(grounding_binding, "hard_constraint_status", "") or "unknown"),
                    availability_status=str(_value(grounding_binding, "availability_status", "") or "unknown"),
                    status="selected",
                    required_capability=required_capability,
                ))
    if diagnostics:
        raise SelectionBindingError(diagnostics)
    selected_candidates = {
        str(item)
        for selection in list(_value(scenario, "target_selections", []) or [])
        for item in list(_value(selection, "candidate_ids", []) or [])
        if str(item).strip()
    }
    decision_candidates = {item.candidate_ref for item in decisions}
    if decision_candidates != selected_candidates:
        raise SelectionBindingError([{
            "code": "selection_candidate_coverage_mismatch",
            "selected_candidates": sorted(selected_candidates),
            "decision_candidates": sorted(decision_candidates),
        }])
    scenario_id = str(_value(scenario, "scenario_id", "") or "")
    scenario_fingerprint = str(_value(scenario, "fingerprint", "") or "")
    return SelectionDecisionSet(
        decision_set_ref=f"selection-decisions:{scenario_id}",
        scenario_id=scenario_id,
        scenario_fingerprint=scenario_fingerprint,
        data_snapshot_ref=str(snapshot.snapshot_id or ""),
        data_catalog_digest=str(snapshot.digest or ""),
        decisions=decisions,
    )


__all__ = [
    "SelectionBindingError",
    "build_selection_decision_set",
]
