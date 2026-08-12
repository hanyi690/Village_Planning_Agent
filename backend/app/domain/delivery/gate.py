"""DELIVER terminal router over a DeliveryManifest.

Mirrors the RECONCILE/VALIDATE gate convention (app.domain.validation.reconcile_gate)
with stage="deliver". Pure function: DeliveryManifest -> GateDecision.
No I/O, no LLM, no KG - deterministic only.

Routes:
  PASS            -> complete or controlled partial terminal delivery
  END_DIAGNOSTIC  -> remaining non-deferred blocker

Determinism: routing is a pure function of the manifest fields.
Only the gate function is delivered here; main graph wiring lands in Wave M.
"""
from __future__ import annotations

from typing import Any

from app.domain.common.gate_progress import gate_progress_metadata
from app.modules.schema.contracts.delivery_manifest_contracts import (
    DeliveryManifest,
)
from app.modules.schema.contracts.workflow_contracts import (
    GateDecision,
    PendingRequest,
    StageId,
)

STAGE = StageId.DELIVER.value


def _blocking_categories(manifest: DeliveryManifest) -> set[str]:
    """Categorize blocking human items by their item_id prefix."""
    categories: set[str] = set()
    for item in manifest.pending_human_items or []:
        if not item.blocking:
            continue
        item_id = item.item_id or ""
        if item_id.startswith("hi-class-"):
            categories.add("classification")
        elif item_id.startswith("hi-layers-"):
            categories.add("layers")
        elif item_id.startswith("hi-upstream-"):
            categories.add("upstream")
        else:
            categories.add("other")
    return categories


def deliver_gate_route(manifest: DeliveryManifest) -> str:
    """Return PASS for successful terminals, otherwise END_DIAGNOSTIC."""
    if manifest.delivery_status in {"complete", "partial"}:
        return "PASS"
    return "END_DIAGNOSTIC"


def evaluate_deliver_gate(
    manifest: DeliveryManifest,
    *,
    input_artifact_refs: dict[str, Any] | None = None,
    previous_gate: Any = None,
) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-deliver-" + (manifest.artifact_id or "0")

    route = deliver_gate_route(manifest)
    issue_payload = [
        item.model_dump(mode="json")
        for item in manifest.pending_human_items
        if item.blocking
    ]
    progress, _ = gate_progress_metadata(
        input_artifact_refs=input_artifact_refs,
        output={
            "delivery_status": manifest.delivery_status,
            "statutory_complete": manifest.statutory_complete,
            "traceability": [item.model_dump(mode="json") for item in manifest.traceability],
        },
        issues=issue_payload,
        previous_gate=previous_gate,
    )
    route_reason = (
        f"terminal_delivery:{manifest.delivery_status}"
        if route == "PASS"
        else "remaining_non_deferred_delivery_blockers"
    )

    if route != "PASS":
        categories = sorted(_blocking_categories(manifest))
        pending = [
            PendingRequest(
                request_id="pr-deliver-" + route.lower() + "-0",
                stage=stage,
                request_type="deliver_" + route.lower(),
                context={
                    "reason": route,
                    "blocking_categories": categories,
                    "delivery_status": manifest.delivery_status,
                    "blocking_item_ids": manifest.diagnostic_summary.get(
                        "blocking_item_ids", []
                    ),
                },
            )
        ]
        return GateDecision(
            stage=stage,
            passed=False,
            feedback_route=route,
            pending_requests=pending,
            context_version=manifest.context_version,
            artifact_id=gate_artifact_id,
            route_reason=route_reason,
            **progress,
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        pending_requests=[],
        context_version=manifest.context_version,
        artifact_id=gate_artifact_id,
        route_reason=route_reason,
        **progress,
    )


__all__ = ["evaluate_deliver_gate", "deliver_gate_route"]
