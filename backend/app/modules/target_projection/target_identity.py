"""Stable target identity helpers for projection artifacts."""

from __future__ import annotations

from typing import Any


def target_identity(value: Any) -> str:
    return str(
        getattr(value, "target_id", "")
        or getattr(value, "intervention_id", "")
        or getattr(value, "physical_project_ref", "")
        or ""
    ).strip()


__all__ = ["target_identity"]
