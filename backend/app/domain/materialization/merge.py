"""merge_worker_results - unified WorkerResult merge into ParcelChangeSet + layout_configs.

Pure deterministic merge of the EXECUTE worker outputs. No side effects, no
I/O, no LLM. Consumed by the ``merge_worker_results`` node in execute_agent.py
and unit-testable in isolation.

Responsibilities:
- BSM ownership enforcement: more than one authoritative write to the same BSM
  blocks the whole ParcelChangeSet, even when classification codes match.
- layout_configs dedup by layerType: the higher-priority (later) worker wins
  when two workers emit the same layer type.
- Build the unified ``ParcelChangeSet`` via
  ``land_design_worker.build_parcel_change_set``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.domain.materialization.land_design_worker import build_parcel_change_set
from app.contracts.workflow.execution_plan_contracts import TypedActionResult
from app.contracts.spatial.parcel_change_contracts import ParcelChange, ParcelChangeSet

# Later workers win when two workers emit the same layerType.
_WORKER_PRIORITY: Dict[str, int] = {
    "site_area": 0,
    "zone": 1,
    "facility": 2,
    "axis": 3,
    "road": 4,
}

_DEFAULT_PRIORITY = 99


def _result_get(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _change_bsm(change: Any) -> str:
    return str(getattr(change, "bsm", None) or "")


def _change_after_code(change: Any) -> str:
    cls = getattr(change, "after_classification", None)
    return str(getattr(cls, "code", None) or "")


def _change_after_wkt(change: Any) -> str:
    return str(getattr(change, "after_geometry_wkt", None) or "")


def _change_source_bsms(change: Any) -> set[str]:
    values = getattr(change, "derived_from_bsms", None) or []
    if isinstance(values, str):
        values = [values]
    return {str(value).strip() for value in values if str(value).strip()}


def _detect_bsm_conflicts(worker_results: List[Any]) -> List[Dict[str, Any]]:
    """Detect conflicting authoritative writes to source parcels.

    A worker may split a source parcel and therefore emit a derived BSM rather
    than reusing the source BSM.  Result-BSM uniqueness alone would miss an
    overlapping project/road write, so source lineage and resulting geometry
    are checked together.  Disjoint sub-geometries from one source parcel are
    valid and remain independently materializable.
    """
    by_bsm: Dict[str, List[Tuple[Any, Any]]] = {}
    authoritative: list[tuple[Any, Any]] = []
    for result in worker_results or []:
        for change in _result_get(result, "parcel_changes") or []:
            bsm = _change_bsm(change)
            action = str(getattr(change, "action", "") or "")
            if not bsm or action == "preserve":
                continue
            if not _change_after_code(change):
                continue
            by_bsm.setdefault(bsm, []).append((result, change))
            authoritative.append((result, change))

    conflicts: List[Dict[str, Any]] = []
    for bsm, entries in by_bsm.items():
        if len(entries) > 1:
            target_ids = sorted({
                str(getattr(change, "intervention_id", "") or "")
                for _, change in entries
                if str(getattr(change, "intervention_id", "") or "")
            })
            conflicts.append(
                {
                    "type": "bsm_conflict",
                    "code": "authoritative_land_use_conflict",
                    "blocking": True,
                    "bsm": bsm,
                    "affected_bsms": [bsm],
                    "target_ids": target_ids,
                    "violation_id": (
                        "authoritative_land_use_conflict:"
                        + bsm
                        + ":"
                        + ":".join(target_ids)
                    ),
                    "evidence_refs": [
                        f"parcel-change:{bsm}:{target_id}" for target_id in target_ids
                    ],
                    "workers": [
                        {
                            "worker_type": _result_get(result, "worker_type", ""),
                            "action": getattr(change, "action", ""),
                            "after_code": _change_after_code(change),
                            "target_id": str(
                                getattr(change, "intervention_id", "") or ""
                            ),
                            "lineage_ref": str(
                                getattr(change, "project_ref", "") or ""
                            ),
                        }
                        for result, change in entries
                    ],
                }
            )

    from shapely import wkt

    parsed: list[tuple[Any, Any, Any]] = []
    for result, change in authoritative:
        source_bsms = _change_source_bsms(change)
        geometry = None
        try:
            geometry = wkt.loads(_change_after_wkt(change))
            if geometry.is_empty or not geometry.is_valid:
                geometry = None
        except Exception:
            geometry = None
        if source_bsms and geometry is not None:
            parsed.append((result, change, geometry))
    for index, (left_result, left_change, left_geometry) in enumerate(parsed):
        for right_result, right_change, right_geometry in parsed[index + 1:]:
            if not (_change_source_bsms(left_change) & _change_source_bsms(right_change)):
                continue
            if str(_result_get(left_result, "worker_type", "")) == str(
                _result_get(right_result, "worker_type", "")
            ) and str(getattr(left_change, "intervention_id", "") or "") == str(
                getattr(right_change, "intervention_id", "") or ""
            ):
                continue
            try:
                overlap = left_geometry.intersection(right_geometry)
                if overlap.is_empty or float(overlap.area) <= 1e-12:
                    continue
            except Exception:
                continue
            source_bsms = sorted(
                _change_source_bsms(left_change) & _change_source_bsms(right_change)
            )
            target_ids = sorted({
                str(getattr(left_change, "intervention_id", "") or ""),
                str(getattr(right_change, "intervention_id", "") or ""),
            } - {""})
            conflicts.append({
                "type": "source_parcel_overlap",
                "code": "authoritative_source_geometry_overlap",
                "blocking": True,
                "source_bsms": source_bsms,
                "target_ids": target_ids,
                "overlap_area": float(overlap.area),
                "workers": [
                    {
                        "worker_type": _result_get(left_result, "worker_type", ""),
                        "bsm": _change_bsm(left_change),
                        "action": getattr(left_change, "action", ""),
                        "target_id": str(getattr(left_change, "intervention_id", "") or ""),
                    },
                    {
                        "worker_type": _result_get(right_result, "worker_type", ""),
                        "bsm": _change_bsm(right_change),
                        "action": getattr(right_change, "action", ""),
                        "target_id": str(getattr(right_change, "intervention_id", "") or ""),
                    },
                ],
            })
    return conflicts


def _dedup_layout_configs(worker_results: List[Any]) -> List[Dict[str, Any]]:
    """Merge layout configs by layer type without dropping task outputs.

    EXECUTE now runs one immutable task per worker invocation.  Replacing a
    same-typed layer with the last worker (the historical grouped-worker
    behavior) silently discarded all but the final candidate and produced an
    empty-looking delivery map.  Keep one deterministic layer per type while
    concatenating its feature collections.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    ordered = sorted(
        worker_results or [],
        key=lambda r: _WORKER_PRIORITY.get(_result_get(r, "worker_type", ""), _DEFAULT_PRIORITY),
    )
    for result in ordered:
        for config in _result_get(result, "layers") or []:
            layer_type = (
                config.get("layerType") if isinstance(config, dict) else getattr(config, "layerType", None)
            ) or (
                config.get("layer_type") if isinstance(config, dict) else getattr(config, "layer_type", None)
            ) or ""
            if not layer_type:
                continue
            current = merged.get(layer_type)
            if current is None:
                merged[layer_type] = dict(config)
                continue
            current_data = current.setdefault("data", current.get("geojson") or {})
            incoming_data = config.get("data") or config.get("geojson") or {}
            current_features = list(current_data.get("features") or [])
            incoming_features = list(incoming_data.get("features") or [])
            seen = {
                str((item.get("properties") or {}).get("feature_id") or "")
                for item in current_features
                if isinstance(item, dict)
            }
            for feature in incoming_features:
                feature_id = str(
                    (feature.get("properties") or {}).get("feature_id") or ""
                ) if isinstance(feature, dict) else ""
                if feature_id and feature_id in seen:
                    continue
                current_features.append(feature)
                if feature_id:
                    seen.add(feature_id)
            current_data["type"] = incoming_data.get("type") or current_data.get("type") or "FeatureCollection"
            current_data["features"] = current_features
            current["data"] = current_data
            current["geojson"] = current_data
    return list(merged.values())


