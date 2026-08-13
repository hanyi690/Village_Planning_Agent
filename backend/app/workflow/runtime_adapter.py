"""Adapter between the compact root checkpoint and stage-local runtime data.

Stage-local keys travel as a first-class ``runtime`` channel on
``WorkflowState``, replacing the retired ``workflow_progress`` artifact.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from functools import wraps
from typing import Any

from langgraph.types import Command

from app.workflow.state import WorkflowState

_CONTROL_KEYS = set(WorkflowState.__annotations__) - {"runtime"}
_CARRIER_IDENTITY_KEYS = {"session_id", "run_id", "branch_id"}
_CARRIER_RESERVED_KEYS = _CARRIER_IDENTITY_KEYS | {"artifact_refs"}

# Top-level WorkflowState channels that carry an Annotated reducer.  LangGraph
# merges parallel workers' writes to these keys; they must not also be baked
# into the runtime channel.
_REDUCER_KEYS = frozenset(
    key
    for key, hint in typing.get_type_hints(WorkflowState, include_extras=True).items()
    if typing.get_origin(hint) is typing.Annotated
)


def _merge_value(key: str, current: Any, update: Any) -> Any:
    """Apply the reducer semantics needed by the still-migrating stages."""
    if key == "messages":
        try:
            from app.workflow.plan_state.state import _messages_reducer

            return _messages_reducer(current or [], update or [])
        except Exception:
            return [*(current or []), *(update or [])]
    if key in {"artifact_refs", "config", "metadata"}:
        result = dict(current or {})
        result.update(dict(update or {}))
        return result
    return update


def _restore_messages(messages: Any) -> Any:
    """Rehydrate LangChain messages after JSON artifact round-tripping."""
    if not isinstance(messages, list):
        return messages
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    classes = {
        "ai": AIMessage,
        "human": HumanMessage,
        "system": SystemMessage,
        "tool": ToolMessage,
    }
    restored = []
    for item in messages:
        if not isinstance(item, dict) or hasattr(item, "content"):
            restored.append(item)
            continue
        data = dict(item.get("data") or item)
        message_type = str(data.pop("type", item.get("type", ""))).lower()
        message_class = classes.get(message_type)
        if message_class is None:
            restored.append(item)
            continue
        data.pop("role", None)
        try:
            restored.append(message_class(**data))
        except (TypeError, ValueError):
            restored.append(item)
    return restored


def materialize_workflow_state(state: dict[str, Any]) -> dict[str, Any]:
    """Expose stage-local data to one node without putting it in root channels.

    Three shapes of input are handled:

    1. Compact root state carrying a ``runtime`` channel: use it directly.
    2. Read-compat shim: compact root state referencing a legacy
       ``workflow_progress`` artifact (pre-cutover checkpoints) hydrates the
       stage-local view from that carrier without writing back to it.
    3. A dynamic Send worker payload (has ``dimension_key``): the whole payload
       is the worker's task input, so it becomes the runtime view verbatim.
    """
    runtime = dict(state.get("runtime") or {})
    if not runtime and state.get("dimension_key"):
        runtime = dict(state)
    elif not runtime and (state.get("artifact_refs") or {}).get("workflow_progress"):
        from app.infrastructure.artifacts.runtime import load_artifact

        payload = load_artifact(state, "workflow_progress")
        if payload is not None:
            runtime = {
                **dict(payload.get("stage_payload") or {}),
                "session_id": payload.get("session_id", ""),
                "run_id": payload.get("run_id", ""),
                "branch_id": payload.get("branch_id", "main"),
                "artifact_refs": dict(payload.get("artifact_refs") or {}),
            }
    for key in _CONTROL_KEYS:
        if key in state and key not in {"retry", "interrupt_ref", "terminal_ref", "active_stage", "status"}:
            runtime[key] = state[key]
    if state.get("retry") is not None:
        runtime["retry_counts"] = dict(state.get("retry") or {})
    if state.get("interrupt_ref") is not None:
        runtime["human_interrupt"] = state.get("interrupt_ref")
    if state.get("terminal_ref") is not None:
        runtime["diagnostic_terminal"] = state.get("terminal_ref")
    if "messages" in runtime:
        runtime["messages"] = _restore_messages(runtime["messages"])
    return runtime


def _carrier(runtime: dict[str, Any]) -> dict[str, Any]:
    """Return the JSON-safe stage-local subset written to the runtime channel.

    Keys carried by top-level ``WorkflowState`` reducer channels are excluded:
    LangGraph merges them directly, so parallel workers do not contend on a
    shared named ref.
    """
    return {
        key: value
        for key, value in runtime.items()
        if key not in _CARRIER_RESERVED_KEYS
        and key not in _REDUCER_KEYS
    }


def _control_projection(runtime: dict[str, Any]) -> dict[str, Any]:
    phase = str(runtime.get("phase") or "")
    stage = str(runtime.get("current_stage") or runtime.get("paused_stage") or phase)
    delivery_status = str(runtime.get("delivery_status") or "")
    status = "paused" if runtime.get("human_interrupt") or runtime.get("paused_stage") else (
        "completed" if delivery_status else "running"
    )
    projection = {
        "session_id": str(runtime.get("session_id") or ""),
        "run_id": str(runtime.get("run_id") or runtime.get("session_id") or ""),
        "branch_id": str(runtime.get("branch_id") or "main"),
        "phase": phase,
        "active_stage": stage,
        "status": "failed" if runtime.get("fatal_error") else status,
        "delivery_status": delivery_status,
        "context_ref": dict(runtime.get("context_ref") or {}),
        "context_fingerprint": str(runtime.get("context_fingerprint") or ""),
        "artifact_refs": dict(runtime.get("artifact_refs") or {}),
        "retry": dict(runtime.get("retry_counts") or {}),
        "interrupt_ref": runtime.get("human_interrupt"),
        "terminal_ref": runtime.get("diagnostic_terminal"),
    }
    for key in _REDUCER_KEYS:
        if key in projection:
            continue
        if key in runtime and (
            runtime[key] is not None or key == "fatal_error"
        ):
            projection[key] = runtime[key]
    return projection


def initial_workflow_state(runtime: dict[str, Any]) -> dict[str, Any]:
    """Convert a newly-created legacy-shaped input into compact state."""
    payload = dict(runtime)
    return {"runtime": _carrier(payload), **_control_projection(payload)}


def pack_workflow_patch(state: dict[str, Any], patch: dict[str, Any]) -> WorkflowState:
    """Merge a stage patch and expose only the compact checkpoint channels."""
    runtime = materialize_workflow_state(state)
    for key, value in patch.items():
        runtime[key] = _merge_value(key, runtime.get(key), value)
    return {**_control_projection(runtime), "runtime": _carrier(runtime)}


def _adapt_command(state: dict[str, Any], command: Command) -> Command:
    """Keep dynamic routing while converting only the persisted update."""
    update = command.update
    if isinstance(update, dict):
        update = pack_workflow_patch(state, update)
    return Command(
        graph=command.graph,
        update=update,
        resume=command.resume,
        goto=command.goto,
    )


def adapt_node(node: Callable[..., Any], *, worker: bool = False) -> Callable[..., Any]:
    """Run a legacy-shaped node behind the compact root state boundary.

    ``worker=True`` marks a parallel dimension worker.  Workers project shared
    keys to top-level reducer channels only, so concurrent Send branches do not
    contend on the runtime channel.
    """
    @wraps(node)
    async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        local_state = materialize_workflow_state(state)
        result = node(local_state)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, Command):
            return _adapt_command(state, result)
        if not isinstance(result, dict):
            return result
        if worker:
            runtime = materialize_workflow_state(state)
            for key, value in result.items():
                runtime[key] = _merge_value(key, runtime.get(key), value)
            return _control_projection(runtime)
        return pack_workflow_patch(state, result)

    return wrapped


def adapt_route(route: Callable[..., str]) -> Callable[..., str]:
    """Run a routing predicate against materialized stage-local state."""
    @wraps(route)
    def wrapped(state: dict[str, Any]) -> str:
        return route(materialize_workflow_state(state))

    return wrapped


__all__ = [
    "adapt_node",
    "adapt_route",
    "initial_workflow_state",
    "materialize_workflow_state",
    "pack_workflow_patch",
]
