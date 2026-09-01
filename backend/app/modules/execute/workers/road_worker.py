"""Road materializer: write approved route geometry only."""

from __future__ import annotations

from app.modules.execute.execute_state import ExecuteAgentState
from app.modules.execute.road_parcel_materializer import (
    _target_matches,
    materialize_road_parcel_changes,
)
from app.modules.execute.workers.worker_common import _attach_feature_lineage, _candidate_capability_block, _execution_intent_from_plan, _intent_list, _plan_tasks, _scenario_features_for_layer, _task_enabled, _task_execution_result, _task_value
from app.contracts.execute.execution_plan_contracts import WorkerResult
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


_EXISTING_ROAD_ACTIONS = {"upgrade", "widen", "harden", "repair"}


def _road_value(target, field, default=None):
    if isinstance(target, dict):
        return target.get(field, default)
    return getattr(target, field, default)


def _road_strings(value) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _single_plan_task_id(state: ExecuteAgentState) -> str:
    """Read both typed ExecutionPlan and explicit v1 dict snapshots."""

    plan = getattr(state, "execution_plan", None)
    if isinstance(plan, dict):
        tasks = list(plan.get("worker_tasks") or [])
    else:
        tasks = list(getattr(plan, "worker_tasks", []) or [])
    if len(tasks) != 1:
        return ""
    task = tasks[0]
    return str(task.get("task_id", "") if isinstance(task, dict) else getattr(task, "task_id", ""))


def _road_kind(target) -> str | None:
    explicit = str(_road_value(target, "road_planning_kind", "") or "")
    if explicit in {"existing_road_intervention", "new_corridor"}:
        return explicit
    action = str(_road_value(target, "action", "") or "")
    if action == "new":
        return "new_corridor"
    if action in _EXISTING_ROAD_ACTIONS:
        return "existing_road_intervention"
    return None


def _resolved_endpoint(target, side: str) -> bool:
    endpoint = _road_value(target, f"{side}_endpoint")
    if isinstance(endpoint, dict):
        status = endpoint.get("resolution_status")
        coordinate = endpoint.get("coordinate")
        source = endpoint.get("source_artifact_ref")
        entity = endpoint.get("entity_ref") or endpoint.get("source_feature_id")
        evidence = endpoint.get("evidence_refs") or []
    elif endpoint is not None:
        status = getattr(endpoint, "resolution_status", None)
        coordinate = getattr(endpoint, "coordinate", None)
        source = getattr(endpoint, "source_artifact_ref", "")
        entity = getattr(endpoint, "entity_ref", None) or getattr(
            endpoint, "source_feature_id", ""
        )
        evidence = getattr(endpoint, "evidence_refs", None) or []
    else:
        return False
    return bool(
        status == "resolved"
        and coordinate is not None
        and str(source or "").strip()
        and str(entity or "").strip()
        and evidence
    )


def _routing_value(target, field):
    routing = _road_value(target, "routing_evidence")
    if isinstance(routing, dict):
        return routing.get(field)
    return getattr(routing, field, None) if routing is not None else None


def _road_evidence_refs(target) -> list[str]:
    refs = set(_road_strings(_road_value(target, "road_evidence_refs")))
    for side in ("start", "end"):
        endpoint = _road_value(target, f"{side}_endpoint")
        if isinstance(endpoint, dict):
            refs.update(_road_strings(endpoint.get("evidence_refs")))
            artifact = endpoint.get("source_artifact_ref")
        else:
            refs.update(_road_strings(getattr(endpoint, "evidence_refs", None)))
            artifact = getattr(endpoint, "source_artifact_ref", "") if endpoint else ""
        if str(artifact or "").strip():
            refs.add(str(artifact))
    for field in (
        "current_network",
        "dem",
        "land_friction",
        "hazard",
        "spatial_constraints",
    ):
        evidence = _routing_value(target, field)
        if isinstance(evidence, dict):
            artifact = evidence.get("artifact_ref")
        else:
            artifact = getattr(evidence, "artifact_ref", "") if evidence else ""
        if str(artifact or "").strip():
            refs.add(str(artifact))
    for value in _road_strings(_road_value(target, "existing_road_feature_ids")):
        refs.add(f"road-feature:{value}")
    for value in _road_strings(_road_value(target, "existing_road_segment_ids")):
        refs.add(f"road-segment:{value}")
    for value in _road_strings(
        [
            *_road_strings(_road_value(target, "path_bsms")),
            *_road_strings(_road_value(target, "candidate_bsms")),
        ]
    ):
        refs.add(f"parcel:{value}")
    return sorted(refs)