def _collect_action_results(worker_results: List[Any]) -> List[TypedActionResult]:
    """Collect typed non-spatial results without converting them into parcels."""
    action_results: List[TypedActionResult] = []
    for result in worker_results or []:
        for action_result in _result_get(result, "action_results") or []:
            if isinstance(action_result, TypedActionResult):
                action_results.append(action_result)
            elif isinstance(action_result, dict):
                action_results.append(TypedActionResult(**action_result))
    return action_results


def _verify_geometry_valid(changes: list) -> bool:
    """True when every change carries a non-empty, valid WKT geometry."""
    if not changes:
        return False
    from shapely import wkt

    for change in changes or []:
        aw = str(getattr(change, "after_geometry_wkt", "") or "")
        if not aw:
            return False
        try:
            geom = wkt.loads(aw)
            if geom.is_empty or not geom.is_valid:
                return False
        except Exception:
            return False
    return True


def _verify_area_conservation(changes: list) -> bool:
    """True when non-create changes preserve a positive area (create adds area)."""
    for change in changes or []:
        action = str(getattr(change, "action", "") or "")
        if action in ("create",):
            continue
        area = float(getattr(change, "new_area_ha", 0.0) or 0.0)
        if area <= 0:
            return False
    return True


def merge_worker_results(
    worker_results: List[Any],
) -> Tuple[ParcelChangeSet, List[Dict[str, Any]], List[Dict[str, Any]], List[TypedActionResult]]:
    """Merge WorkerResults into parcel, layout, diagnostics, and action outputs.

    - Any duplicate authoritative BSM write blocks all parcel changes.
    - layout_configs deduped by layerType (later worker wins by priority).
    - ParcelChangeSet built via ``land_design_worker.build_parcel_change_set``
      with area-conservation and geometry-validity flags derived from the
      merged changes.

    Returns:
        (parcel_changeset, merged_layout_configs, diagnostics, action_results)
    """
    conflicts = _detect_bsm_conflicts(worker_results)

    changes: List[ParcelChange] = []
    for result in worker_results or []:
        changes.extend(_result_get(result, "parcel_changes") or [])

    if conflicts:
        changes = []

    changeset = build_parcel_change_set(
        changes,
        area_conservation_verified=(
            not conflicts and _verify_area_conservation(changes)
        ),
        geometry_validity_verified=(
            not conflicts and _verify_geometry_valid(changes)
        ),
    )
    layout_configs = _dedup_layout_configs(worker_results)
    return changeset, layout_configs, list(conflicts), _collect_action_results(worker_results)


__all__ = [
    "merge_worker_results",
    "_detect_bsm_conflicts",
    "_dedup_layout_configs",
    "_collect_action_results",
]
