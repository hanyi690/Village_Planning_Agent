"""Deterministic scenario ranking helpers."""

from __future__ import annotations

from typing import Any


def rank_scenarios(scenarios: list[Any]) -> list[Any]:
    return sorted(
        scenarios,
        key=lambda item: (
            str(getattr(item, "status", "")),
            str(getattr(item, "scenario_id", "")),
        ),
    )


__all__ = ["rank_scenarios"]
