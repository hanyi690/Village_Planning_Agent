"""Facility worker node: decision-driven facility footprint placement."""

from __future__ import annotations

from typing import List

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.common import _execution_error
from app.domain.materialization.nodes.worker_common import _attach_feature_lineage, _execution_intent_from_plan, _scenario_features_for_layer, _task_enabled, _task_execution_result
from app.contracts.workflow.execution_plan_contracts import WorkerResult
from app.contracts.spatial.parcel_change_contracts import ParcelChange
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _task_value(task: object, name: str, default: object = None) -> object:
    return task.get(name, default) if isinstance(task, dict) else getattr(task, name, default)


def _candidate_value(candidate: object | None, name: str, default: object = None) -> object:
    if isinstance(candidate, dict):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _task_candidate_id(task: object | None) -> str:
    if task is None:
        return ""
    assignment = _task_value(task, "assignment")
    binding = _task_value(assignment, "target_binding", {}) or {}
    return str(
        _task_value(task, "candidate_id", "")
        or (binding.get("candidate_id", "") if isinstance(binding, dict) else "")
        or ""
    ).strip()


def _facility_task_and_candidate(state: ExecuteAgentState, target_id: str) -> tuple[object | None, object | None]:
    """Resolve the selected candidate without deriving a replacement point."""
    for task in getattr(state.execution_plan, "worker_tasks", None) or []:
        if str(_task_value(task, "target_id", "")) != str(target_id):
            continue
        candidate_id = _task_candidate_id(task)
        candidate = (state.candidate_geometry_by_id or {}).get(candidate_id) if candidate_id else None
        return task, candidate
    return None, None


def _candidate_provenance(candidate: object | None) -> dict[str, object]:
    """Expose only source-backed candidate metadata on the emitted feature."""
    if candidate is None:
        return {}
    source_refs = [
        str(value)
        for value in (_candidate_value(candidate, "source_refs", []) or [])
        if str(value).strip()
    ]
    source_ref = str(_candidate_value(candidate, "source_ref", "") or "").strip()
    if source_ref and source_ref not in source_refs:
        source_refs.append(source_ref)
    return {
        "candidate_id": str(_candidate_value(candidate, "candidate_id", "") or ""),
        "source_refs": list(dict.fromkeys(source_refs)),
        "source_bsms": [
            str(value)
            for value in (_candidate_value(candidate, "source_bsms", []) or [])
            if str(value).strip()
        ],
        "feature_bsms": [
            str(value)
            for value in (_candidate_value(candidate, "feature_bsms", []) or [])
            if str(value).strip()
        ],
        "source_feature_ids": [
            str(value)
            for value in (_candidate_value(candidate, "source_feature_ids", []) or [])
            if str(value).strip()
        ],
        "entity_refs": [
            str(value)
            for value in (_candidate_value(candidate, "entity_refs", []) or [])
            if str(value).strip()
        ],
        "relation_refs": [
            str(value)
            for value in (_candidate_value(candidate, "relation_refs", []) or [])
            if str(value).strip()
        ],
        "evidence_refs": [
            str(value)
            for value in (_candidate_value(candidate, "evidence_refs", []) or [])
            if str(value).strip()
        ],
        "l1_snapshot_ref": str(
            _candidate_value(candidate, "l1_snapshot_ref", "") or ""
        ),
        "bundle_snapshot_digest": str(
            _candidate_value(candidate, "bundle_snapshot_digest", "") or ""
        ),
        "geometry_ref": source_ref or str(_candidate_value(candidate, "candidate_id", "") or ""),
        "candidate_geometry_role": str(_candidate_value(candidate, "role", "") or ""),
        "candidate_geometry_granularity": str(_candidate_value(candidate, "granularity", "") or ""),
        "crs": str(_candidate_value(candidate, "crs", "") or ""),
    }


