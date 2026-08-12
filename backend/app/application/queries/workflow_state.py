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

    from app.services.runtime import PlanningRuntimeService

    raw_state = await PlanningRuntimeService.aget_state_values(session_id)
    if not raw_state:
        return None
    return control_state_from_checkpoint(raw_state)


__all__ = ["load_workflow_state"]
