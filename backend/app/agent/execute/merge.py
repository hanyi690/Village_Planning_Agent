"""merge_worker_results - unified WorkerResult merge into ParcelChangeSet + layout_configs.

Pure deterministic merge of the EXECUTE worker outputs. No side effects, no
I/O, no LLM. Consumed by the ``merge_worker_results`` node in execute_agent.py
and unit-testable in isolation.

Responsibilities:
- BSM conflict detection: the same bsm appearing in more than one worker's
  ``parcel_changes`` with a different ``after_classification`` code is recorded
  as a ``bsm_conflict`` diagnostic (not silently merged away).
- layout_configs dedup by layerType: the higher-priority (later) worker wins
  when two workers emit the same layer type.
- Build the unified ``ParcelChangeSet`` via
  ``land_design_worker.build_parcel_change_set``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.agent.execute.land_design_worker import build_parcel_change_set
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet

# Later workers win when two workers emit the same layerType.
_WORKER_PRIORITY: Dict[str, int] = {
    "project": 0,
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


def _detect_bsm_conflicts(worker_results: List[Any]) -> List[Dict[str, Any]]:
    """Detect same-bsm changes with conflicting after_classification across workers."""
    by_bsm: Dict[str, List[Tuple[Any, Any]]] = {}
    for result in worker_results or []:
        for change in _result_get(result, "parcel_changes") or []:
            bsm = _change_bsm(change)
            if not bsm:
                continue
            by_bsm.setdefault(bsm, []).append((result, change))

    conflicts: List[Dict[str, Any]] = []
    for bsm, entries in by_bsm.items():
        codes = {_change_after_code(change) for _result, change in entries}
        if len(codes) > 1:
            conflicts.append(
                {
                    "type": "bsm_conflict",
                    "bsm": bsm,
                    "workers": [
                        {
                            "worker_type": _result_get(result, "worker_type", ""),
                            "action": getattr(change, "action", ""),
                            "after_code": _change_after_code(change),
                        }
                        for result, change in entries
                    ],
                }
            )
    return conflicts


def _dedup_layout_configs(worker_results: List[Any]) -> List[Dict[str, Any]]:
    """Dedup layout_configs by layerType; higher-priority (later) worker wins."""
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
            merged[layer_type] = config
    return list(merged.values())


def merge_worker_results(
    worker_results: List[Any],
) -> Tuple[ParcelChangeSet, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Merge WorkerResults into a unified (ParcelChangeSet, layout_configs, diagnostics).

    - BSM conflict detection: same bsm in multiple workers with different
      after_classification -> ``bsm_conflict`` diagnostic.
    - layout_configs deduped by layerType (later worker wins by priority).
    - ParcelChangeSet built via ``land_design_worker.build_parcel_change_set``.

    Returns:
        (parcel_changeset, merged_layout_configs, diagnostics)
    """
    conflicts = _detect_bsm_conflicts(worker_results)

    changes: List[ParcelChange] = []
    for result in worker_results or []:
        changes.extend(_result_get(result, "parcel_changes") or [])

    changeset = build_parcel_change_set(changes)
    layout_configs = _dedup_layout_configs(worker_results)
    return changeset, layout_configs, list(conflicts)


__all__ = [
    "merge_worker_results",
    "_detect_bsm_conflicts",
    "_dedup_layout_configs",
]
