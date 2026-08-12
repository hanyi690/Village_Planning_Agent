"""Deterministic display styling for current and planned land-use layers.

This module is presentation-only. It reads labels/codes already present in
the data snapshot and adds a frontend display color to the render projection.
It never creates or normalizes a planning classification.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Mapping


_LABEL_FIELDS = (
    "planning_canonical_name", "planning_name", "planning_land_use",
    "planned_landuse", "planned_land_use", "planning_landuse",
    "canonical_name", "GHYTMC", "GHFLMC", "assigned_zone", "zone_type",
    "DLMC", "dlmc", "SDDLMC", "sddlmc", "landuse_name", "landuse",
)
_CODE_FIELDS = (
    "planning_code", "GHYTBM", "ghytbm", "GHFLBM", "ghflbm",
    "DLBM", "dlbm", "SDDLBM", "sddlbm",
)
_LABEL_COLORS = {
    "耕地": "#e8d66b", "园地": "#b8d979", "林地": "#4f9d69",
    "草地": "#8bcf75", "水域": "#6fb7d6", "湿地": "#79c7bd",
    "宅基地": "#f2ad72", "居住用地": "#f2ad72",
    "公共服务设施用地": "#79a9d8", "公共服务用地": "#79a9d8",
    "产业用地": "#c69b72", "经营性建设用地": "#d9825b",
    "交通用地": "#8b8f98", "村内交通用地": "#9ea3aa",
    "对外交通用地": "#6e747c", "水利设施用地": "#4f91bd",
    "生态绿地": "#69b578", "生态保护区": "#5aa66a",
    "生态修复区": "#86bd6d", "保护区": "#7899c9",
}
# Display fallback only; this is not a planning crosswalk and is never
# written back as a classification field.
_CODE_COLORS = {
    "1100": "#e8d66b", "1200": "#b8d979", "1300": "#4f9d69",
    "1400": "#8bcf75", "2100": "#f2ad72", "2121": "#f2ad72",
    "2200": "#79a9d8", "3100": "#6fb7d6", "3200": "#4f91bd",
}
_FALLBACK_COLORS = ("#c6a0d9", "#e3a07d", "#91b7c7", "#d0b66f", "#87b58b", "#b3a6d1")


def _first_value(properties: Mapping[str, Any], names: tuple[str, ...]) -> str:
    folded = {str(key).casefold(): value for key, value in properties.items()}
    for name in names:
        value = properties.get(name, folded.get(name.casefold()))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def classification_color(properties: Mapping[str, Any], fallback: str = "#cbd5e1") -> str:
    """Return a stable display color from existing source properties."""
    explicit = str(properties.get("color") or "").strip()
    if explicit:
        return explicit
    label = _first_value(properties, _LABEL_FIELDS)
    for name, color in _LABEL_COLORS.items():
        if label == name or name in label or label in name:
            return color
    code = _first_value(properties, _CODE_FIELDS)
    if code in _CODE_COLORS:
        return _CODE_COLORS[code]
    if label or code:
        digest = hashlib.sha256(f"{label}|{code}".encode("utf-8")).digest()
        return _FALLBACK_COLORS[digest[0] % len(_FALLBACK_COLORS)]
    return fallback


def colorize_feature_collection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a FeatureCollection and add per-feature display colors."""
    output = deepcopy(dict(payload))
    features = []
    for feature in output.get("features") or []:
        item = deepcopy(feature)
        properties = dict(item.get("properties") or {})
        properties["color"] = classification_color(properties)
        item["properties"] = properties
        features.append(item)
    output["features"] = features
    return output


__all__ = ["classification_color", "colorize_feature_collection"]
