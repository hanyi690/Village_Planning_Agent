"""Fail-closed EXECUTE boundary diagnostics.

This module contains only the classification admission check.  It is kept
separate from the retired plan builder so EXECUTE cannot import or discover a
legacy plan-construction path.
"""

from __future__ import annotations

from typing import Any

from app.contracts.artifacts.deferral_contracts import DeferralLedger
from app.contracts.workflow.execution_plan_contracts import ExecutionPlan

_CLASSIFICATION_OUTPUT_KINDS = frozenset({"parcel", "polygon"})
_TASK_SPECS = (
    ("site_area", "site_area_targets"),
    ("zone", "zone_targets"),
    ("zone", "custom_zone_targets"),
    ("facility", "facilities"),
    ("axis", "development_axes"),
    ("road", "road_targets"),
    ("linear", "linear_targets"),
)


def _value(target: Any, name: str, default: Any = None) -> Any:
    if isinstance(target, dict):
        return target.get(name, default)
    return getattr(target, name, default)


def _unwrap_intent(intent: Any) -> Any:
    return getattr(intent, "typed_intent", None) or intent


def _items(intent: Any, name: str) -> list[Any]:
    value = intent.get(name) if isinstance(intent, dict) else getattr(intent, name, None)
    if not value and name == "site_area_targets":
        value = intent.get("project_targets") if isinstance(intent, dict) else getattr(intent, "project_targets", None)
    return list(value or [])


def _classification_status(target: Any) -> str:
    decision = _value(target, "classification_decision")
    status = _value(decision, "status") if decision is not None else "missing"
    return str(getattr(status, "value", status) or "unresolved")


def _classification_required(target: Any, assignment: Any) -> bool:
    role = _value(target, "materialization_role") or _value(assignment, "materialization_role")
    if not role:
        role = _value(_value(assignment, "target_binding", {}) or {}, "materialization_role")
    if role in {"functional_overlay", "protection_overlay", "restoration_overlay"}:
        return False
    if _value(target, "category_code") and _value(target, "vocabulary_name"):
        return True
    return bool({
        str(_value(target, "expected_output_kind", "") or ""),
        str(_value(assignment, "expected_output_kind", "") or ""),
    } & _CLASSIFICATION_OUTPUT_KINDS)


def _target_index(intent: Any) -> dict[str, Any]:
    return {
        str(_value(target, "target_id", "")): target
        for _, field_name in _TASK_SPECS
        for target in _items(intent, field_name)
        if str(_value(target, "target_id", "") or "")
    }


def _deferred_target_ids(ledger: Any) -> set[str]:
    if not isinstance(ledger, DeferralLedger):
        return set()
    return {str(entry.target_id) for entry in (ledger.entries or [])}


def classification_boundary_diagnostics(
    intent: Any,
    execution_plan: ExecutionPlan | None = None,
    *,
    deferral_ledger: Any = None,
) -> list[dict[str, Any]]:
    """Return classification violations without deriving a planning class."""
    targets = _target_index(_unwrap_intent(intent))
    deferred_ids = _deferred_target_ids(deferral_ledger)
    diagnostics: list[dict[str, Any]] = []
    tasks = list(getattr(execution_plan, "worker_tasks", None) or []) if execution_plan else []
    tasks += list(getattr(execution_plan, "deferred_tasks", None) or []) if execution_plan else []
    for target_id, target in targets.items():
        assignment = next(
            (_value(task, "assignment") for task in tasks if str(_value(task, "target_id", "") or "") == target_id),
            {"expected_output_kind": _value(target, "expected_output_kind", "")},
        )
        if not _classification_required(target, assignment) or _classification_status(target) == "resolved":
            continue
        if target_id in deferred_ids:
            continue
        diagnostics.append({
            "code": "classification_decision_required",
            "target_id": target_id,
            "expected_output_kind": str(_value(target, "expected_output_kind", "") or ""),
            "classification_status": _classification_status(target),
            "message": (
                "EXECUTE requires a resolved ClassificationDecision for parcel/polygon output; "
                "the target was not dispatched and has no valid DeferralLedger entry."
            ),
        })
    for task in list(getattr(execution_plan, "worker_tasks", None) or []) if execution_plan else []:
        output_kind = str(_value(task, "expected_output_kind", "") or "")
        if output_kind not in _CLASSIFICATION_OUTPUT_KINDS:
            continue
        target_id = str(_value(task, "target_id", "") or "")
        target = targets.get(target_id)
        assignment = _value(task, "assignment")
        if target is None:
            binding = _value(assignment, "target_binding", {}) or {}
            target = binding if isinstance(binding, dict) else None
        required = target is None or _classification_required(target, assignment)
        if required and (target is None or _classification_status(target) != "resolved"):
            diagnostics.append({
                "code": "worker_task_classification_boundary_violation",
                "target_id": target_id,
                "expected_output_kind": output_kind,
                "classification_status": _classification_status(target) if target is not None else "missing",
                "message": "A parcel/polygon worker task has no resolved explicit classification; EXECUTE refuses to run the persisted plan.",
            })
    return diagnostics


