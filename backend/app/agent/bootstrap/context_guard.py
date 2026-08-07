"""Shared invariant guard: context must be frozen before artifact persist."""
from typing import Any, Dict


def require_frozen_context(state: Dict[str, Any]) -> None:
    """Assert that PlanningContext is established before persisting artifacts.

    Validates:
    - context_version is non-empty
    - context_ref is present with non-empty version and session_id
    - context_ref.version matches context_version
    - context_ref.session_id matches state session_id
    """
    context_version = str(state.get("context_version", ""))
    if not context_version:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: cannot persist versioned artifact with empty "
            "context_version. bootstrap_context must run first."
        )
    context_ref = state.get("context_ref") or {}
    if not context_ref:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: context_ref is missing or empty. "
            "bootstrap_context must populate context_ref before artifact persist."
        )
    ref_version = str(context_ref.get("version", ""))
    if not ref_version:
        raise RuntimeError(
            "CONTEXT_NOT_FROZEN: context_ref.version is empty. "
            "bootstrap_context must populate context_ref.version."
        )
    if ref_version != context_version:
        raise RuntimeError(
            f"CONTEXT_VERSION_MISMATCH: context_version={context_version} "
            f"but context_ref.version={ref_version}"
        )
    session_id = state.get("session_id", "")
    if not session_id:
        raise RuntimeError("CONTEXT_NOT_FROZEN: state.session_id is empty.")
    ref_session = str(context_ref.get("session_id", ""))
    if not ref_session:
        raise RuntimeError("CONTEXT_NOT_FROZEN: context_ref.session_id is empty.")
    if ref_session != session_id:
        raise RuntimeError(
            f"CONTEXT_SESSION_MISMATCH: state session_id={session_id} "
            f"but context_ref.session_id={ref_session}"
        )