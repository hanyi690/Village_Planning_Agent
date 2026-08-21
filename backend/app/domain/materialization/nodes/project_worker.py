"""Project worker node: place each L3 project on the SSD-selected parcel."""

from __future__ import annotations

from typing import List

from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.worker_common import (
    _execution_intent_from_plan,
    _footprint_geometry,
    _plan_tasks,
    _task_value,
    _parcel_geometry,
    _resolve_parcel_by_bsm,
    _scenario_features_for_layer,
    _task_for_target,
    _attach_feature_lineage,
    _task_enabled,
    _task_execution_result,
)
from app.contracts.workflow.execution_plan_contracts import TypedActionResult, WorkerResult
from app.contracts.spatial.parcel_change_contracts import ParcelChange
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _project_worker(state: ExecuteAgentState) -> WorkerResult:
    """Project worker: place each L3 project on the SSD-selected parcel.

    Joins selected parcels and design briefs by stable target ID. Non-spatial
    action targets produce typed action results and never parcel changes.
    """
    from app.domain.materialization.land_design_worker import design_project_footprint

    if not _task_enabled(state, "site_area"):
        return WorkerResult(worker_type="site_area")

    projects = list(getattr(_execution_intent_from_plan(state), "site_area_targets", None) or [])
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    selected_by_target = {
        str(_task_value(task, "target_id", "")): str(_task_value(_task_value(task, "assignment"), "selected_bsm", ""))
        for task in _plan_tasks(state, {"site_area_footprint"})
        if _task_value(_task_value(task, "assignment"), "selected_bsm", "")
    }
    if state.execution_plan is None:
        selected_by_target = {
            str(item.project_ref): str(item.candidate_id)
            for item in list(getattr(state.site_selection, "full_ranking", None) or [])
            if getattr(item, "project_ref", None) and getattr(item, "candidate_id", None)
        }
    projects_by_target = {
        str(getattr(project, "target_id", "")): project for project in projects
        if getattr(project, "target_id", "")
    }
    briefs = list(state.land_design_briefs or [])
    briefs_by_target = {
        str(brief.project_ref): brief
        for brief in briefs
        if getattr(brief, "project_ref", "")
    }
    candidate_geometry_by_id = getattr(state, "candidate_geometry_by_id", {}) or {}
    candidate_by_target = {
        str(_task_value(task, "target_id", "")): str(
            _task_value(task, "candidate_id", "") or ""
        )
        for task in _plan_tasks(state, {"site_area_footprint"})
        if _task_value(task, "candidate_id", "")
    }
    direct_candidate_targets = {
        target_id
        for target_id, candidate_id in candidate_by_target.items()
        if str(
            getattr(candidate_geometry_by_id.get(candidate_id), "role", "") or ""
        ) == "execution_geometry"
        and str(
            getattr(candidate_geometry_by_id.get(candidate_id), "wkt", "") or ""
        ).strip()
    }
    non_executable_candidate_targets = {
        target_id
        for target_id, candidate_id in candidate_by_target.items()
        if candidate_geometry_by_id.get(candidate_id) is not None
        and target_id not in direct_candidate_targets
    }
    features = []
    changes: List[ParcelChange] = []
    completed_target_ids = set()
    action_results = [
        TypedActionResult(
            target_id=project.target_id,
            action=project.action,
            details={"name": project.name},
        )
        for project in projects
        if not getattr(project, "requires_spatial", True)
        or getattr(project, "expected_output_kind", "") == "action"
    ]
    for target_id, bsm in selected_by_target.items():
        # An executable SELECT geometry is already the planning subgeometry.
        # Do not expand it back to the full source BSM through land design.
        if target_id in direct_candidate_targets or target_id in non_executable_candidate_targets:
            continue
        project = projects_by_target.get(target_id)
        if project is None or not getattr(project, "requires_spatial", True):
            continue
        parcel = parcel_by_bsm.get(str(bsm))
        if parcel is None or not _parcel_geometry(parcel):
            continue
        if getattr(project, "expected_output_kind", "") == "action":
            continue
        brief = briefs_by_target.get(target_id)
        if brief is None:
            continue
        change_list = design_project_footprint(project, brief, str(bsm), parcel_by_bsm)
        if not change_list:
            continue
        changes.extend(change_list)
        completed_target_ids.add(target_id)
        primary = change_list[0]
        props = {
            "project_id": project.target_id,
            "project_name": getattr(project, "name", ""),
            "project_category": getattr(project, "category", "other"),
            "action": getattr(project, "action", "new"),
            "scale_text": getattr(project, "scale_text", ""),
            "source_bsm": str(bsm),
            "source_instruction_id": getattr(project, "source_instruction_id", ""),
            "source_report_key": getattr(project, "source_report_key", ""),
            "candidate_bsms": list(getattr(project, "candidate_bsms", None) or []),
            "constraint_check": "passed",
            "geometry_source": "land_design_worker",
            "change_action": primary.action,
        }
        props["project_ref"] = target_id
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": _footprint_geometry(primary, _parcel_geometry(parcel)),
        })

    # Relation-aware candidates are not necessarily cadastral parcels.  A
    # typed execution geometry is authoritative and is materialized directly;
    # the parcel design branch above is used only when SELECT did not produce
    # an executable candidate for that task.
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping as shapely_mapping
    for target_id, candidate_id in candidate_by_target.items():
        if target_id in completed_target_ids:
            continue
        candidate = candidate_geometry_by_id.get(candidate_id)
        geometry_wkt = str(getattr(candidate, "wkt", "") or "")
        if candidate is None or str(getattr(candidate, "role", "") or "") != "execution_geometry":
            continue
        if not geometry_wkt:
            continue
        try:
            geometry = shapely_mapping(shapely_wkt.loads(geometry_wkt))
        except Exception:
            continue
        if not geometry or not geometry.get("type"):
            continue
        project = projects_by_target.get(target_id)
        if project is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "target_id": target_id,
                "project_id": target_id,
                "project_name": getattr(project, "name", ""),
                "project_category": getattr(project, "category", "other"),
                "candidate_id": candidate_id,
                "source_bsms": list(getattr(candidate, "source_bsms", None) or []),
                "feature_bsms": list(getattr(candidate, "feature_bsms", None) or []),
                "crs": str(getattr(candidate, "crs", "") or "EPSG:4326"),
                "source_feature_ids": list(
                    getattr(candidate, "source_feature_ids", None) or []
                ),
                "entity_refs": list(getattr(candidate, "entity_refs", None) or []),
                "relation_refs": list(getattr(candidate, "relation_refs", None) or []),
                "evidence_refs": list(getattr(candidate, "evidence_refs", None) or []),
                "l1_snapshot_ref": str(
                    getattr(candidate, "l1_snapshot_ref", "") or ""
                ),
                "bundle_snapshot_digest": str(
                    getattr(candidate, "bundle_snapshot_digest", "") or ""
                ),
                "subgeometry_operation": str(
                    getattr(candidate, "subgeometry_operation", "") or ""
                ),
                "subgeometry_diagnostics": list(
                    getattr(candidate, "subgeometry_diagnostics", None) or []
                ),
                "spatial_domain_kind": str(
                    getattr(candidate, "spatial_domain_kind", "") or ""
                ),
                "source_area_ha": getattr(candidate, "source_area_ha", None),
                "planning_area_ha": getattr(candidate, "planning_area_ha", None),
                "coverage_ratio": getattr(candidate, "coverage_ratio", None),
                "scenario_id": str(_task_value(_task_for_target(state, target_id), "scenario_id", "") or ""),
                "source_refs": list(dict.fromkeys([
                    *list(getattr(candidate, "source_refs", None) or []),
                    *list(getattr(candidate, "evidence_refs", None) or []),
                    str(getattr(candidate, "source_ref", "") or ""),
                ])) or ["candidate_geometry"],
                "generation_operation": "candidate_geometry_materialize",
                "materialization_role": str(
                    getattr(project, "materialization_role", "")
                    or "project_footprint"
                ),
                "hard_constraint_status": str(
                    getattr(candidate, "hard_constraint_status", "") or ""
                ),
            },
            "geometry": geometry,
        })
        completed_target_ids.add(target_id)

    layers = []
    if features:
        layers.append({
            "layerType": "planned_project",
            "layerName": "规划项目",
            "data": {"type": "FeatureCollection", "features": features},
        })
    unresolved = []
    if projects_by_target and not features and not action_results:
        unresolved.append({
            "code": "project_output_empty",
            "message": "Project targets exist but none could be placed on a constraint-safe candidate parcel.",
        })
    task_results = []
    for project in projects:
        deferred_candidate = (
            project.target_id in non_executable_candidate_targets
            and project.target_id not in completed_target_ids
        )
        candidate = candidate_geometry_by_id.get(
            candidate_by_target.get(project.target_id, "")
        )
        task_result = _task_execution_result(
            state,
            "site_area_footprint",
            project.target_id,
            status=(
                "succeeded"
                if project.target_id in completed_target_ids
                else "deferred"
                if deferred_candidate
                else "failed"
            ),
            diagnostics=(
                []
                if project.target_id in completed_target_ids
                else [{
                    "code": (
                        "candidate_geometry_not_executable"
                        if deferred_candidate
                        else "project_output_missing"
                    ),
                    "target_id": project.target_id,
                    "candidate_id": str(getattr(candidate, "candidate_id", "") or ""),
                    "geometry_role": str(getattr(candidate, "role", "") or ""),
                    "subgeometry_operation": str(
                        getattr(candidate, "subgeometry_operation", "") or ""
                    ),
                    "subgeometry_diagnostics": list(
                        getattr(candidate, "subgeometry_diagnostics", None) or []
                    ),
                }]
            ),
        )
        if task_result is not None:
            task_results.append(task_result)
    scenario_features = [
        item
        for layer in layers
        for item in _scenario_features_for_layer(
            state, layer, generation_operation="project_worker"
        )
    ]
    _attach_feature_lineage(task_results, scenario_features)
    return WorkerResult(
        worker_type="site_area",
        task_results=task_results,
        layers=layers,
        parcel_changes=changes,
        action_results=action_results,
        unresolved_items=unresolved,
        diagnostics=[{
            "code": "project_ok",
            "projects_placed": len(features),
            "changes": len(changes),
            "actions": len(action_results),
        }],
        scenario_features=scenario_features,
        task_id=(
            str(getattr(state.execution_plan.worker_tasks[0], "task_id", ""))
            if state.execution_plan and len(state.execution_plan.worker_tasks) == 1
            else ""
        ),
    )


async def _project_worker_node(state: ExecuteAgentState) -> dict:
    result = _project_worker(state)
    return {"worker_results": [result]}
