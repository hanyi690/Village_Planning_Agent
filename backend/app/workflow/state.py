"""Canonical control state for the new workflow boundary.

The legacy analysis channels are still being migrated stage by stage.  New
workflow services must depend on this small projection, never on report text,
GIS payloads, or worker-local state.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.modules.schema.contracts.artifact_descriptor import ArtifactDescriptor
from app.modules.schema.contracts.workflow_contracts import GateDecision


POST_L3_GATE_STAGES = frozenset(
    {
        "target_projection",
        "ground",
        "select",
        "validate",
        "reconcile",
        "deliver",
    }
)
LEGACY_GATE_STAGES = frozenset({"l1", "l2", "l3"})
GATE_LOAD_FAILED = "__GATE_LOAD_FAILED__"


class RootGateResolutionError(RuntimeError):
    """Raised when root control cannot prove a stage gate from its contract."""

    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage} gate resolution failed: {reason}")


def load_root_gate(state: dict[str, Any], stage: str) -> GateDecision:
    """Load the typed gate that root routing is allowed to trust.

    Post-L3 gates are reference-only: an inline ``{stage}_gate`` value is
    intentionally ignored.  L1/L2/L3 are the only temporary exception while
    their legacy layer state is migrated.  A missing or invalid gate is an
    error, never an implicit PASS.
    """

    normalized_stage = str(stage or "").strip().lower()
    if normalized_stage in LEGACY_GATE_STAGES:
        raw = state.get(f"{normalized_stage}_gate_decision")
        if raw is None:
            raw = state.get(f"{normalized_stage}_gate")
        if raw is None:
            raise RootGateResolutionError(normalized_stage, "legacy gate is missing")
        try:
            return GateDecision.model_validate(raw)
        except Exception as exc:
            raise RootGateResolutionError(normalized_stage, "legacy gate is invalid") from exc

    if normalized_stage not in POST_L3_GATE_STAGES:
        raise RootGateResolutionError(normalized_stage, "stage is outside root gate scope")

    key = f"{normalized_stage}_gate"
    raw_ref = dict(state.get("artifact_refs") or {}).get(key)
    if not raw_ref:
        raise RootGateResolutionError(normalized_stage, f"missing artifact ref: {key}")
    try:
        descriptor = ArtifactDescriptor.model_validate(raw_ref)
    except Exception as exc:
        raise RootGateResolutionError(normalized_stage, f"invalid artifact ref: {key}") from exc
    if descriptor.schema_id != "GateDecision":
        raise RootGateResolutionError(
            normalized_stage,
            f"artifact ref {key} has schema {descriptor.schema_id!r}",
        )

    from app.infrastructure.artifacts.runtime import load_artifact

    try:
        gate = load_artifact(state, key, GateDecision)
    except Exception as exc:
        raise RootGateResolutionError(normalized_stage, f"artifact load failed: {key}") from exc
    if gate is None:
        raise RootGateResolutionError(normalized_stage, f"artifact payload is empty: {key}")
    if gate.stage.strip().lower() != normalized_stage:
        raise RootGateResolutionError(
            normalized_stage,
            f"artifact payload stage is {gate.stage!r}",
        )
    return gate


def root_gate_route(state: dict[str, Any], stage: str) -> str:
    """Return a gate route, or a distinct fail-closed sentinel on load error."""

    try:
        gate = load_root_gate(state, stage)
    except RootGateResolutionError:
        return GATE_LOAD_FAILED
    route = gate.feedback_route
    if route:
        return route
    return "PASS" if gate.passed else "HUMAN"


class WorkflowState(TypedDict, total=False):
    """Checkpoint-owned control state and immutable artifact references."""

    run_id: str
    session_id: str
    branch_id: str
    phase: str
    active_stage: str
    status: str
    delivery_status: str
    context_ref: dict[str, Any]
    context_fingerprint: str
    artifact_refs: dict[str, ArtifactDescriptor | dict[str, Any]]
    gate_ref: ArtifactDescriptor | dict[str, Any] | None
    retry: dict[str, Any]
    interrupt_ref: ArtifactDescriptor | dict[str, Any] | None
    terminal_ref: ArtifactDescriptor | dict[str, Any] | None
def _active_stage(state: dict[str, Any]) -> str:
    """Derive one stage name without exposing legacy routing fields."""

    return str(
        state.get("active_stage")
        or state.get("paused_stage")
        or state.get("current_stage")
        or state.get("phase")
        or ""
    )


def _status(state: dict[str, Any]) -> str:
    """Normalize checkpoint status for application queries."""

    if state.get("fatal_error"):
        return "failed"
    if state.get("human_interrupt") or state.get("interrupt_ref") or state.get("paused_stage"):
        return "paused"
    if state.get("delivery_status"):
        return "completed"
    value = str(state.get("status") or "running")
    return value if value in {
        "pending",
        "running",
        "paused",
        "reviewing",
        "revising",
        "completed",
        "failed",
    } else "running"


def project_workflow_state(state: dict[str, Any]) -> WorkflowState:
    """Project a checkpoint into the small application control-state shape.

    The graph still has legacy channels while the stage nodes are migrated.
    This function is the only place where those channels are interpreted by
    the application layer.  It deliberately drops reports, messages, GIS
    payloads, worker results, and stage-local state.
    """

    interrupt = _interrupt_projection(state)
    return {
        "run_id": str(state.get("run_id") or state.get("session_id") or ""),
        "session_id": str(state.get("session_id") or state.get("run_id") or ""),
        "branch_id": str(state.get("branch_id") or "main"),
        "phase": str(state.get("phase") or ""),
        "active_stage": _active_stage(state),
        "status": _status(state),
        "delivery_status": str(state.get("delivery_status") or ""),
        "context_ref": dict(state.get("context_ref") or {}),
        "context_fingerprint": str(state.get("context_fingerprint") or ""),
        "artifact_refs": dict(state.get("artifact_refs") or {}),
        "gate_ref": state.get("gate_ref") or _latest_gate(state),
        "retry": dict(state.get("retry") or state.get("retry_counts") or {}),
        "interrupt_ref": interrupt,
        "terminal_ref": state.get("terminal_ref") or state.get("diagnostic_terminal"),
    }


def _interrupt_projection(state: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize HUMAN and step-mode legacy channels into one small payload."""

    raw = state.get("interrupt_ref") or state.get("human_interrupt")
    interrupt = dict(raw) if isinstance(raw, dict) else {}
    items = list(interrupt.get("items") or state.get("human_review_items") or [])
    event_id = str(interrupt.get("event_id") or state.get("human_review_event_id") or "")
    paused_stage = str(interrupt.get("paused_stage") or state.get("paused_stage") or "")
    if not interrupt and not items and not event_id and not paused_stage:
        return None
    interrupt["event_id"] = event_id
    interrupt["items"] = items
    if paused_stage:
        interrupt["paused_stage"] = paused_stage
    return interrupt


def _latest_gate(state: dict[str, Any]) -> Any:
    """Select the downstream-most gate for a compact status projection."""

    for key in (
        "deliver_gate",
        "reconcile_gate",
        "validate_gate",
        "select_gate",
        "ground_gate",
        "target_projection_gate",
    ):
        ref = (state.get("artifact_refs") or {}).get(key)
        if ref:
            return ref
    for key in (
        "l3_gate_decision",
        "l2_gate_decision",
        "l1_gate_decision",
    ):
        value = state.get(key)
        if value is not None:
            return value
    return None


def control_state_from_checkpoint(state: dict[str, Any]) -> WorkflowState:
    """Named application-facing alias for checkpoint projection."""

    return project_workflow_state(state)


__all__ = [
    "GATE_LOAD_FAILED",
    "LEGACY_GATE_STAGES",
    "POST_L3_GATE_STAGES",
    "RootGateResolutionError",
    "WorkflowState",
    "control_state_from_checkpoint",
    "load_root_gate",
    "project_workflow_state",
    "root_gate_route",
]
