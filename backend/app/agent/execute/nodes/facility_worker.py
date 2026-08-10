"""Facility worker node: decision-driven facility footprint placement."""

from __future__ import annotations

from typing import List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.common import _execution_error
from app.agent.execute.nodes.worker_common import _execution_intent_from_plan, _resolve_parcel_by_bsm, _task_enabled, _task_execution_result
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _facility_worker(state: ExecuteAgentState) -> WorkerResult:
    """Facility worker: decision-driven facility footprint placement.

    Builds a Polygon footprint for each FacilityTarget anchor via the Land
    Design Worker. Passes the real ``parcel_by_bsm`` so the containing-parcel
    branch of ``design_facility_parcel`` activates when an anchor sits inside
    an existing parcel. No KG POI lookup, no FacilityPlacer.
    """
    from app.agent.execute.land_design_worker import design_facility_parcel
    if not _task_enabled(state, "facility"):
        return WorkerResult(worker_type="facility")

    facilities = list(getattr(_execution_intent_from_plan(state), "facilities", None) or [])
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    features = []
    changes: List[ParcelChange] = []
    task_results = []
    for facility in facilities:
        change = design_facility_parcel(facility, parcel_by_bsm, None)
        if change is None:
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
    unresolved = []
    if not features:
        unresolved.append({
            "code": "facility_output_empty",
            "message": "Facility targets exist but no facility layer was produced.",
        })
    return WorkerResult(
        worker_type="facility",
        task_results=task_results,
        layers=layers,
        parcel_changes=changes,
        unresolved_items=unresolved,
        diagnostics=[{"code": "facility_ok", "placed": len(features)}],
    )


async def _facility_worker_node(state: ExecuteAgentState) -> dict:
    try:
        result = _facility_worker(state)
        return {"worker_results": [result]}
    except Exception as e:
        logger.error("[EXECUTE:facility] failed: %s", e, exc_info=True)
        return _execution_error(state, "facility", "facility_failed", str(e))
