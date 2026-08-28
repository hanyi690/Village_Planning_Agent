"""Shared constraint-code vocabulary used by planning stages."""

from __future__ import annotations


PROHIBITED_LAND_CONSTRAINTS = frozenset({
    "farmland_protection",
    "ecological_redline",
    "historical_protection",
    "cultivated_land_target",
    "hazard_control_line",
    "flood_control_line",
})


__all__ = ["PROHIBITED_LAND_CONSTRAINTS"]
