"""Project worker node: place each L3 project on the SSD-selected parcel."""

from __future__ import annotations

from typing import List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import (
    _footprint_geometry,
    _parcel_geometry,
    _resolve_parcel_by_bsm,
    _task_enabled,
)
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _project_worker(state: ExecuteAgentState) -> WorkerResult:
    """Project worker: place each L3 project on the SSD-selected parcel.

    Consumes ``SiteSelectionDecision.selected_combination`` (ordered BSM list,
    paired with land design briefs) and runs ``design_project_footprint``
    (OBB split) for real project footprints. Returns a ``WorkerResult``; never
    mutates shared state.
    """
    from app.agent.execute.land_design_worker import design_project_footprint

    if not _task_enabled(state, "project"):
        return WorkerResult(worker_type="project")

    projects = list(getattr(state.intent, "project_targets", None) or [])
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    selected = list(getattr(state.site_selection, "selected_combination", None) or [])
    if not selected:
        logger.warning("[EXECUTE:project] SELECT not wired; project worker produces no output")
        return WorkerResult(
            worker_type="project",
            diagnostics=[{
                "code": "no_selection",
                "message": "SELECT not wired; no selected parcels for projects.",
            }],
        )

    projects_by_id = {
        getattr(project, "project_id", ""): project for project in projects
    }
    briefs = list(state.land_design_briefs or [])
    features = []
    changes: List[ParcelChange] = []
    for index, bsm in enumerate(selected):
        parcel = parcel_by_bsm.get(str(bsm))
        if parcel is None or not _parcel_geometry(parcel):
            continue
        project = None
        brief = briefs[index] if index < len(briefs) else None
        if brief is not None:
            project = projects_by_id.get(getattr(brief, "project_ref", ""))
        if project is None:
            continue
        worker_brief = brief
        change_list = design_project_footprint(project, worker_brief, str(bsm), parcel_by_bsm)
        if not change_list:
            continue
        changes.extend(change_list)
        primary = change_list[0]
        project_id = ""
        if project is not None:
            project_id = getattr(project, "project_id", "")
        elif brief is not None:
            project_id = getattr(brief, "project_ref", "")
        props = {
            "project_id": project_id,
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
        if brief is not None:
            props["project_ref"] = getattr(brief, "project_ref", "")
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": _footprint_geometry(primary, _parcel_geometry(parcel)),
        })

    layers = []
    if features:
        layers.append({
            "layerType": "planned_project",
            "layerName": "规划项目",
            "data": {"type": "FeatureCollection", "features": features},
        })
    unresolved = []
    if not features:
        unresolved.append({
            "code": "project_output_empty",
            "message": "Project targets exist but none could be placed on a constraint-safe candidate parcel.",
        })
    return WorkerResult(
        worker_type="project",
        layers=layers,
        parcel_changes=changes,
        unresolved_items=unresolved,
        diagnostics=[{"code": "project_ok", "projects_placed": len(features), "changes": len(changes)}],
    )


async def _project_worker_node(state: ExecuteAgentState) -> dict:
    result = _project_worker(state)
    return {"worker_results": [result]}