def _road_failure_type(target) -> tuple[str, str]:
    kind = _road_kind(target)
    if kind is None:
        return "road_unresolved", "source_contract_missing"
    if kind == "new_corridor":
        if not (_resolved_endpoint(target, "start") and _resolved_endpoint(target, "end")):
            return "road_anchor_unresolved", "anchor_missing"
        if not any(
            _routing_value(target, field) is not None
            for field in ("current_network", "dem", "land_friction")
        ):
            return "road_unresolved", "source_contract_missing"
        return "road_route_failed", "route_failed"
    has_binding = bool(
        _road_strings(_road_value(target, "existing_road_feature_ids"))
        or _road_strings(_road_value(target, "existing_road_segment_ids"))
    )
    if not has_binding or _routing_value(target, "current_network") is None:
        return "road_unresolved", "source_contract_missing"
    return "road_route_failed", "route_failed"


def _normalize_road_unresolved_findings(
    road_targets,
    *,
    produced_target_ids: set[str],
    unresolved_items,
    error: str = "",
) -> list[dict]:
    """Bind every unresolved road finding to one declared road target."""

    explicit_unresolved: set[str] = set()
    messages: list[str] = []
    raw_by_target: dict[str, list[dict]] = {}
    unbound_items: list[dict] = []
    for item in list(unresolved_items or []):
        if not isinstance(item, dict):
            messages.append(str(item))
            continue
        item_targets: set[str] = set()
        for field in ("target_id", "project_id", "source_project_id"):
            item_targets.update(_road_strings(item.get(field)))
        explicit_unresolved.update(item_targets)
        if item_targets:
            for item_target in item_targets:
                raw_by_target.setdefault(item_target, []).append(item)
        else:
            unbound_items.append(item)
        messages.extend(_road_strings(item.get("message")))
    if error:
        messages.append(str(error))
    findings: list[dict] = []
    for target in road_targets:
        target_id = str(_road_value(target, "target_id", "") or "").strip()
        if not target_id:
            continue
        if target_id in produced_target_ids and target_id not in explicit_unresolved:
            continue
        code, reason_code = _road_failure_type(target)
        related_items = [*raw_by_target.get(target_id, []), *unbound_items]
        diagnostics = [
            diagnostic
            for item in related_items
            for diagnostic in list(item.get("diagnostics") or [])
            if isinstance(diagnostic, dict)
        ]
        diagnostic_codes = sorted({
            str(value)
            for item in related_items
            for value in list(item.get("diagnostic_codes") or [])
            if str(value).strip()
        })
        if any(
            value in {
                "ROAD_CANDIDATE_NOT_GENERATED",
                "ROAD_ALL_CANDIDATES_REJECTED",
                "ROAD_STAGE3_GATE_BLOCKED",
                "ROAD_ROUTE_FAILED",
            }
            for value in diagnostic_codes
        ):
            code, reason_code = "road_route_failed", "route_failed"
        evidence_refs = set(_road_evidence_refs(target))
        for item in related_items:
            evidence_refs.update(_road_strings(item.get("evidence_refs")))
        for diagnostic in diagnostics:
            evidence_refs.update(_road_strings(diagnostic.get("evidence_refs")))
        findings.append(
            {
                "type": "RoadUnresolved",
                "violation_id": f"{code}:{target_id}",
                "code": code,
                "reason_code": reason_code,
                "target_id": target_id,
                "source_project_id": str(
                    _road_value(target, "source_project_id", "") or ""
                ),
                "affected_bsms": sorted(
                    set(
                        _road_strings(_road_value(target, "path_bsms"))
                        + _road_strings(_road_value(target, "candidate_bsms"))
                    )
                ),
                "evidence_refs": sorted(evidence_refs),
                "diagnostic_codes": diagnostic_codes,
                "diagnostics": diagnostics,
                "message": "; ".join(sorted(set(messages)))
                or "No planned-road geometry was produced for this target.",
            }
        )
    return findings


