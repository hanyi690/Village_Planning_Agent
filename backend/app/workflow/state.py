"""Canonical control state for the new workflow boundary.

The legacy analysis channels are still being migrated stage by stage.  New
workflow services must depend on this small projection, never on report text,
GIS payloads, or worker-local state.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from app.contracts.artifacts import ArtifactRef
from app.contracts.workflow.workflow_contracts import GateDecision


# ``execute`` 是有意不在 GATE_STAGES 里的显式豁免（A4）：EXECUTE 阶段不
# 产出 gate artifact，其路由只看 fatal_error（见 root_graph.route_after_execute）。
GATE_STAGES = frozenset(
    {
        "l1",
        "l2",
        "l3",
        "target_projection",
        "ground",
        "select",
        "validate",
        "reconcile",
        "deliver",
    }
)
GATE_LOAD_FAILED = "__GATE_LOAD_FAILED__"


class RootGateResolutionError(RuntimeError):
    """Raised when root control cannot prove a stage gate from its contract."""

    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(f"{stage} gate resolution failed: {reason}")


def load_root_gate(state: dict[str, Any], stage: str) -> GateDecision:
    """Load the typed gate that root routing is allowed to trust.

    Every gate is reference-only: an inline ``{stage}_gate`` value is
    intentionally ignored.  A missing or invalid gate is an error, never an
    implicit PASS.
    """

    normalized_stage = str(stage or "").strip().lower()
    if normalized_stage not in GATE_STAGES:
        raise RootGateResolutionError(normalized_stage, "stage is outside root gate scope")

    key = f"{normalized_stage}_gate"
    raw_ref = dict(state.get("artifact_refs") or {}).get(key)
    if not raw_ref:
        raise RootGateResolutionError(normalized_stage, f"missing artifact ref: {key}")
    try:
        descriptor = ArtifactRef.model_validate(raw_ref)
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


def _merge_identity(current: Any, update: Any) -> Any:
    """Merge run/session/branch identity that parallel workers write identically."""
    if current is None or current == "" or current == update:
        return update
    if isinstance(current, dict) and isinstance(update, dict):
        merged = dict(current)
        merged.update(dict(update))
        return merged
    raise ValueError(
        f"parallel writers disagree on identity key: {current!r} vs {update!r}"
    )


def _merge_control(current: Any, update: Any) -> Any:
    """Merge non-identity control keys (phase/status/stage) across branches.

    Parallel dimension workers and the deferred aggregate/advance nodes may
    write the same control key within one super-step.  These fields are
    progress pointers, not business facts: the downstream-most writer wins.
    """
    if current is None:
        return update
    if isinstance(current, dict) and isinstance(update, dict):
        merged = dict(current)
        merged.update(dict(update))
        return merged
    return update


def _merge_fatal_error(current: Any, update: Any) -> Any:
    """Preserve one parallel failure while allowing explicit recovery clear."""
    if update is None:
        return None
    return current or update


def _merge_artifact_refs(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge parallel worker artifact refs by key (last writer wins per key)."""
    merged = dict(current or {})
    merged.update(dict(update or {}))
    return merged


