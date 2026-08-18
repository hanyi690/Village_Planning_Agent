"""Source-backed bindings from typed existing facility targets to GIS IDs."""

from __future__ import annotations

import re
from typing import Any, Sequence


_SOURCE_GROUP_BY_TARGET_TYPE = {
    "公交站": "公交站",
    "公交站点": "公交站",
    "公交站亭": "公交站",
    "文化展示设施": "祠堂",
    "文化活动中心": "祠堂",
    "祠堂": "祠堂",
}


def _declared_quantity(intervention: Any) -> int | None:
    params = getattr(intervention, "facility_parameters", None)
    capacity = getattr(params, "capacity", None) if params is not None else None
    for candidate in (
        capacity,
        (getattr(intervention, "spatial_requirements", {}) or {}).get("quantity"),
        (getattr(intervention, "spatial_requirements", {}) or {}).get("count"),
    ):
        if isinstance(candidate, (int, float)) and float(candidate).is_integer() and candidate > 0:
            return int(candidate)
    scale = str(getattr(intervention, "scale", "") or "").strip()
    texts = [scale]
    requirements = getattr(intervention, "spatial_requirements", {}) or {}
    texts.extend([
        str(requirements.get("location") or ""),
        *(str(item) for item in requirements.get("location_hints", []) or []),
        str(getattr(intervention, "name", "") or ""),
        str(getattr(intervention, "problem_addressed", "") or ""),
    ])
    for text in texts:
        match = re.search(r"(?<!\d)(\d+)\s*处", text)
        if match:
            return int(match.group(1))
    return None


def bind_existing_facility_source_features(
    intervention: Any,
    source_features: Sequence[Any] = (),
) -> list[str]:
    """Return all source IDs iff typed group and declared quantity agree.

    A missing quantity, unsupported semantic type, missing source ID, or
    count mismatch returns an empty list.  No first member, text substring,
    coordinate, centroid, or parcel operation is used.
    """
    if getattr(intervention, "category", "") != "facility":
        return []
    action = str(getattr(intervention, "intervention_action", "") or "")
    params = getattr(intervention, "facility_parameters", None)
    typed_action = str(getattr(params, "action", "") or "") if params else ""
    if action not in {"preserve", "upgrade", "repair"} and typed_action not in {
        "preserve", "upgrade", "repair",
    }:
        text = " ".join([
            str(getattr(intervention, "name", "") or ""),
            str(getattr(intervention, "problem_addressed", "") or ""),
            str((getattr(intervention, "spatial_requirements", {}) or {}).get("location") or ""),
        ])
        if not any(marker in text for marker in ("现状", "升级", "改造", "修缮", "维护", "保留", "活化")):
            return []
    expected = str(getattr(params, "facility_type", "") or "").strip() if params else ""
    source_group = _SOURCE_GROUP_BY_TARGET_TYPE.get(expected)
    quantity = _declared_quantity(intervention)
    if not source_group or quantity is None:
        return []
    ids: list[str] = []
    for feature in source_features:
        raw = getattr(feature, "_raw", {}) or {}
        source_id = str(raw.get("source_feature_id") or "").strip()
        semantic_type = str(raw.get("source_semantic_type") or "").strip()
        if source_id and semantic_type == source_group:
            ids.append(source_id)
    ids = list(dict.fromkeys(ids))
    return ids if len(ids) == quantity else []


def _declared_road_quantity(intervention: Any) -> int | None:
    """Read an explicit existing-road count from the typed adapter fields.

    Road semantics do not have a generic ``capacity`` field.  A count is
    therefore accepted only from the structured requirement keys (or the
    narrow ``N条/段`` scale notation).  It is never inferred from a village,
    a road name, or a parcel candidate pool.
    """
    requirements = getattr(intervention, "spatial_requirements", {}) or {}
    for key in ("source_feature_count", "quantity", "count"):
        value = requirements.get(key)
        if isinstance(value, (int, float)) and float(value).is_integer() and value > 0:
            return int(value)
    scale = str(getattr(intervention, "scale", "") or "").strip()
    match = re.search(r"(?<!\d)(\d+)\s*(?:条|段)(?:道路|路)?", scale)
    return int(match.group(1)) if match else None


def bind_existing_road_source_features(
    intervention: Any,
    source_features: Sequence[Any] = (),
) -> list[str]:
    """Bind an existing road/axis target to source-backed line features.

    The adapter has two deliberately explicit paths:

    * ``source_feature_ids``/``existing_road_feature_ids`` names the exact
      source features and every ID must be present in the current-road layer;
    * a structured existing-road count may bind *all* current-road features
      only when the declared count equals the source count.

    A new corridor, a count mismatch (for example 275 requested vs 131
    source lines), an absent source ID, or non-line source geometry returns an
    empty list.  Callers then retain the normal corridor/candidate/deferred
    path.  No text matching, centroid, parcel union, or synthetic line is
    used here.
    """
    if getattr(intervention, "category", "") not in {"road", "axis"}:
        return []

    params = getattr(intervention, "road_parameters", None)
    if params is None:
        params = getattr(intervention, "linear_parameters", None)
    if params is None:
        params = getattr(intervention, "axis_parameters", None)
    action = str(getattr(intervention, "intervention_action", "") or "")
    typed_action = str(getattr(params, "action", "") or "") if params else ""
    existing_actions = {"preserve", "upgrade", "widen", "harden", "repair"}
    if action not in existing_actions and typed_action not in existing_actions:
        return []

    valid: dict[str, Any] = {}
    for feature in source_features:
        raw = getattr(feature, "_raw", {}) or {}
        source_id = str(raw.get("source_feature_id") or "").strip()
        geometry = getattr(feature, "geometry", None)
        geometry_type = geometry.get("type") if isinstance(geometry, dict) else ""
        if source_id and geometry_type in {"LineString", "MultiLineString"}:
            valid.setdefault(source_id, feature)
    if not valid:
        return []

    requirements = getattr(intervention, "spatial_requirements", {}) or {}
    raw_ids = None
    for key in ("source_feature_ids", "existing_road_feature_ids", "road_feature_ids"):
        if key in requirements:
            raw_ids = requirements.get(key)
            break
    if raw_ids is not None:
        if not isinstance(raw_ids, (list, tuple, set)):
            return []
        requested = list(dict.fromkeys(
            str(item).strip() for item in raw_ids if str(item).strip()
        ))
        if not requested or any(item not in valid for item in requested):
            return []
        return requested

    quantity = _declared_road_quantity(intervention)
    if quantity is None or quantity != len(valid):
        return []
    return list(valid)


__all__ = [
    "bind_existing_facility_source_features",
    "bind_existing_road_source_features",
]