def _road_worker(state: ExecuteAgentState) -> WorkerResult:
    """Road worker: planned road network generation.

    EXECUTE only materializes an accepted, target-bound route.  Route search
    and candidate filtering belong to the pre-approval planning provider.  A
    task without an approved execution geometry therefore fails closed before
    any planner or generator can be consulted.
    """
    if not _task_enabled(state, "road"):
        return WorkerResult(worker_type="road")

    intent = _execution_intent_from_plan(state)
    road_targets = _intent_list(intent, "road_targets")
    if not road_targets:
        return WorkerResult(
            worker_type="road",
            diagnostics=[{
                "code": "road_target_identity_missing",
                "message": "Road worker was routed without any declared road target.",
            }],
        )

    target_ids = {str(road.target_id) for road in road_targets}
    road_tasks_by_target: dict[str, list[object]] = {}
    for task in _plan_tasks(state, {"road_construction"}):
        road_tasks_by_target.setdefault(
            str(_task_value(task, "target_id", "") or ""), []
        ).append(task)
    provenance_keys = (
        "target_id", "target_ids", "project_id", "source_project_id",
        "source_id", "source_intent_ids", "grouped_source_ids",
    )

    def values(value):
        if value is None:
            return set()
        if isinstance(value, (list, tuple, set)):
            return {str(item) for item in value}
        return {str(value)}

    def layer_target_ids(layers):
        produced = set()
        for layer in layers:
            data = layer.get("data") or layer
            for feature in data.get("features") or []:
                properties = feature.get("properties") or {}
                for key in provenance_keys:
                    produced.update(values(properties.get(key)))
        return produced & target_ids

    def item_target_ids(items):
        matched = {}
        for road in road_targets:
            target_id = str(road.target_id)
            matched[target_id] = [
                item for item in items
                if isinstance(item, dict)
                and target_id in {
                    value
                    for key in provenance_keys
                    for value in values(item.get(key))
                }
            ]
        return matched

    def task_results(layers, unresolved_items=None, error=""):
        unresolved_by_target = item_target_ids(list(unresolved_items or []))
        produced = layer_target_ids(layers)
        results = []
        occurrence_by_target: dict[str, int] = {}
        for road in road_targets:
            target_id = str(road.target_id)
            occurrence = occurrence_by_target.get(target_id, 0)
            occurrence_by_target[target_id] = occurrence + 1
            matching_tasks = road_tasks_by_target.get(target_id, [])
            matching_task = matching_tasks[min(occurrence, len(matching_tasks) - 1)] if matching_tasks else None
            diagnostics = list(unresolved_by_target[target_id])
            succeeded = target_id in produced and not diagnostics and not error
            if not succeeded and not diagnostics:
                diagnostics.extend(
                    _normalize_road_unresolved_findings(
                        [road],
                        produced_target_ids=produced,
                        unresolved_items=[],
                        error=error,
                    )
                )
            result = _task_execution_result(
                state,
                "road_construction",
                target_id,
                task_id=str(_task_value(matching_task, "task_id", "") or "") if matching_task else "",
                candidate_id=str(_task_value(matching_task, "candidate_id", "") or "") if matching_task else "",
                status="succeeded" if succeeded else "failed",
                diagnostics=diagnostics,
                errors=[error] if error else [],
            )
            if result is not None:
                results.append(result)
        return results

    def scenario_features(layers):
        return [
            item
            for layer in layers
            for item in _scenario_features_for_layer(
                state, layer, generation_operation="road_worker"
            )
        ]

    def with_lineage(result, features):
        _attach_feature_lineage(result, features)
        return result

    def with_parcel_changes(result, layers):
        """Attach transport-land changes to new-corridor road output.

        Existing-road upgrade/repair/hardening keeps its authoritative
        current-road geometry and does not claim a new land-use polygon.
        A new corridor or explicit widening, however, is not executable
        until its accepted line is intersected with the current bundle
        land-use layer and materialized as transport land.  This keeps the
        line and polygon outputs in one road worker while preserving their
        separate contracts.
        """
        explicit_parcel_binding = str(
            getattr(state, "parcel_compatibility_mode", "") or ""
        ).strip() == "legacy_bsm"
        if not explicit_parcel_binding:
            return result
        changes = []
        parcel_diagnostics = []
        try:
            from app.infrastructure.export.delivery_snapshot import (
                canonical_gis_data_from_workspace,
            )

            gis_data = canonical_gis_data_from_workspace(state.spatial_workspace)
            landuse_payload = gis_data.get("landuse_current_geojson") or {}
        except Exception as exc:
            landuse_payload = {}
            parcel_diagnostics.append({
                "code": "road_landuse_source_unavailable",
                "target_id": "",
                "message": "Current land-use source could not be loaded.",
                "exception_type": type(exc).__name__,
            })
        if not landuse_payload.get("features"):
            parcel_diagnostics.append({
                "code": "road_landuse_source_missing",
                "target_id": "",
                "message": "New-corridor road materialization requires current land-use features.",
            })
        # A DATA-only baseline may contain arbitrary polygons/lines but no
        # cadastral BSM/DLBM classification.  The accepted road line remains
        # a valid executable output; only the optional transport-land parcel
        # split is deferred.  Never fabricate a parcel identity or land-use
        # code from generic attributes.
        generic_baseline = bool(landuse_payload.get("features")) and not any(
            isinstance(feature, dict)
            and any(
                str((feature.get("properties") or {}).get(key) or "").strip()
                for key in ("bsm", "BSM", "dlbm", "DLBM")
            )
            for feature in (landuse_payload.get("features") or [])
        )
        if generic_baseline:
            return result
        for road in road_targets:
            target_id = str(_road_value(road, "target_id", "") or "")
            action = str(_road_value(road, "action", "") or "")
            requires_landuse = (
                _road_kind(road) == "new_corridor"
                or action == "widen"
            )
            if not requires_landuse:
                continue
            if not any(
                _target_matches(feature, target_id)
                for layer in layers
                if str(layer.get("layerType") or layer.get("layer_type") or "")
                in {"planned_road", "planned_road_candidates"}
                for feature in ((layer.get("data") or layer.get("geojson") or layer).get("features") or [])
                if isinstance(feature, dict)
            ):
                # Route generation already records the target-bound failure;
                # do not add a second line-missing finding here.
                continue
            target_changes, diagnostics = materialize_road_parcel_changes(
                target=road,
                layers=list(layers),
                landuse_payload=landuse_payload,
                target_id=target_id,
                evidence_refs=_road_evidence_refs(road),
                feature_bsms=_road_strings(_road_value(road, "path_bsms")),
                source_feature_ids=_road_strings(
                    _road_value(road, "existing_road_feature_ids")
                ),
                l1_snapshot_ref=str(_road_value(road, "l1_snapshot_ref", "") or ""),
                bundle_snapshot_digest=str(
                    _road_value(road, "bundle_snapshot_digest", "") or ""
                ),
            )
            changes.extend(target_changes)
            parcel_diagnostics.extend(
                {**item, "target_id": item.get("target_id") or target_id}
                for item in diagnostics
            )
        if parcel_diagnostics:
            result.unresolved_items = list(result.unresolved_items or []) + parcel_diagnostics
            diagnostic_by_target = {}
            for item in parcel_diagnostics:
                diagnostic_by_target.setdefault(
                    str(item.get("target_id") or ""), []
                ).append(item)
            for task_result in result.task_results:
                target_id = str(getattr(task_result, "target_id", "") or "")
                diagnostics = diagnostic_by_target.get(target_id)
                if not diagnostics:
                    continue
                task_result.status = "failed"
                task_result.diagnostics = list(task_result.diagnostics or []) + diagnostics
        result.parcel_changes = list(result.parcel_changes or []) + changes
        return result

    # The only accepted route source is the frozen candidate geometry carried
    # by the approval-bound task.  ``candidate_geometry_by_id`` is populated
    # from the same grounded snapshot that produced the approval.
    candidate_geometry_by_id = getattr(state, "candidate_geometry_by_id", {}) or {}
    accepted_layers = []
    for task in list(getattr(getattr(state, "execution_plan", None), "worker_tasks", None) or []):
        if str(getattr(task, "target_type", "") or "") != "road":
            continue
        candidate_id = str(getattr(task, "candidate_id", "") or "")
        candidate = candidate_geometry_by_id.get(candidate_id)
        geometry_wkt = str(getattr(candidate, "wkt", "") or "")
        if isinstance(candidate, dict):
            geometry_wkt = str(candidate.get("wkt") or candidate.get("geometry_wkt") or "")
        if not candidate_id or not geometry_wkt:
            continue
        role = str(
            candidate.get("role", "") if isinstance(candidate, dict)
            else getattr(candidate, "role", "")
        )
        if role != "execution_geometry":
            continue
        if _candidate_capability_block(state, candidate):
            continue
        try:
            from shapely import wkt as shapely_wkt
            from shapely.geometry import mapping as shapely_mapping
            geometry = shapely_mapping(shapely_wkt.loads(geometry_wkt))
        except Exception:
            continue
        target_id = str(getattr(task, "target_id", "") or "")
        accepted_layers.append({
            "layerType": "planned_road",
            "layerName": "规划道路",
            "data": {"type": "FeatureCollection", "features": [{
                "type": "Feature",
                "properties": {
                    "target_id": target_id,
                    "candidate_id": candidate_id,
                    "scenario_id": str(getattr(task, "scenario_id", "") or ""),
                    "source_feature_ids": list(getattr(task, "target_binding", {}).get("source_feature_ids", []) or []),
                    "resource_refs": list(getattr(task, "resource_refs", None) or getattr(task, "target_binding", {}).get("resource_refs", []) or []),
                    "representation_refs": list(getattr(task, "representation_refs", None) or getattr(task, "target_binding", {}).get("representation_refs", []) or []),
                    "evidence_refs": list(getattr(task, "evidence_refs", []) or []),
                    "roadbed_width_m": getattr(task, "target_binding", {}).get("roadbed_width_m", None),
                    "pavement_width_m": getattr(task, "target_binding", {}).get("pavement_width_m", None),
                    "materialization_role": "approved_route_materialize",
                },
                "geometry": geometry,
            }]},
        })
    normalized_unresolved = _normalize_road_unresolved_findings(
        road_targets,
        produced_target_ids=layer_target_ids(accepted_layers),
        unresolved_items=[] if accepted_layers else [{
            "message": "Approved route geometry is missing; route planning is not available in EXECUTE.",
        }],
    )
    if accepted_layers:
        features = scenario_features(accepted_layers)
        return with_lineage(with_parcel_changes(WorkerResult(
            worker_type="road",
            task_results=task_results(accepted_layers, normalized_unresolved),
            layers=accepted_layers,
            unresolved_items=normalized_unresolved,
            diagnostics=[{"code": "approved_route_materializer", "candidate_count": len(accepted_layers)}],
            scenario_features=features,
            task_id=_single_plan_task_id(state),
        ), accepted_layers), features)

    logger.warning("[EXECUTE:road] no approved route geometry; road worker unresolved")
    unresolved_items = _normalize_road_unresolved_findings(
        road_targets,
        produced_target_ids=set(),
        unresolved_items=[{
            "message": "No approved route geometry was provided by SELECT.",
        }],
    )
    return WorkerResult(
        worker_type="road",
        task_results=task_results([], unresolved_items),
        unresolved_items=unresolved_items,
        diagnostics=[{"code": "approved_route_missing", "materializer_only": True}],
    )
