"""Deterministic spatial-language normalization helpers."""

from __future__ import annotations


_DIRECTION_RULES = (
    ("东北", "northeast"),
    ("西北", "northwest"),
    ("东南", "southeast"),
    ("西南", "southwest"),
    ("东部", "east"),
    ("东侧", "east"),
    ("东边", "east"),
    ("东", "east"),
    ("西部", "west"),
    ("西侧", "west"),
    ("西边", "west"),
    ("西", "west"),
    ("北部", "north"),
    ("北侧", "north"),
    ("北边", "north"),
    ("北", "north"),
    ("南部", "south"),
    ("南侧", "south"),
    ("南边", "south"),
    ("南", "south"),
    ("中部", "center"),
    ("中心", "center"),
    ("中", "center"),
)


def direction_from_location(location: str) -> str:
    """Map Chinese location text to the first matching direction enum."""
    if not location:
        return ""
    for keyword, direction in _DIRECTION_RULES:
        if keyword in location:
            return direction
    return ""


__all__ = ["direction_from_location"]
