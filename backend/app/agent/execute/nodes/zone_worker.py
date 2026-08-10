"""Zone worker node: deterministic zone reclassification + MIP allocation."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.legacy.layer_helpers import (
    _allocated_geojson_from_changes,
    _build_custom_planning_layer,
    _function_zone_layer,
)
from app.agent.execute.nodes.common import _execution_error
from app.agent.execute.nodes.worker_common import (
    _build_landuse_geojson,
    _execution_intent_from_plan,
    _intent_list,
    _resolve_parcel_by_bsm,
    _task_enabled,
)
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_zone_allocator(state: ExecuteAgentState) -> Any:
    """ZoneAllocatorPort from injected ports, else the default PuLP adapter."""
    ports = getattr(state, "ports", None)
    allocator = getattr(ports, "zone_allocator", None) if ports is not None else None
    if allocator is None:
        from app.modules.spatial_ops.allocation.zone_allocator_adapter import PuLPZoneAllocator

        allocator = PuLPZoneAllocator()
    return allocator


def _zone_target_key(zone_target: Any) -> str:
    return str(
        getattr(zone_target, "zone_id", None)
        or getattr(zone_target, "land_use", None)
        or ""
    )


def _allocate_empty_zone_targets(
    state: ExecuteAgentState,
    empty_targets: List[Any],
    parcel_by_bsm: Dict[str, Any],
    zone_changes: List[ParcelChange],
    diagnostics: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """MIP-allocate parcels for zone targets with no candidate_bsms.

    The unclaimed parcel pool (parcels not claimed by any non-empty zone target)
    is passed as the candidate set. Infeasible allocations are surfaced as
    ``design_unresolved`` diagnostics - never silently skipped.
    """
    unresolved: List[Dict[str, Any]] = []
    if not empty_targets:
        return unresolved

    claimed: set = set()
    for zone_target in _intent_list(_execution_intent_from_plan(state), "zone_targets"):
        for bsm in getattr(zone_target, "candidate_bsms", None) or []:
            claimed.add(str(bsm))
    pool = [bsm for bsm in parcel_by_bsm if str(bsm) not in claimed]

    targets: Dict[str, float] = {}
    candidates: Dict[str, List[str]] = {}
    metadata: Dict[str, Any] = {"parcel_by_bsm": parcel_by_bsm}
    for zone_target in empty_targets:
        key = _zone_target_key(zone_target)
        if not key:
            continue
        targets[key] = float(getattr(zone_target, "area_ha", None) or 0.0)
        candidates[key] = list(pool)
        metadata[key] = {"land_use": getattr(zone_target, "land_use", "") or ""}

    if not targets:
        return unresolved

    allocator = _resolve_zone_allocator(state)
    try:
        solution = allocator.allocate(targets, candidates, constraints=None, metadata=metadata)
    except Exception as e:  # pragma: no cover - defensive
        for zone_target in empty_targets:
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_error",
                "target": _zone_target_key(zone_target),
                "message": str(e),
            })
        return unresolved

    if not getattr(solution, "feasible", False):
        for zone_target in empty_targets:
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_infeasible",
                "target": _zone_target_key(zone_target),
                "diagnostics": list(getattr(solution, "diagnostics", None) or []),
            })
        return unresolved

    from app.agent.execute.land_design_worker import design_zone_parcel

    for zone_target in empty_targets:
        key = _zone_target_key(zone_target)
        assigned_bsms = [
            entry.bsm
            for entry in getattr(solution, "assignments", None) or []
            if entry.zone_id == key
        ]
        if not assigned_bsms:
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_empty",
                "target": key,
                "message": "Allocator returned no assignments for zone.",
            })
            continue
        allocated_target = zone_target.model_copy(update={"candidate_bsms": assigned_bsms})
        zone_changes.extend(design_zone_parcel(allocated_target, parcel_by_bsm))
        diagnostics.append({
            "code": "zone_allocated",
            "target": key,
            "assigned": len(assigned_bsms),
        })
    return unresolved


def _zone_worker(state: ExecuteAgentState) -> WorkerResult:
    """Zone worker: deterministic zone reclassification + MIP allocation.

    Reclassifies each zone target's candidate parcels to the zone's planning
    land use via the Land Design Worker. Zone targets with empty
    ``candidate_bsms`` are solved through the ``ZoneAllocatorPort`` (PuLP MIP);
    infeasible allocations become ``design_unresolved`` diagnostics.
    """
    from app.agent.execute.land_design_worker import design_zone_parcel

    if not _task_enabled(state, "layout"):
        return WorkerResult(worker_type="zone")

    landuse = _build_landuse_geojson(state)
    bound_intent = _execution_intent_from_plan(state)
    zone_targets = _intent_list(bound_intent, "zone_targets")
    custom_targets = _intent_list(bound_intent, "custom_zone_targets")
    parcel_by_bsm = _resolve_parcel_by_bsm(state)

    diagnostics: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    if not zone_targets and not custom_targets:
        message = "No explicit planning zone targets were derived from the reports."
        logger.error("[EXECUTE:zone] %s", message)
        unresolved.append({"code": "missing_zone_targets", "message": message})
        return WorkerResult(
            worker_type="zone", unresolved_items=unresolved, diagnostics=diagnostics
        )

    zone_changes: List[ParcelChange] = []
    empty_targets = []
    for zone_target in zone_targets:
        if not getattr(zone_target, "candidate_bsms", None):
            empty_targets.append(zone_target)
            continue
        zone_changes.extend(design_zone_parcel(zone_target, parcel_by_bsm))

    unresolved.extend(
        _allocate_empty_zone_targets(
            state, empty_targets, parcel_by_bsm, zone_changes, diagnostics
        )
    )

    layers = []
    func_layer = _function_zone_layer(zone_changes)
    if func_layer:
        layers.append(func_layer)

    if custom_targets:
        try:
            custom_layer = _build_custom_planning_layer(state, landuse, custom_targets)
            if custom_layer:
                layers.append(custom_layer)
                diagnostics.append({
                    "code": "custom_zone_built",
                    "features": len((custom_layer.get("data") or {}).get("features") or []),
                })
        except Exception as e:
            logger.error("[EXECUTE:zone] custom zoning failed: %s", e, exc_info=True)
            diagnostics.append({"code": "custom_zoning_failed", "message": str(e)})

    return WorkerResult(
        worker_type="zone",
        layers=layers,
        parcel_changes=zone_changes,
        unresolved_items=unresolved,
        diagnostics=diagnostics,
    )


async def _zone_worker_node(state: ExecuteAgentState) -> dict:
    if not _task_enabled(state, "layout"):
        return {}
    result = _zone_worker(state)
    update: Dict[str, Any] = {"worker_results": [result]}
    if any(item.get("code") == "missing_zone_targets" for item in result.unresolved_items):
        update["execution_errors"] = _execution_error(
            state, "layout", "missing_zone_targets",
            "No explicit planning zone targets were derived from the reports.",
        )["execution_errors"]
    landuse = _build_landuse_geojson(state)
    if landuse.get("features"):
        zone_changes = list(result.parcel_changes)
        update["allocated_geojson"] = _allocated_geojson_from_changes(landuse, zone_changes)
        update["allocation_summary"] = {
            "mode": "deterministic",
            "allocated_count": len(zone_changes),
            "zone_target_count": len(_intent_list(_execution_intent_from_plan(state), "zone_targets")),
            "adjustments_applied": len(list(state.constraint_adjustments or [])),
            "custom_zone_count": sum(
                1 for layer in result.layers
                if (layer.get("layerType") or layer.get("layer_type")) == "custom_planning_zone"
            ),
        }
    return update
