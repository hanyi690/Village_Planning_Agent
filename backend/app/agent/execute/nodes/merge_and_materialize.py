"""Merge / geometry-materialize / planned-state-builder nodes."""

from __future__ import annotations

from typing import Any, Dict, List

from app.agent.execute.execute_state import ExecuteAgentState
from app.agent.execute.nodes.worker_common import _execution_intent_from_plan, _worker_result_get


async def _merge_worker_results_node(state: ExecuteAgentState) -> dict:
    """Merge all WorkerResults into a unified ParcelChangeSet + layout_configs."""
    from app.agent.execute.merge import merge_worker_results

    changeset, layout_configs, diagnostics, action_results = merge_worker_results(
        list(state.worker_results)
    )
    update: Dict[str, Any] = {
        "parcel_changeset": changeset,
        "layout_configs": layout_configs,
        "worker_conflict_diagnostics": diagnostics,
        "action_results": action_results,
    }
    if changeset is not None:
        update["parcel_changes"] = list(changeset.changes)

    unresolved = []
    for result in state.worker_results:
        unresolved.extend(_worker_result_get(result, "unresolved_items") or [])
    if unresolved:
        update["unresolved_targets"] = (
            list(state.unresolved_targets or []) + unresolved
        )
    return update


async def _geometry_materialize_node(state: ExecuteAgentState) -> dict:
    """Confirm the already-determined geometry operations (no site selection).

    Lightweight confirmation: the design phase produced the ParcelChanges; this
    node only validates that geometry-mutating changes carry a usable
    ``after_geometry_wkt`` so the later checks can trust the changeset.
    """
    changeset = state.parcel_changeset
    diagnostics: List[Dict[str, Any]] = []
    geometry_valid = True
    checked = 0
    for change in (changeset.changes if changeset is not None else []):
        checked += 1
        if change.action in {"create", "split", "merge"} and not (
            getattr(change, "after_geometry_wkt", "") or ""
        ):
            geometry_valid = False
            diagnostics.append({
                "code": "missing_after_geometry",
                "bsm": getattr(change, "bsm", ""),
                "action": change.action,
            })
    report = {
        "geometry_valid": geometry_valid,
        "checked_changes": checked,
        "diagnostics": diagnostics,
    }
    return {"geometry_materialize_report": report}


async def _planned_state_builder_node(state: ExecuteAgentState) -> dict:
    """Produce the authoritative PlannedState from the merged ParcelChangeSet."""
    from app.agent.execute.planned_state_builder import changeset_to_planned_state

    if state.parcel_changeset is None:
        return {}
    planned_state = changeset_to_planned_state(state.parcel_changeset, _execution_intent_from_plan(state))
    return {"planned_state": planned_state}
