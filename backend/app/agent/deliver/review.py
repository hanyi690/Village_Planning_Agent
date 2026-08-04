"""DELIVER review package builder - plain serializable dict.

Pure function: DeliveryManifest + GateDecision -> dict. No I/O.
Mirrors the reconcile/validate review convention (Chinese section headers,
pydantic models dumped to JSON-safe values). Deterministic only.
"""
from __future__ import annotations

from typing import Any

from app.modules.schema.contracts.delivery_manifest_contracts import (
    DeliveryManifest,
)
from app.modules.schema.contracts.workflow_contracts import GateDecision

_ROUTE_RATIONALE = {
    "PASS": "statutory output complete; no blocking issues",
    "RETRY_VALIDATE": "dominant blocking issue is classification_missing; re-validation can fix",
    "HUMAN": "export failure, upstream unresolved, tie, or gate failure; human review required",
}


def _build_deliverables(manifest: DeliveryManifest) -> list[dict[str, Any]]:
    return [d.model_dump() for d in manifest.deliverables]


def _build_traceability(manifest: DeliveryManifest) -> list[dict[str, Any]]:
    return [t.model_dump() for t in manifest.traceability]


def _build_exit_gate(manifest: DeliveryManifest) -> dict[str, Any]:
    gate = manifest.delivery_gate
    if gate is None:
        return {"passed": None, "note": "delivery gate not computed"}
    return {
        "land_balance_closed": gate.land_balance_closed,
        "three_line_violations": gate.three_line_violations,
        "protected_intrusions": gate.protected_intrusions,
        "changed_parcels_pct": gate.changed_parcels_pct,
        "zones_complete": gate.zones_complete,
        "passed": gate.passed,
        "failures": gate.failures,
    }


def _build_human_items(manifest: DeliveryManifest) -> list[dict[str, Any]]:
    return [item.model_dump() for item in manifest.pending_human_items]


def _build_classification(manifest: DeliveryManifest) -> dict[str, Any]:
    classification_items = [
        item for item in manifest.pending_human_items if (item.item_id or "").startswith("hi-class-")
    ]
    return {
        "blocking": bool(classification_items),
        "items": [item.model_dump() for item in classification_items],
    }


def _build_statutory_completeness(manifest: DeliveryManifest) -> dict[str, Any]:
    return {
        "statutory_complete": manifest.statutory_complete,
        "breakdown": dict(manifest.statutory_complete_breakdown or {}),
    }


def _build_gate_decision(gate: GateDecision) -> dict[str, Any]:
    route = gate.feedback_route or "PASS"
    return {
        "route": route,
        "passed": gate.passed,
        "pending_requests": [pr.model_dump() for pr in gate.pending_requests],
        "rationale": _ROUTE_RATIONALE.get(route, "route undetermined"),
    }


def _build_provenance(manifest: DeliveryManifest) -> dict[str, Any]:
    if manifest.provenance is None:
        return {}
    return manifest.provenance.model_dump(mode="json")


def build_deliver_review_package(
    manifest: DeliveryManifest, gate: GateDecision
) -> dict[str, Any]:
    """Construct the DELIVER review package content dict (pure, no I/O)."""
    return {
        "交付清单": _build_deliverables(manifest),
        "溯源谱系": _build_traceability(manifest),
        "出口门槛": _build_exit_gate(manifest),
        "未决人工项": _build_human_items(manifest),
        "规划分类缺失": _build_classification(manifest),
        "法定成果完整性": _build_statutory_completeness(manifest),
        "Gate 决定": _build_gate_decision(gate),
        "来源追溯": _build_provenance(manifest),
    }


__all__ = ["build_deliver_review_package"]
