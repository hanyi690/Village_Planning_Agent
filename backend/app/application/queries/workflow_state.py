"""Application query for the checkpoint-owned workflow control state."""

from __future__ import annotations

from app.workflow.state import WorkflowState, control_state_from_checkpoint


async def load_workflow_state(session_id: str) -> WorkflowState | None:
    """Read one checkpoint and return only the stable control projection.

    Runtime owns LangGraph snapshots.  The application query owns the
    boundary that prevents API code from depending on the legacy AgentState.
    Artifact payloads are intentionally queried by their explicit artifact
    reference in the delivery queries, never through this projection.
    """

    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    raw_state = await PlanningRuntimeService.aget_state_values(session_id)
    if not raw_state:
        return None
    control = control_state_from_checkpoint(raw_state)

    # A HUMAN interrupt created inside a compiled segment can be present on a
    # pending Pregel task before the parent values projection has merged the
    # segment's interrupt fields.  This is especially visible after resuming
    # one interrupt and immediately reaching a second step-mode checkpoint:
    # the checkpoint is live, but the API projection can still look consumed.
    # Read the authoritative pending task once as a defensive projection
    # fallback.  This does not mutate the checkpoint or resume anything.
    if not control.get("interrupt_ref"):
        snapshot = await PlanningRuntimeService.aget_state(session_id, subgraphs=True)
        pending = _pending_interrupt_projection(snapshot)
        if pending is not None:
            control["interrupt_ref"] = pending

    return control


def _pending_interrupt_projection(snapshot: object) -> dict[str, object] | None:
    """Extract the newest pending HUMAN payload from a checkpoint tree."""

    from app.contracts.workflow.human_interrupt_contracts import normalize_human_interrupt

    def visit_tasks(tasks: object) -> dict[str, object] | None:
        for task in tasks or ():
            for pending in getattr(task, "interrupts", None) or ():
                payload = getattr(pending, "value", None)
                if isinstance(payload, dict):
                    return normalize_human_interrupt(payload)
            child = getattr(task, "state", None)
            if child is not None:
                child_payload = visit_tasks(getattr(child, "tasks", None))
                if child_payload is not None:
                    return child_payload
        return None

    return visit_tasks(getattr(snapshot, "tasks", None))


__all__ = ["load_workflow_state"]