def _merge_retry(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge per-stage retry counters across parallel branches."""
    merged = dict(current or {})
    for stage, value in dict(update or {}).items():
        if isinstance(value, (int, float)):
            merged[stage] = max(int(merged.get(stage, 0) or 0), int(value))
        else:
            merged[stage] = value
    return merged


def _merge_layer_dims(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge per-phase dimension lists that parallel workers extend.

    Each L1/L2/L3 worker reports ``{phase_key: [own_dimension]}``.  LangGraph
    calls this reducer with all concurrent writes for a super-step so the
    phase lists accumulate every worker's dimension (deduped), giving
    ``layer_completion_check`` the full picture without CAS coordination.
    """
    merged = dict(current or {})
    for name, values in dict(update or {}).items():
        if isinstance(values, list) and isinstance(merged.get(name), list):
            merged[name] = list(dict.fromkeys([*merged[name], *values]))
        else:
            merged[name] = values
    return merged


def _merge_reports(current: list[dict[str, Any]], update: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append worker report records (deduped by report_id) across branches."""
    merged = list(current or [])
    seen = {str(item.get("report_id")) for item in merged if isinstance(item, dict)}
    for item in list(update or []):
        if isinstance(item, dict) and str(item.get("report_id")) in seen:
            continue
        merged.append(item)
        if isinstance(item, dict):
            seen.add(str(item.get("report_id")))
    return merged


def _merge_failure_events(
    current: list[dict[str, Any]],
    update: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge all parallel provider failures; an explicit empty list clears."""
    if update == []:
        return []
    merged = list(current or [])
    seen = {str(item) for item in merged}
    for item in list(update or []):
        if str(item) in seen:
            continue
        merged.append(item)
        seen.add(str(item))
    return merged


def _merge_char_counts(current: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Merge per-layer character counts (max per layer) across branches."""
    merged = dict(current or {})
    for layer, value in dict(update or {}).items():
        try:
            merged[layer] = max(int(merged.get(layer, 0) or 0), int(value))
        except (TypeError, ValueError):
            merged[layer] = value
    return merged


def _merge_messages(current: Any, update: Any) -> Any:
    """Append conversation messages across parallel worker branches."""
    try:
        from langgraph.graph.message import add_messages

        return add_messages(current or [], update or [])
    except Exception:
        return [*(current or []), *(update or [])]


def _merge_runtime(current: Any, update: Any) -> Any:
    """Shallow-merge stage-local runtime dicts (last writer wins per key)."""
    merged = dict(current or {})
    merged.update(dict(update or {}))
    return merged


class WorkflowState(TypedDict, total=False):
    """Checkpoint-owned control state and immutable artifact references."""

    run_id: Annotated[str, _merge_identity]
    session_id: Annotated[str, _merge_identity]
    branch_id: Annotated[str, _merge_identity]
    phase: Annotated[str, _merge_control]
    active_stage: Annotated[str, _merge_control]
    status: Annotated[str, _merge_control]
    delivery_status: Annotated[str, _merge_control]
    context_ref: Annotated[dict[str, Any], _merge_artifact_refs]
    context_fingerprint: Annotated[str, _merge_control]
    artifact_refs: Annotated[dict[str, ArtifactRef], _merge_artifact_refs]
    gate_ref: Annotated[ArtifactRef | None, _merge_control]
    retry: Annotated[dict[str, Any], _merge_retry]
    interrupt_ref: Annotated[ArtifactRef | None, _merge_control]
    terminal_ref: Annotated[ArtifactRef | None, _merge_control]
    completed_dimensions: Annotated[dict[str, list[str]], _merge_layer_dims]
    revision_completed_dims: Annotated[dict[str, list[str]], _merge_layer_dims]
    pending_reports: Annotated[list[dict[str, Any]], _merge_reports]
    layer_char_counts: Annotated[dict[str, int], _merge_char_counts]
    revision_impact_tree: Annotated[dict[str, list[str]], _merge_layer_dims]
    revision_target_dimensions: Annotated[list[str], _merge_control]
    messages: Annotated[list[Any], _merge_messages]
    layer_just_completed: Annotated[int | None, _merge_control]
    previous_layer: Annotated[int | None, _merge_control]
    is_revision: Annotated[bool | None, _merge_control]
    need_revision: Annotated[bool | None, _merge_control]
    last_revised_dimensions: Annotated[list[str], _merge_control]
    revision_feedback: Annotated[str | None, _merge_control]
    fatal_error: Annotated[dict[str, Any] | None, _merge_fatal_error]
    provider_failures: Annotated[list[dict[str, Any]], _merge_failure_events]
    dimension_failures: Annotated[list[dict[str, Any]], _merge_failure_events]
    dimension_retry_counts: Annotated[dict[str, int], _merge_retry]
    runtime: Annotated[dict[str, Any], _merge_runtime]
    repair_directives: Annotated[dict[str, Any], _merge_control]
    repair_impact: Annotated[dict[str, Any], _merge_control]
    # A5: 子图化入口提示 / 跨段并行派发载荷（瞬态，入口路由消费后清空）。
    subgraph_entry: Annotated[str | None, _merge_control]
    pending_dispatches: Annotated[list[dict[str, Any]], _merge_control]


class WorkflowOutput(TypedDict, total=False):
    """Application-facing output projection (A6).

    Only these control keys are visible to a direct ``invoke`` caller; the
    checkpoint keeps the full internal ``WorkflowState`` (including messages,
    worker results and stage-local runtime).  Mirrors
    :func:`project_workflow_state`.
    """

    run_id: str
    session_id: str
    branch_id: str
    phase: str
    active_stage: str
    status: str
    delivery_status: str
    context_ref: dict[str, Any]
    context_fingerprint: str
    artifact_refs: dict[str, Any]
    gate_ref: Any
    retry: dict[str, Any]
    interrupt_ref: Any
    terminal_ref: Any


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


def _interrupt_projection(state: dict[str, Any]) -> ArtifactRef | dict[str, Any] | None:
    """Normalize HUMAN and step-mode legacy channels into one small payload.

    An already-resumed interrupt (human_review_resume_consumed=True) must not
    be presented again: presenting it makes the operator/test resubmit the
    same event_id and get a 409 conflict (idempotency: consumed checkpoints
    are never re-shown; a fresh interrupt resets consumed=False).
    """

    if state.get("human_review_resume_consumed"):
        return None
    raw = state.get("interrupt_ref") or state.get("human_interrupt")
    if isinstance(raw, ArtifactRef):
        return raw
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
        "l3_gate",
        "l2_gate",
        "l1_gate",
    ):
        ref = (state.get("artifact_refs") or {}).get(key)
        if ref:
            return ref
    return None


def control_state_from_checkpoint(state: dict[str, Any]) -> WorkflowState:
    """Named application-facing alias for checkpoint projection."""

    return project_workflow_state(state)


__all__ = [
    "GATE_LOAD_FAILED",
    "GATE_STAGES",
    "RootGateResolutionError",
    "WorkflowOutput",
    "WorkflowState",
    "control_state_from_checkpoint",
    "load_root_gate",
    "project_workflow_state",
    "root_gate_route",
]
