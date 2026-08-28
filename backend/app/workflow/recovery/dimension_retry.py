"""Small, stage-neutral retry decisions for one failed dimension.

The business worker reports the exact failed producer and its persisted retry
counter. This module only decides whether that producer may be invoked again;
it never selects another dimension and never changes an artifact.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def schedule_dimension_retry(
    state: Mapping[str, Any],
    dimension_key: str,
    retry_counts: Mapping[str, Any],
) -> list[str]:
    """Return ``[dimension_key]`` while the explicit retry budget remains."""

    key = str(dimension_key or "").strip()
    if not key:
        return []
    try:
        limit = max(0, int(state.get("dimension_retry_limit") or 1))
        attempts = int(retry_counts.get(key, 0))
    except (TypeError, ValueError):
        return []
    return [key] if attempts <= limit else []


__all__ = ["schedule_dimension_retry"]
