"""Shared node helpers: checkpoint-safe serialization and execution error accumulation."""

from __future__ import annotations

from functools import wraps
from typing import Any, Awaitable, Callable

from app.agent.execute.execute_state import ExecuteAgentState


def _checkpoint_safe(value: Any) -> Any:
    """Convert NumPy scalar containers to checkpoint-serializable primitives."""
    # Worker input adapters historically used ``SimpleNamespace`` for parcels.
    # That object is convenient inside a worker but msgpack cannot persist it
    # in a LangGraph checkpoint (the failure only surfaced when resuming HUMAN).
    # Convert it at the subgraph boundary; downstream parcel helpers accept
    # both mapping and attribute-shaped values.
    from types import SimpleNamespace

    if isinstance(value, SimpleNamespace):
        return {str(key): _checkpoint_safe(item) for key, item in vars(value).items()}
    module_name = type(value).__module__
    if module_name == "numpy" or module_name.startswith("numpy."):
        if hasattr(value, "item"):
            return _checkpoint_safe(value.item())
        if hasattr(value, "tolist"):
            return _checkpoint_safe(value.tolist())
    if isinstance(value, dict):
        return {key: _checkpoint_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_checkpoint_safe(item) for item in value]
    return value


def _checkpoint_safe_node(
    node: Callable[[ExecuteAgentState], Awaitable[dict]],
) -> Callable[[ExecuteAgentState], Awaitable[dict]]:
    @wraps(node)
    async def wrapped(state: ExecuteAgentState) -> dict:
        return _checkpoint_safe(await node(state))

    return wrapped


def _execution_error(
    state: ExecuteAgentState,
    stage: str,
    code: str,
    message: str,
) -> dict:
    issue = {"stage": stage, "code": code, "message": message}
    existing = list(state.execution_errors or [])
    if not any(
        item.get("stage") == stage and item.get("code") == code
        for item in existing
    ):
        existing.append(issue)
    return {"execution_errors": existing}
