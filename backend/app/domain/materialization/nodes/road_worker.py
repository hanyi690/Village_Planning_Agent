"""Road worker node: planned road network generation."""

from __future__ import annotations

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.worker_common import _attach_feature_lineage, _execution_intent_from_plan, _intent_list, _scenario_features_for_layer, _task_enabled, _task_execution_result
from app.contracts.workflow.execution_plan_contracts import WorkerResult
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

    Primary path: the injected ``RoadPlannerPort`` when available; otherwise the
    remote Stage 0-6 generator (confirmation gates 2.6/3/4, ported from
    origin/agent/kg-schema-gis-handoff-20260730), falling back to the
    lightweight local ``plan_roads``. If declared road targets still produce no
    geometry, the worker records an unresolved item (formal output is gated by
    the outer VALIDATE).
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
        if len(road_targets) == 1 and layers and not produced:
            produced = {str(road_targets[0].target_id)}
        results = []
        for road in road_targets:
            target_id = str(road.target_id)
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

    ports = getattr(state, "ports", None)
    planner = getattr(ports, "road_planner", None) if ports is not None else None
    if planner is not None:
        try:
            if planner.is_available():
                plan_result = planner.plan(state)
                layers = list(getattr(plan_result, "layers", None) or [])
                unresolved_items = _normalize_road_unresolved_findings(
                    road_targets,
                    produced_target_ids=layer_target_ids(layers),
                    unresolved_items=list(
                        getattr(plan_result, "unresolved_items", None) or []
                    ),
                )
                features = scenario_features(layers)
                return with_lineage(WorkerResult(
                    worker_type="road",
                    task_results=task_results(layers, unresolved_items),
                    layers=layers,
                    unresolved_items=unresolved_items,
                    diagnostics=[{"code": "road_planner_port", "available": True}],
                    scenario_features=features,
                    task_id=_single_plan_task_id(state),
                ), features)
        except Exception as e:
            logger.warning("[EXECUTE:road] planner port failed: %s", e)

    generator_error = ""
    generator_unresolved_items = []
    try:
        from app.domain.materialization.road_generator import (
            execute_road_planning_from_agent_state,
        )

        result = execute_road_planning_from_agent_state(state)
        layers = result.get("layout_layers") or []
        generator_unresolved_items = list(result.get("unresolved_items") or [])
        formal_road_layers = [
            layer
            for layer in layers
            if (layer.get("layerType") or layer.get("layer_type"))
            in {"planned_road", "planned_road_candidates"}
            and ((layer.get("data") or {}).get("features") or layer.get("features"))
        ]
        if formal_road_layers:
            for layer in formal_road_layers:
                data = layer.get("data")
                if isinstance(data, dict):
                    data.pop("crs", None)
                layer.pop("crs", None)
            logger.info(
                "[EXECUTE:road] stage generator: ran=%s targets=%d layers=%d",
                result.get("ran"), result.get("road_target_count", 0), len(layers),
            )
            normalized_unresolved = _normalize_road_unresolved_findings(
                road_targets,
                produced_target_ids=layer_target_ids(formal_road_layers),
                unresolved_items=generator_unresolved_items,
            )
            features = scenario_features(formal_road_layers)
            return with_lineage(WorkerResult(
                worker_type="road",
                task_results=task_results(
                    formal_road_layers,
                    normalized_unresolved,
                ),
                layers=list(layers),
                unresolved_items=normalized_unresolved,
                diagnostics=[{"code": "road_stage_generator", "ran": bool(result.get("ran"))}],
                scenario_features=features,
                task_id=_single_plan_task_id(state),
            ), features)
        logger.info("[EXECUTE:road] stage generator skipped: %s", result.get("reason"))
        if generator_unresolved_items:
            normalized_unresolved = _normalize_road_unresolved_findings(
                road_targets,
                produced_target_ids=set(),
                unresolved_items=generator_unresolved_items,
            )
            return WorkerResult(
                worker_type="road",
                task_results=task_results([], normalized_unresolved),
                layers=list(layers),
                unresolved_items=normalized_unresolved,
                diagnostics=[{"code": "road_stage_generator", "ran": bool(result.get("ran"))}],
            )
    except Exception as e:
        generator_error = str(e)
        logger.warning(
            "[EXECUTE:road] stage generator failed: %s", e
        )

    logger.warning("[EXECUTE:road] no usable road plan produced; road worker unresolved")
    unresolved_items = _normalize_road_unresolved_findings(
        road_targets,
        produced_target_ids=set(),
        unresolved_items=[{
            "message": "No road plan produced: stage generator unavailable or failed.",
        }],
        error=generator_error,
    )
    return WorkerResult(
        worker_type="road",
        task_results=task_results([], unresolved_items, generator_error),
        unresolved_items=unresolved_items,
    )


async def _road_worker_node(state: ExecuteAgentState) -> dict:
    result = _road_worker(state)
    return {"worker_results": [result]}
