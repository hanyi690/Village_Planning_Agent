"""Explicit legacy-gated access to advisory crosswalks.

Wave A.1: the mapping-style planning chain is FAIL-CLOSED by default. It may
only run when the explicit legacy switch is enabled (for comparison testing),
and its output must be marked as non-planning-result.

The advisory crosswalk is never exposed to the LLM or the default active chain.
"""

from __future__ import annotations

import os

LEGACY_ENV = "GIS_LEGACY_MAPPING"


def legacy_enabled() -> bool:
    """True only when the explicit legacy switch is on."""
    return os.environ.get(LEGACY_ENV, "") == "1"


def require_legacy(context: str) -> None:
    """Raise a LegacyBlocked error if the legacy switch is off."""
    if not legacy_enabled():
        raise LegacyBlocked(
            f"{context} is part of the legacy mapping-style planning chain "
            f"(fail-closed by default). Set {LEGACY_ENV}=1 only for comparison "
            "testing; its output is NOT a planning result."
        )


class LegacyBlocked(RuntimeError):
    """Raised when a legacy mapping-style operation runs without the switch."""


def legacy_marker() -> dict:
    """Marker to attach to any legacy output: 非规划成果."""
    return {
        "legacy": True,
        "is_planning_result": False,
        "reason": "legacy mapping-style output (非规划成果)",
    }
