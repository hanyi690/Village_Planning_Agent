"""Constraint adjustment helpers for EXECUTE input preparation."""

from __future__ import annotations

from typing import Any, Dict, List


def _adjustment_get(adjustment: Any, key: str, default: Any = None) -> Any:
    """Read a field from a legacy adjustment dict or an attribute-carrying object."""
    if isinstance(adjustment, dict):
        return adjustment.get(key, default)
    value = getattr(adjustment, key, None)
    return default if value is None else value


def _apply_constraint_adjustments(zone_targets: list, adjustments: list) -> list:
    """Apply constraint_adjustments (legacy {zone, delta_ha} shape) to zone targets.

    Matches each adjustment to a zone target by land_use / planning_zone /
    zone_id and shifts its area_ha target by delta_ha (positive or negative).
    Unmatched zones are skipped safely. Returns the applied adjustments.
    """
    applied: List[dict] = []
    if not adjustments:
        return applied
    target_by_zone: Dict[str, Any] = {}
    for target in zone_targets:
        for key in (
            getattr(target, "land_use", None),
            getattr(target, "planning_zone", None),
            getattr(target, "zone_id", None),
        ):
            if key:
                target_by_zone.setdefault(str(key), target)
    for adjustment in adjustments or []:
        zone = _adjustment_get(adjustment, "zone", "")
        if not zone:
            continue
        target = target_by_zone.get(str(zone))
        if target is None:
            continue
        delta_ha = _adjustment_get(adjustment, "delta_ha", 0.0) or 0.0
        try:
            delta_ha = float(delta_ha)
        except (TypeError, ValueError):
            delta_ha = 0.0
        current = getattr(target, "area_ha", None)
        setattr(target, "area_ha", (float(current) if current is not None else 0.0) + delta_ha)
        applied.append(adjustment)
    return applied