def _facility_worker(state: ExecuteAgentState) -> WorkerResult:
    """Facility worker: decision-driven facility footprint placement.

    Builds a local footprint for each FacilityTarget anchor via the Land
    Design Worker.  A selected candidate must be executable point geometry;
    candidate-only scopes are deferred and never expanded to a containing BSM.
    """
    from app.domain.materialization.land_design_worker import design_facility_parcel
    if not _task_enabled(state, "facility"):
        return WorkerResult(worker_type="facility")

    facilities = list(getattr(_execution_intent_from_plan(state), "facilities", None) or [])
    features = []
    changes: List[ParcelChange] = []
    task_results = []
    unresolved = []
    for facility in facilities:
        task, selected_candidate = _facility_task_and_candidate(state, facility.target_id)
        candidate_id = _task_candidate_id(task)
        if candidate_id and selected_candidate is None:
            diagnostic = {
                "code": "candidate_geometry_missing",
                "target_id": str(facility.target_id),
                "candidate_id": candidate_id,
                "message": "Facility execution requires the selected candidate geometry artifact.",
            }
            unresolved.append(diagnostic)
            task_result = _task_execution_result(
                state,
                "facility_placement",
                facility.target_id,
                status="deferred",
                diagnostics=[diagnostic],
            )
            if task_result is not None:
                task_results.append(task_result)
            continue
        candidate_provenance = _candidate_provenance(selected_candidate)
        candidate_wkt = str(_candidate_value(selected_candidate, "wkt", "") or "").strip()
        if candidate_id and (
            str(_candidate_value(selected_candidate, "role", "") or "")
            != "execution_geometry"
            or not candidate_wkt
        ):
            diagnostic = {
                "code": "candidate_geometry_not_executable",
                "target_id": str(facility.target_id),
                "candidate_id": candidate_id,
                "candidate_role": str(_candidate_value(selected_candidate, "role", "") or ""),
                "message": "Facility candidate is not executable point geometry.",
            }
            unresolved.append(diagnostic)
            task_result = _task_execution_result(
                state,
                "facility_placement",
                facility.target_id,
                status="deferred",
                diagnostics=[diagnostic],
            )
            if task_result is not None:
                task_results.append(task_result)
            continue
        if candidate_wkt:
            try:
                from shapely import wkt as shapely_wkt

                candidate_geometry = shapely_wkt.loads(candidate_wkt)
                if candidate_geometry.geom_type != "Point" or candidate_geometry.is_empty:
                    raise ValueError("facility_candidate_must_be_point")
                # The selected authoritative candidate is the only source
                # permitted to replace a stale target anchor.
                facility.anchor_point = (
                    float(candidate_geometry.x),
                    float(candidate_geometry.y),
                )
            except Exception as exc:
                diagnostic = {
                    "code": "candidate_geometry_invalid",
                    "target_id": str(facility.target_id),
                    "candidate_id": candidate_id,
                    "message": "Facility execution candidate geometry could not be parsed as a point.",
                    "exception_type": type(exc).__name__,
                }
                unresolved.append(diagnostic)
                logger.warning(
                    "[EXECUTE:facility] invalid selected candidate geometry for %s",
                    facility.target_id,
                )
                task_result = _task_execution_result(
                    state,
                    "facility_placement",
                    facility.target_id,
                    status="deferred",
                    diagnostics=[diagnostic],
                )
                if task_result is not None:
                    task_results.append(task_result)
                continue
        if facility.anchor_point is None and state.execution_plan is not None:
            for task in getattr(state.execution_plan, "worker_tasks", None) or []:
                task_target_id = task.get("target_id", "") if isinstance(task, dict) else getattr(task, "target_id", "")
                if str(task_target_id) != str(facility.target_id):
                    continue
                assignment = task.get("assignment") if isinstance(task, dict) else getattr(task, "assignment", None)
                anchor = assignment.get("anchor_point") if isinstance(assignment, dict) else getattr(assignment, "anchor_point", None)
                if anchor is not None:
                    facility.anchor_point = anchor
                break
        if selected_candidate is not None:
            candidate_provenance = _candidate_provenance(selected_candidate)
        change = design_facility_parcel(facility)
        if change is None:
            if facility.anchor_point is not None:
                features.append({
                    "type": "Feature",
                    "properties": {
                        "facility_id": f"facility:{facility.target_id}",
                        "target_id": facility.target_id,
                        "facility_type": getattr(facility, "type", ""),
                        "status": "planned_new",
                        "source_bsm": "",
                        "change_action": "point_only",
                        **candidate_provenance,
                    },
                    "geometry": {"type": "Point", "coordinates": list(facility.anchor_point)},
                })
                task_result = _task_execution_result(
                    state,
                    "facility_placement",
                    facility.target_id,
                    status="succeeded",
                )
                if task_result is not None:
                    task_results.append(task_result)
                continue
            logger.warning(
                "[EXECUTE:facility] skipped %s (no anchor_point)",
                getattr(facility, "type", ""),
            )
            task_result = _task_execution_result(
                state,
                "facility_placement",
                facility.target_id,
                status="failed",
                diagnostics=[{"code": "facility_anchor_missing", "target_id": facility.target_id}],
            )
            if task_result is not None:
                task_results.append(task_result)
            continue
        changes.append(change)
        geometry = {}
        if facility.anchor_point is not None:
            geometry = {"type": "Point", "coordinates": list(facility.anchor_point)}
        features.append({
            "type": "Feature",
            "properties": {
                "facility_id": change.bsm,
                "target_id": facility.target_id,
                "facility_type": getattr(facility, "type", ""),
                "status": "planned_new",
                "source_bsm": change.bsm,
                "change_action": change.action,
                **candidate_provenance,
            },
            "geometry": geometry,
        })
        task_result = _task_execution_result(
            state,
            "facility_placement",
            facility.target_id,
            status="succeeded",
        )
        if task_result is not None:
            task_results.append(task_result)

    layers = []
    if features:
        layers.append({
            "layerType": "facility_point",
            "layerName": "公共服务设施",
            "data": {"type": "FeatureCollection", "features": features},
        })
    if not features:
        unresolved.append({
            "code": "facility_output_empty",
            "message": "Facility targets exist but no facility layer was produced.",
        })
    scenario_features = [
        item
        for layer in layers
        for item in _scenario_features_for_layer(
            state, layer, generation_operation="facility_worker"
        )
    ]
    _attach_feature_lineage(task_results, scenario_features)
    return WorkerResult(
        worker_type="facility",
        task_results=task_results,
        layers=layers,
        parcel_changes=changes,
        unresolved_items=unresolved,
        diagnostics=[{"code": "facility_ok", "placed": len(features)}],
        scenario_features=scenario_features,
        task_id=(
            str(getattr(state.execution_plan.worker_tasks[0], "task_id", ""))
            if state.execution_plan and len(state.execution_plan.worker_tasks) == 1
            else ""
        ),
    )


async def _facility_worker_node(state: ExecuteAgentState) -> dict:
    try:
        result = _facility_worker(state)
        return {"worker_results": [result]}
    except Exception as e:
        logger.error("[EXECUTE:facility] failed: %s", e, exc_info=True)
        return _execution_error(state, "facility", "facility_failed", str(e))
