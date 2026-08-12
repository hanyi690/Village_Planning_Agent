"""Pure checkpoint classification helpers.

Kept outside API routers so checkpoint policy can be tested and reused by
runtime/recovery code without importing the route graph.
"""

from __future__ import annotations

from typing import Any, Dict


def has_pending_interrupt(snapshot: Any) -> bool:
    return bool(
        snapshot
        and any(getattr(task, "interrupts", None) for task in (snapshot.tasks or ()))
    )


def first_pending_interrupt_payload(snapshot: Any) -> Dict[str, Any] | None:
    """Return the first JSON interrupt payload for checkpoint projection."""

    if not snapshot:
        return None
    for task in snapshot.tasks or ():
        for interrupt in getattr(task, "interrupts", None) or ():
            payload = getattr(interrupt, "value", None)
            if isinstance(payload, dict):
                return payload
    return None


def classify_checkpoint(
    values: Dict[str, Any],
    *,
    pending_interrupt: bool = False,
) -> tuple[bool, str]:
    """Return ``(stable, kind)`` without relying on legacy flags."""

    if not values:
        return False, "intermediate"
    if values.get("phase") == "completed":
        return True, "completed"
    if values.get("last_revised_dimensions") and not values.get("is_revision", False):
        return True, "revision"
    if pending_interrupt or values.get("human_interrupt"):
        return True, "human"
    if (
        values.get("previous_layer", 0) > 0
        and values.get("layer_just_completed") == values.get("previous_layer")
    ):
        return True, "layer"
    return False, "intermediate"


__all__ = ["classify_checkpoint", "first_pending_interrupt_payload", "has_pending_interrupt"]
