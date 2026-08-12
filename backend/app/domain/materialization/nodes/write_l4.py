"""L4 write-back node: persist planned entities back to KG."""

from __future__ import annotations

from app.domain.materialization.execute_state import ExecuteAgentState
from app.utils.logger import get_logger

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

    try:
        from app.modules.kg.manager import get_kg_manager
        manager = get_kg_manager()
        kg = manager.get_session_kg(session_id)
        if kg is None:
            logger.warning("[EXECUTE:l4_write] No KG for session %s", session_id)
            return {}
    except Exception as e:
        logger.warning("[EXECUTE:l4_write] KG access failed: %s", e)
        return {}

    from app.modules.kg.builder.layer4 import apply_planned_state

    planned_state = None
    if getattr(state, "parcel_changeset", None) is not None:
        from app.domain.materialization.planned_state_builder import changeset_to_planned_state
        from app.domain.materialization.nodes.worker_common import _execution_intent_from_plan

        planned_state = changeset_to_planned_state(
            state.parcel_changeset,
            _execution_intent_from_plan(state),
            list(state.layout_configs or []),
        )
        logger.info(
            "[EXECUTE:l4_write] building PlannedState from ParcelChangeSet (%d changes)",
            len(state.parcel_changeset.changes),
        )
    elif getattr(state, "planned_state", None) is not None:
        planned_state = state.planned_state

    if planned_state is None:
        logger.warning("[EXECUTE:l4_write] no parcel_changeset/planned_state; skipping L4 write")
        return {}

    outcome = getattr(state, "execution_result", None)
    outcome_targets = {
        (str(getattr(item, "target_id", "")), str(getattr(item, "expected_output_kind", "")))
        for item in (getattr(outcome, "task_results", None) or [])
        if str(getattr(item, "status", "")) == "succeeded"
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
            planned_state.zones,
            planned_state.facilities,
            planned_state.roads,
            planned_state.axes,
        )
    )
    if written:
        apply_planned_state(kg, planned_state)
        manager.bump_version(session_id)
        logger.info("[EXECUTE:l4_write] Wrote %d L4 entities to KG", written)

    return {
        "l4_written": written,
        "execution_result_target_ids": sorted({target_id for target_id, _ in outcome_targets}),
    }
