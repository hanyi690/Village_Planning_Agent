"""Facility worker node: decision-driven facility footprint placement."""

from __future__ import annotations

from typing import List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.common import _execution_error
from app.agent.execute.nodes.worker_common import _resolve_parcel_by_bsm, _task_enabled
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
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    if not _task_enabled(state, "facility"):
        return WorkerResult(worker_type="facility")

    facilities = list(getattr(state.intent, "facilities", None) or [])
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    features = []
    changes: List[ParcelChange] = []
    for facility in facilities:
        change = design_facility_parcel(facility, parcel_by_bsm, None)
        if change is None:
            logger.warning(
                "[EXECUTE:facility] skipped %s (no anchor_point)",
                getattr(facility, "type", ""),
            )
            continue
        changes.append(change)
        geometry = {}
        after_wkt = getattr(change, "after_geometry_wkt", "") or ""
        if after_wkt:
            try:
                geom = wkt.loads(after_wkt)
                if not geom.is_empty:
                    geometry = geometry_mapping(geom)
            except Exception:
                geometry = {}
        features.append({
            "type": "Feature",
            "properties": {
                "facility_id": change.bsm,
                "facility_type": getattr(facility, "type", ""),
                "status": "planned_new",
                "source_bsm": change.bsm,
                "change_action": change.action,
            },
            "geometry": geometry,
        })

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