def candidate_geometry_drift_diagnostics(
    execution_plan: ExecutionPlan,
    candidate_geometry_by_id: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reject current catalog facts that drift from the approval-bound task."""
    diagnostics: list[dict[str, Any]] = []
    for task in list(getattr(execution_plan, "worker_tasks", None) or []):
        candidate_id = str(getattr(task, "candidate_id", "") or "")
        if not candidate_id:
            continue
        binding = getattr(task, "target_binding", {}) or {}
        current = (candidate_geometry_by_id or {}).get(candidate_id)
        expected = {
            "wkt": str(binding.get("candidate_geometry_wkt", "") or ""),
            "role": str(binding.get("geometry_role", "") or ""),
            "kind": str(binding.get("geometry_kind", "") or ""),
            "crs": str(binding.get("crs", "") or ""),
            "source_feature_ids": sorted(str(item) for item in (binding.get("source_feature_ids") or []) if str(item)),
            "source_bsms": sorted(str(item) for item in (binding.get("source_bsms") or []) if str(item)),
            "feature_bsms": sorted(str(item) for item in (binding.get("feature_bsms") or []) if str(item)),
            "entity_refs": sorted(str(item) for item in (binding.get("entity_refs") or []) if str(item)),
            "relation_refs": sorted(str(item) for item in (binding.get("relation_refs") or []) if str(item)),
            "source_refs": sorted(str(item) for item in (binding.get("source_refs") or []) if str(item)),
            "evidence_refs": sorted(str(item) for item in (binding.get("evidence_refs") or []) if str(item)),
            "source_binding_ref": str(binding.get("source_binding_ref", "") or ""),
            "l1_snapshot_ref": str(binding.get("l1_snapshot_ref", "") or ""),
            "bundle_snapshot_digest": str(binding.get("bundle_snapshot_digest", "") or ""),
        }
        actual = {
            "wkt": str(getattr(current, "wkt", "") or "") if current is not None else "",
            "role": str(getattr(current, "role", "") or "") if current is not None else "",
            "kind": str(getattr(current, "kind", "") or "") if current is not None else "",
            "crs": str(getattr(current, "crs", "") or "") if current is not None else "",
            "source_feature_ids": sorted(str(item) for item in (getattr(current, "source_feature_ids", None) or []) if str(item)),
            "source_bsms": sorted(str(item) for item in (getattr(current, "source_bsms", None) or []) if str(item)),
            "feature_bsms": sorted(str(item) for item in (getattr(current, "feature_bsms", None) or []) if str(item)),
            "entity_refs": sorted(str(item) for item in (getattr(current, "entity_refs", None) or []) if str(item)),
            "relation_refs": sorted(str(item) for item in (getattr(current, "relation_refs", None) or []) if str(item)),
            "source_refs": sorted(str(item) for item in (getattr(current, "source_refs", None) or []) if str(item)),
            "evidence_refs": sorted(str(item) for item in (getattr(current, "evidence_refs", None) or []) if str(item)),
            "source_binding_ref": str(getattr(current, "source_binding_ref", "") or "") if current is not None else "",
            "l1_snapshot_ref": str(getattr(current, "l1_snapshot_ref", "") or "") if current is not None else "",
            "bundle_snapshot_digest": str(getattr(current, "bundle_snapshot_digest", "") or "") if current is not None else "",
        }
        if current is None or expected != actual:
            diagnostics.append({
                "code": "EXECUTE_APPROVED_CANDIDATE_GEOMETRY_MISMATCH",
                "target_id": str(getattr(task, "target_id", "") or ""),
                "candidate_id": candidate_id,
                "expected": expected,
                "actual": actual,
            })
    return diagnostics


__all__ = ["classification_boundary_diagnostics", "candidate_geometry_drift_diagnostics"]
