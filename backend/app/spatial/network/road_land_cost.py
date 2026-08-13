"""Shared deterministic land-friction rule for road alternatives and grids."""

from __future__ import annotations

from typing import Any


ROAD_LAND_WEIGHT_RULE_VERSION = "road_land_weight_v1"


def road_land_weight(value: Any, code: Any = None) -> float:
    """Return the existing Stage-4 relative land occupation weight.

    Keeping this rule in one module prevents vector candidate scoring and the
    raster cost surface from silently using different planning semantics.
    """

    code_text = str(code or "")
    if code_text == "2126" or code_text.startswith("22"):
        return 0.5
    if code_text.startswith("31"):
        return 50.0
    if code_text in {"2121", "2122", "2124", "2125"}:
        return 10.0
    if code_text.startswith(("11", "12")):
        return 6.0
    if code_text.startswith("13"):
        return 3.0
    if code_text.startswith("14"):
        return 2.5
    text = str(value or "")
    if "道路" in text or "交通" in text:
        return 0.5
    if "水域" in text:
        return 50.0
    if any(token in text for token in ("宅基地", "住宅", "商业", "工矿", "工业", "公共管理")):
        return 10.0
    if any(token in text for token in ("耕地", "园地")):
        return 6.0
    if any(token in text for token in ("林地", "草地")):
        return 3.0
    return 2.0


__all__ = ["ROAD_LAND_WEIGHT_RULE_VERSION", "road_land_weight"]
