"""DELIVER gate - 3-way router over a DeliveryManifest.

Mirrors the RECONCILE/VALIDATE gate convention (app.agent.reconcile.gate)
with stage="deliver". Pure function: DeliveryManifest -> GateDecision.
No I/O, no LLM, no KG - deterministic only.

Routes (precedence high -> low):
  PASS            -> statutory_complete is True
  RETRY_VALIDATE  -> dominant blocking item is classification_missing
                     (item_id "hi-class-*") — fixable by re-validation
  HUMAN           -> export failure (hi-layers-*), upstream unresolved
                     (hi-upstream-*), tie between blocking categories, or
                     delivery_gate failed with no blocking item

Determinism: routing is a pure function of the manifest fields.
Only the gate function is delivered here; main graph wiring lands in Wave M.
"""
from __future__ import annotations

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
    """Return the deterministic route: "PASS"|"RETRY_VALIDATE"|"HUMAN"."""
    if manifest.statutory_complete:
        return "PASS"

    categories = _blocking_categories(manifest)

    if len(categories) == 1 and categories == {"classification"}:
        return "RETRY_VALIDATE"

    return "HUMAN"


def evaluate_deliver_gate(manifest: DeliveryManifest) -> GateDecision:
    stage = STAGE
    gate_artifact_id = "gate-deliver-" + (manifest.artifact_id or "0")

    route = deliver_gate_route(manifest)

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
        )

    return GateDecision(
        stage=stage,
        passed=True,
        feedback_route=None,
        pending_requests=[],
        context_version=manifest.context_version,
        artifact_id=gate_artifact_id,
    )


__all__ = ["evaluate_deliver_gate", "deliver_gate_route"]
