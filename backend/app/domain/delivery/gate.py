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

from typing import Any, Iterable

from app.domain.common.gate_progress import gate_progress_metadata
from app.contracts.artifacts.delivery_manifest_contracts import (
    DeliveryManifest,
)
from app.contracts.workflow.workflow_contracts import (
    GateDecision,
    PendingRequest,
    StageId,
)

STAGE = StageId.DELIVER.value

# These layers describe the baseline/control map and cannot, by themselves,
# prove that the planning workflow materialized a planning result.  The
# complete planned land-use layer is handled specially: unchanged features
# are baseline copies, while features carrying a material change are counted
# as planning output.
_BASELINE_LAYER_TYPES = {
    "current_landuse",
    "current_road",
    "boundary",
    "input_constraint",
}
_COMPLETE_PLANNED_LAYER = "complete_planned_landuse"
_UNCHANGED_STATUSES = {None, "", "preserved", "unchanged"}


def _layer_type(layer: Any) -> str:
    if not isinstance(layer, dict):
        return ""
    return str(layer.get("layerType") or layer.get("layer_type") or "")


def _layer_features(layer: Any) -> list[dict[str, Any]]:
    if not isinstance(layer, dict):
        return []
    data = layer.get("data") or layer.get("geojson") or {}
    if not isinstance(data, dict):
        return []
    features = data.get("features")
    return [feature for feature in features if isinstance(feature, dict)] if isinstance(features, list) else []


def summarize_planning_output(
    render_layers: Iterable[Any] | None,
    snapshot: Any = None,
) -> dict[str, Any]:
    """Summarize non-baseline output at the DELIVER boundary.

    Current land-use and controls can make a map non-empty even when SELECT
    and EXECUTE produced no planning feature.  This summary is intentionally
    derived from the exact render input and the snapshot change summary so it
    can be reused by the gate, projections, and real-run audit without
    opening static ``data/gis/.../planned`` files.
    """
    layers = list(render_layers or [])
    planning_overlay_feature_count = 0
    changed_planned_feature_count = 0
    layer_feature_counts: dict[str, int] = {}
    for layer in layers:
        layer_name = _layer_type(layer)
        features = _layer_features(layer)
        layer_feature_counts[layer_name] = layer_feature_counts.get(layer_name, 0) + len(features)
        if not layer_name or layer_name in _BASELINE_LAYER_TYPES:
            continue
        if layer_name == _COMPLETE_PLANNED_LAYER:
            changed_planned_feature_count += sum(
                (feature.get("properties") or {}).get("change_status") not in _UNCHANGED_STATUSES
                for feature in features
            )
            continue
        planning_overlay_feature_count += len(features)

    change_summary = getattr(snapshot, "change_summary", None)
    if not isinstance(change_summary, dict) and isinstance(snapshot, dict):
        change_summary = snapshot.get("change_summary")
    change_summary = dict(change_summary or {})
    actual_change_count = sum(
        int(change_summary.get(key) or 0)
        for key in ("modified", "split", "merged", "created", "removed")
    )
    non_baseline_feature_count = planning_overlay_feature_count + changed_planned_feature_count
    planned_is_current_copy = actual_change_count == 0 and changed_planned_feature_count == 0
    has_planning_output = non_baseline_feature_count > 0
    return {
        "status": "ready" if has_planning_output else "no_planning_output",
        "planning_overlay_feature_count": planning_overlay_feature_count,
        "changed_planned_feature_count": changed_planned_feature_count,
        "non_baseline_feature_count": non_baseline_feature_count,
        "actual_change_count": actual_change_count,
        "planned_is_current_copy": planned_is_current_copy,
        "layer_feature_counts": layer_feature_counts,
    }


def _no_planning_output(manifest: DeliveryManifest) -> bool:
    summary = manifest.diagnostic_summary or {}
    planning = summary.get("planning_output")
    if not isinstance(planning, dict):
        return False
    return str(planning.get("status") or "") == "no_planning_output"


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
    if _no_planning_output(manifest):
        return "END_DIAGNOSTIC"
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
        "no_planning_output"
        if _no_planning_output(manifest)
        else f"terminal_delivery:{manifest.delivery_status}"
        if route == "PASS"
        else "remaining_non_deferred_delivery_blockers"
    )

    if route != "PASS":
        categories = sorted(_blocking_categories(manifest))
        pending = [
            PendingRequest(
                request_id="pr-deliver-" + route.lower() + "-0",
                stage=stage,
                request_type=(
                    "deliver_no_planning_output"
                    if _no_planning_output(manifest)
                    else "deliver_" + route.lower()
                ),
                context={
                    "reason": (
                        "no_planning_output"
                        if _no_planning_output(manifest)
                        else route
                    ),
                    "blocking_categories": categories,
                    "delivery_status": manifest.delivery_status,
                    "blocking_item_ids": manifest.diagnostic_summary.get(
                        "blocking_item_ids", []
                    ),
                    "planning_output": manifest.diagnostic_summary.get(
                        "planning_output", {}
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


__all__ = [
    "deliver_gate_route",
    "evaluate_deliver_gate",
    "summarize_planning_output",
]
