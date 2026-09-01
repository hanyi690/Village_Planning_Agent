"""L4 write-back node: persist planned entities back to KG."""

from __future__ import annotations

from app.modules.execute.execute_state import ExecuteAgentState
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


async def _write_l4_node(state: ExecuteAgentState) -> dict:
    """Write L4 planned entities (PlannedParcel, PlannedZone, PlannedFacility, etc.) to KG.

    Consumes the ParcelChangeSet (or the already-built PlannedState). Called
    after execute completes to persist the planned layout back to KG.
    """
    if (state.validation_result or {}).get("partial_usable"):
        logger.warning("[EXECUTE:l4_write] Skipped for partial result; road stage is deferred")
        return {}
    if not (state.validation_result or {}).get("passed", False):
        logger.error("[EXECUTE:l4_write] Skipped because validation did not pass")
        return {}

    session_id = getattr(state, "session_id", "")
    if not session_id:
        logger.warning("[EXECUTE:l4_write] No session_id - skipping L4 write")
        return {}
    world_model_commit = getattr(
        getattr(state, "ports", None),
        "world_model_commit",
        None,
    )
    if world_model_commit is None:
        logger.warning("[EXECUTE:l4_write] World-model commit port unavailable")
        return {"l4_write_error": "missing_world_model_commit_port"}

    planned_state = getattr(state, "planned_state", None)
    if planned_state is None and getattr(state, "parcel_changeset", None) is not None:
        from app.modules.execute.planned_state_builder import changeset_to_planned_state
        from app.modules.execute.workers.worker_common import (
            _execution_intent_from_plan,
            _worker_result_get,
        )

        planned_state = changeset_to_planned_state(
            state.parcel_changeset,
            _execution_intent_from_plan(state),
            list(state.layout_configs or []),
            scenario_features=[
                feature
                for feature in list(
                    getattr(getattr(state, "spatial_changeset", None), "features", None)
                    or []
                )
            ] or [
                feature
                for result in list(getattr(state, "worker_results", None) or [])
                for feature in list(_worker_result_get(result, "scenario_features") or [])
            ],
        )
        logger.info(
            "[EXECUTE:l4_write] building PlannedState from ParcelChangeSet (%d changes)",
            len(state.parcel_changeset.changes),
        )
    elif getattr(state, "planned_state", None) is not None:
        planned_state = state.planned_state

    if planned_state is None:
        logger.warning("[EXECUTE:l4_write] no planned output; skipping L4 write")
        return {}

    outcome = getattr(state, "execution_result", None)
    outcome_task_results = (
        outcome.get("task_results", [])
        if isinstance(outcome, dict)
        else (getattr(outcome, "task_results", None) or [])
    )
    outcome_targets = {
        (
            str(item.get("target_id", ""))
            if isinstance(item, dict)
            else str(getattr(item, "target_id", "")),
            str(item.get("expected_output_kind", ""))
            if isinstance(item, dict)
            else str(getattr(item, "expected_output_kind", "")),
        )
        for item in outcome_task_results
        if (
            str(item.get("status", ""))
            if isinstance(item, dict)
            else str(getattr(item, "status", ""))
        ) == "succeeded"
    }
    planned_targets = {
        (str(getattr(item, "derived_from_target", "")), "point")
        for item in (planned_state.facilities or [])
        if getattr(item, "derived_from_target", "")
    }
    if planned_targets and not planned_targets <= outcome_targets:
        missing = sorted(planned_targets - outcome_targets)
        logger.warning("[EXECUTE:l4_write] execution outcome missing planned targets: %s", missing)
        return {"l4_write_error": "execution_result_target_coverage", "missing_targets": missing}

    written = sum(
        len(items)
        for items in (
            planned_state.parcels,
            getattr(planned_state, "features", []),
            planned_state.zones,
            planned_state.facilities,
            planned_state.roads,
            planned_state.axes,
        )
    )
    if written:
        try:
            outcome = world_model_commit.commit_planned_state(planned_state)
        except Exception as exc:
            logger.error(
                "[EXECUTE:l4_write] world-model commit failed (exception_type=%s)",
                type(exc).__name__,
            )
            return {
                "l4_write_error": "atomic_commit_failed",
                "error_type": type(exc).__name__,
            }
        if str(outcome.get("status", "")) != "committed":
            return {
                "l4_write_error": "atomic_commit_failed",
                "error_type": str(outcome.get("error_type", "unknown")),
            }
        written = int(outcome.get("written", written) or written)
        logger.info("[EXECUTE:l4_write] Wrote %d planned entities", written)

    return {
        "l4_written": written,
        "execution_result_target_ids": sorted({target_id for target_id, _ in outcome_targets}),
    }
