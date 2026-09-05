"""Shared token-budget and serialization helpers for DATA access tools."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def session_world_model(session_id: str):
    """Return the session's DATA-backed current-world read object."""
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context

        context = get_cached_context(session_id)
        if context is None:
            return None
        return (
            getattr(getattr(context, "ports", None), "current_world", None)
            or getattr(context, "world_model", None)
        )
    except Exception as e:
        logger.warning("[Access] current-world access failed for %s: %s", session_id, e)
        return None


def budget_check(payload: Dict[str, Any], hard_limit: int = 6000) -> Dict[str, Any]:
    """Annotate a payload with its CJK-aware token estimate.

    Does not hard-truncate (tools already bound their own top_k / max_chars),
    but flags oversized payloads so callers/LLM know the view is partial.
    """
    try:
        serialized = json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
        est = max(1, len(serialized) // 2)
    except Exception:
        est = len(str(payload))
    payload["_token_estimate"] = est
    if est > hard_limit:
        payload["_truncated"] = True
    return payload


def tool_reply(data: Dict[str, Any]) -> str:
    """Serialize a tool payload into the standard make_result envelope."""
    from app.infrastructure.llm.tools.helpers import make_result

    return json.dumps(make_result(True, data=data), ensure_ascii=False, default=str)


def simplify_geometry(geom: Optional[Dict[str, Any]], factor: float) -> Optional[Dict[str, Any]]:
    """Downsample geometry coordinates by ``factor`` (0..1, 1 = keep all)."""
    if not geom or factor <= 0 or factor >= 1:
        return geom
    step = max(1, int(round(1.0 / max(factor, 0.01))))
    if step <= 1:
        return geom

    def _coords(c):
        if isinstance(c, (int, float)):
            return c
        if isinstance(c, list):
            # A list of numbers is a coordinate position; a list of lists is nested.
            if c and isinstance(c[0], (int, float)):
                return c
            return [_coords(sub) for sub in c[::step]]
        return c

    return {**geom, "coordinates": _coords(geom.get("coordinates"))}


__all__ = [
    "session_world_model",
    "budget_check",
    "tool_reply",
    "simplify_geometry",
]
