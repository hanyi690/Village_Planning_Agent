"""Fail-closed preparation of evidence-backed road planning candidates.

This module is intentionally upstream of Stage 2.6 and route generation.  It
does not parse prose, choose a village-wide fallback, fabricate endpoints, or
draw geometry.  Its sole responsibility is to prove that a road target has the
minimum authoritative evidence required by its planning kind.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from app.contracts.domain.road_planning import (
    ExistingRoadPlanningInput,
    NewCorridorPlanningInput,
    RoadArtifactEvidence,
    RoadCandidatePreparationBatch,
    RoadCandidatePreparationResult,
    RoadEndpointEvidence,
    RoadEvidenceCatalog,
    RoadPlanningKind,
    RoadPreparationDiagnostic,
    RoadRoutingEvidence,
)


_EXISTING_ACTIONS = {"upgrade", "widen", "harden", "repair"}


def _value(target: Any, name: str, default: Any = None) -> Any:
    if isinstance(target, Mapping):
        return target.get(name, default)
    return getattr(target, name, default)


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value)
    return list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


def _diagnostic(
    code: str,
    message: str,
    field_path: str,
    *,
    severity: str = "error",
    evidence_refs: Sequence[str] = (),
) -> RoadPreparationDiagnostic:
    return RoadPreparationDiagnostic(
        code=code,
        severity=severity,
        message=message,
        field_path=field_path,
        evidence_refs=list(evidence_refs),
    )


def _planning_kind(
    target: Any,
    diagnostics: list[RoadPreparationDiagnostic],
) -> RoadPlanningKind | None:
    action = str(_value(target, "action", "") or "").strip()
    explicit = _value(target, "road_planning_kind")
    inferred: RoadPlanningKind | None
    if action == "new":
        inferred = "new_corridor"
    elif action in _EXISTING_ACTIONS:
        inferred = "existing_road_intervention"
    else:
        inferred = None
        diagnostics.append(
            _diagnostic(
                "ROAD_ACTION_UNSUPPORTED",
                f"Road action {action!r} is not executable as a new corridor "
                "or existing-road intervention.",
                "action",
            )
        )
    if explicit and explicit not in {"new_corridor", "existing_road_intervention"}:
        diagnostics.append(
            _diagnostic(
                "ROAD_PLANNING_KIND_INVALID",
                f"Road planning kind {explicit!r} is outside the closed set.",
                "road_planning_kind",
            )
        )
    if explicit and inferred and explicit != inferred:
        diagnostics.append(
            _diagnostic(
                "ROAD_KIND_ACTION_MISMATCH",
                f"Road planning kind {explicit!r} conflicts with action {action!r}.",
                "road_planning_kind",
            )
        )
    if explicit in {"new_corridor", "existing_road_intervention"}:
        return explicit
    return inferred


def _routing_evidence(target: Any, catalog: RoadEvidenceCatalog) -> RoadRoutingEvidence:
    raw = _value(target, "routing_evidence")
    if isinstance(raw, RoadRoutingEvidence):
        routing = raw.model_copy(deep=True)
    elif isinstance(raw, Mapping):
        routing = RoadRoutingEvidence.model_validate(raw)
    else:
        routing = RoadRoutingEvidence()
    catalog_routing = catalog.routing_evidence
    updates: dict[str, Any] = {}
    for field_name in (
        "current_network",
        "dem",
        "land_friction",
        "hazard",
        "spatial_constraints",
    ):
        if getattr(routing, field_name) is None:
            available = getattr(catalog_routing, field_name)
            if available is not None:
                updates[field_name] = available
    if routing.current_network is None and catalog.current_network is not None:
        updates["current_network"] = catalog.current_network
    if updates:
        routing = routing.model_copy(update=updates)
    return routing


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _read_feature_collection(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping) or payload.get("type") != "FeatureCollection":
        raise ValueError(f"Road evidence artifact is not a FeatureCollection: {path}")
    features = payload.get("features") or []
    if not isinstance(features, list):
        raise ValueError(f"Road evidence artifact has invalid features: {path}")
    return [item for item in features if isinstance(item, Mapping)]


def _current_feature_id(feature: Mapping[str, Any]) -> str:
    properties = feature.get("properties") or {}
    if not isinstance(properties, Mapping):
        properties = {}
    return str(
        properties.get("bsm")
        or properties.get("BSM")
        or properties.get("feature_id")
        or feature.get("id")
        or ""
    ).strip()


def build_road_evidence_catalog(
    *,
    road_edges_path: str | Path,
    current_roads_path: str | Path | None = None,
    endpoint_entities: Mapping[str, RoadEndpointEvidence | Mapping[str, Any]] | None = None,
    routing_evidence: RoadRoutingEvidence | Mapping[str, Any] | None = None,
) -> RoadEvidenceCatalog:
    """Build the immutable id catalog used by fail-closed preparation.

    Stage-1 ``edge_id`` values and explicit source ``bsm``/``feature_id``/GeoJSON
    ids are the only accepted road identifiers. Human labels and array indexes
    are intentionally not promoted to identifiers.
    """

    edges_path = Path(road_edges_path).expanduser().resolve()
    if not edges_path.is_file():
        raise FileNotFoundError(edges_path)
    edge_features = _read_feature_collection(edges_path)
    segment_ids = {
        str((feature.get("properties") or {}).get("edge_id") or "").strip()
        for feature in edge_features
        if isinstance(feature.get("properties") or {}, Mapping)
    }
    segment_ids.discard("")

    feature_ids: set[str] = set()
    if current_roads_path is not None:
        current_path = Path(current_roads_path).expanduser().resolve()
        if not current_path.is_file():
            raise FileNotFoundError(current_path)
        feature_ids = {
            identifier
            for feature in _read_feature_collection(current_path)
            if (identifier := _current_feature_id(feature))
        }

    network = RoadArtifactEvidence(
        role="current_road_network",
        artifact_ref=edges_path.as_uri(),
        checksum=_sha256_file(edges_path),
    )
    if isinstance(routing_evidence, RoadRoutingEvidence):
        routing = routing_evidence.model_copy(deep=True)
    elif isinstance(routing_evidence, Mapping):
        routing = RoadRoutingEvidence.model_validate(routing_evidence)
    else:
        routing = RoadRoutingEvidence()
    if routing.current_network is None:
        routing = routing.model_copy(update={"current_network": network})

    entities: dict[str, RoadEndpointEvidence] = {}
    for entity_ref, raw in (endpoint_entities or {}).items():
        endpoint = (
            raw
            if isinstance(raw, RoadEndpointEvidence)
            else RoadEndpointEvidence.model_validate(raw)
        )
        entities[str(entity_ref)] = endpoint
    return RoadEvidenceCatalog(
        current_network=network,
        routing_evidence=routing,
        current_road_feature_ids=feature_ids,
        current_road_segment_ids=segment_ids,
        endpoint_entities=entities,
    )


def new_corridor_inputs_to_stage2_targets(
    planning_inputs: Sequence[NewCorridorPlanningInput],
) -> list[dict[str, Any]]:
    """Adapt validated new corridors to the legacy Stage-2 file boundary.

    The adapter carries complete endpoint evidence. It never derives an
    endpoint from a place label, bbox, candidate parcel, or village centroid.
    """

    targets: list[dict[str, Any]] = []
    for planning_input in planning_inputs:
        start = planning_input.start_endpoint
        end = planning_input.end_endpoint
        targets.append(
            {
                "typed_contract_version": "road-planning-input-v1",
                "target_id": planning_input.target_id,
                "source_project_id": planning_input.source_project_id,
                "road_planning_kind": planning_input.planning_kind,
                "action": planning_input.action,
                "road_level": planning_input.road_level,
                "length_m": planning_input.length_m,
                "roadbed_width_m": planning_input.roadbed_width_m,
                "pavement_width_m": planning_input.pavement_width_m,
                "start_anchor": start.coordinate,
                "end_anchor": end.coordinate,
                "start_entity_ref": start.entity_ref or start.source_feature_id,
                "end_entity_ref": end.entity_ref or end.source_feature_id,
                "start_endpoint": start.model_dump(mode="json"),
                "end_endpoint": end.model_dump(mode="json"),
                "routing_evidence": planning_input.routing_evidence.model_dump(mode="json"),
                "requires_human_confirmation": False,
            }
        )
    return targets


def _endpoint_from_catalog(
    target: Any,
    side: str,
    catalog: RoadEvidenceCatalog,
    diagnostics: list[RoadPreparationDiagnostic],
) -> RoadEndpointEvidence | None:
    raw = _value(target, f"{side}_endpoint")
    if raw is not None:
        endpoint = (
            raw
            if isinstance(raw, RoadEndpointEvidence)
            else RoadEndpointEvidence.model_validate(raw)
        )
        if endpoint.resolution_status != "resolved":
            diagnostics.append(
                _diagnostic(
                    "ROAD_ENDPOINT_NOT_RESOLVED",
                    f"The {side} endpoint is {endpoint.resolution_status}, not resolved.",
                    f"{side}_endpoint.resolution_status",
                    evidence_refs=endpoint.evidence_refs,
                )
            )
            return None
        if endpoint.role != side:
            diagnostics.append(
                _diagnostic(
                    "ROAD_ENDPOINT_ROLE_MISMATCH",
                    f"The {side} endpoint carries role {endpoint.role!r}.",
                    f"{side}_endpoint.role",
                    evidence_refs=endpoint.evidence_refs,
                )
            )
            return None
        return endpoint

    entity_ref = str(_value(target, f"{side}_entity_ref", "") or "").strip()
    if entity_ref:
        endpoint = catalog.endpoint_entities.get(entity_ref)
        if endpoint is None:
            diagnostics.append(
                _diagnostic(
                    "ROAD_ENDPOINT_ENTITY_NOT_FOUND",
                    f"The {side} connection entity {entity_ref!r} has no "
                    "resolved geometry evidence.",
                    f"{side}_entity_ref",
                )
            )
            return None
        if endpoint.resolution_status != "resolved":
            diagnostics.append(
                _diagnostic(
                    "ROAD_ENDPOINT_NOT_RESOLVED",
                    f"The {side} connection entity is {endpoint.resolution_status}.",
                    f"{side}_entity_ref",
                    evidence_refs=endpoint.evidence_refs,
                )
            )
            return None
        return endpoint.model_copy(update={"role": side})

    if _value(target, f"{side}_anchor") is not None:
        diagnostics.append(
            _diagnostic(
                "ROAD_ENDPOINT_PROVENANCE_MISSING",
                f"The {side} anchor has coordinates but no authoritative "
                "entity/feature provenance.",
                f"{side}_anchor",
            )
        )
        return None

    connects = _strings(_value(target, "connects"))
    if connects:
        diagnostics.append(
            _diagnostic(
                "ROAD_CONNECTION_ENTITIES_UNRESOLVED",
                "Road connection labels must be resolved to typed entity refs "
                "before candidate generation.",
                "connects",
            )
        )
    else:
        diagnostics.append(
            _diagnostic(
                "ROAD_ENDPOINT_MISSING",
                f"The {side} endpoint is missing.",
                f"{side}_endpoint",
            )
        )
    return None


def _base_fields(target: Any) -> dict[str, Any]:
    return {
        "target_id": str(_value(target, "target_id", "") or ""),
        "source_project_id": str(_value(target, "source_project_id", "") or ""),
        "road_level": str(_value(target, "road_level", "") or ""),
        "length_m": _value(target, "length_m"),
        "roadbed_width_m": _value(target, "roadbed_width_m"),
        "pavement_width_m": _value(target, "pavement_width_m"),
    }


def _prepare_existing(
    target: Any,
    catalog: RoadEvidenceCatalog,
    routing: RoadRoutingEvidence,
    diagnostics: list[RoadPreparationDiagnostic],
) -> ExistingRoadPlanningInput | None:
    feature_ids = _strings(_value(target, "existing_road_feature_ids"))
    segment_ids = _strings(_value(target, "existing_road_segment_ids"))
    if not feature_ids and not segment_ids:
        diagnostics.append(
            _diagnostic(
                "ROAD_EXISTING_BINDING_MISSING",
                "Existing-road work requires authoritative current-road feature or segment ids.",
                "existing_road_segment_ids",
            )
        )
    missing_features = sorted(set(feature_ids) - catalog.current_road_feature_ids)
    if missing_features:
        diagnostics.append(
            _diagnostic(
                "ROAD_EXISTING_FEATURE_NOT_FOUND",
                "Current-road feature ids are not present in the authoritative "
                f"catalog: {missing_features}.",
                "existing_road_feature_ids",
            )
        )
    missing_segments = sorted(set(segment_ids) - catalog.current_road_segment_ids)
    if missing_segments:
        diagnostics.append(
            _diagnostic(
                "ROAD_EXISTING_SEGMENT_NOT_FOUND",
                "Current-road segment ids are not present in the authoritative "
                f"network: {missing_segments}.",
                "existing_road_segment_ids",
            )
        )
    if routing.current_network is None:
        diagnostics.append(
            _diagnostic(
                "ROAD_CURRENT_NETWORK_EVIDENCE_MISSING",
                "Existing-road work requires the versioned current-road network artifact.",
                "routing_evidence.current_network",
            )
        )
    if any(item.severity == "error" for item in diagnostics):
        return None
    return ExistingRoadPlanningInput(
        **_base_fields(target),
        action=str(_value(target, "action") or ""),
        existing_road_feature_ids=feature_ids,
        existing_road_segment_ids=segment_ids,
        road_evidence_refs=_strings(_value(target, "road_evidence_refs")),
        routing_evidence=routing,
    )


def _prepare_new(
    target: Any,
    catalog: RoadEvidenceCatalog,
    routing: RoadRoutingEvidence,
    diagnostics: list[RoadPreparationDiagnostic],
) -> NewCorridorPlanningInput | None:
    start = _endpoint_from_catalog(target, "start", catalog, diagnostics)
    end = _endpoint_from_catalog(target, "end", catalog, diagnostics)
    if start is not None and end is not None:
        if (
            start.coordinate == end.coordinate
            or (start.entity_ref and start.entity_ref == end.entity_ref)
        ):
            diagnostics.append(
                _diagnostic(
                    "ROAD_ENDPOINTS_NOT_DISTINCT",
                    "New-corridor start and end endpoints must be distinct.",
                    "start_endpoint,end_endpoint",
                    evidence_refs=[*start.evidence_refs, *end.evidence_refs],
                )
            )
    if not routing.has_routing_basis:
        diagnostics.append(
            _diagnostic(
                "ROAD_ROUTING_EVIDENCE_MISSING",
                "New-corridor planning requires a versioned current network, "
                "DEM, or land-friction artifact.",
                "routing_evidence",
            )
        )
    elif routing.dem is None and routing.land_friction is None:
        diagnostics.append(
            _diagnostic(
                "ROAD_TERRAIN_COST_EVIDENCE_MISSING",
                "No DEM or land-friction artifact is attached; only "
                "network-based routing is available.",
                "routing_evidence",
                severity="warning",
            )
        )
    if any(item.severity == "error" for item in diagnostics):
        return None
    assert start is not None and end is not None
    return NewCorridorPlanningInput(
        **_base_fields(target),
        start_endpoint=start,
        end_endpoint=end,
        routing_evidence=routing,
    )


def prepare_road_candidate(
    target: Any,
    catalog: RoadEvidenceCatalog,
) -> RoadCandidatePreparationResult:
    """Validate one road target and return either a typed input or unresolved."""

    target_id = str(_value(target, "target_id", "") or "")
    diagnostics: list[RoadPreparationDiagnostic] = []
    kind = _planning_kind(target, diagnostics)
    planning_input = None
    try:
        routing = _routing_evidence(target, catalog)
        if kind == "existing_road_intervention":
            planning_input = _prepare_existing(target, catalog, routing, diagnostics)
        elif kind == "new_corridor":
            planning_input = _prepare_new(target, catalog, routing, diagnostics)
    except ValidationError as exc:
        diagnostics.append(
            _diagnostic(
                "ROAD_PLANNING_INPUT_INVALID",
                str(exc),
                "road_planning_input",
            )
        )
        planning_input = None
    return RoadCandidatePreparationResult(
        target_id=target_id,
        planning_kind=kind,
        status="ready" if planning_input is not None else "unresolved",
        planning_input=planning_input,
        diagnostics=diagnostics,
    )


def prepare_road_candidates(
    targets: Sequence[Any],
    catalog: RoadEvidenceCatalog,
) -> RoadCandidatePreparationBatch:
    """Prepare a batch without substituting candidates for unresolved targets."""

    results = [prepare_road_candidate(target, catalog) for target in targets]
    ready_inputs = [
        result.planning_input
        for result in results
        if result.status == "ready" and result.planning_input is not None
    ]
    unresolved_target_ids = [
        result.target_id for result in results if result.status == "unresolved"
    ]
    return RoadCandidatePreparationBatch(
        results=results,
        ready_inputs=ready_inputs,
        unresolved_target_ids=unresolved_target_ids,
    )


__all__ = [
    "build_road_evidence_catalog",
    "new_corridor_inputs_to_stage2_targets",
    "prepare_road_candidate",
    "prepare_road_candidates",
]
