"""PARSE review package builder - source-field mapping, diagnostics, patches, specs, gate, trace.

Pure function: constructs the in-memory dict consumed by ``write_review_package``.
No I/O. Mirrors ``app.agent.l3_plan.review`` (module="parse", artifact_type
"IntentCompilationResult"). Wave F deliverable.
"""
from __future__ import annotations

from typing import Any

from app.modules.parsing.spatial_language import direction_from_location
from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.parse_result_contracts import IntentCompilationResult
from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec
from app.modules.schema.contracts.workflow_contracts import GateDecision

_DIRECTION_TO_8WIND = {
    "north": "N",
    "south": "S",
    "east": "E",
    "west": "W",
    "northeast": "NE",
    "southeast": "SE",
    "northwest": "NW",
    "southwest": "SW",
}


def _iter_targets(result: IntentCompilationResult) -> list[dict[str, Any]]:
    intent = result.typed_intent
    if intent is None:
        return []
    targets: list[dict[str, Any]] = []
    for item in intent.project_targets:
        targets.append(
            {"target_type": "project", "name": item.name, "target_id": item.target_id}
        )
    for item in intent.facilities:
        targets.append(
            {
                "target_type": "facility",
                "name": item.type,
                "target_id": item.target_id,
            }
        )
    for item in intent.road_targets:
        targets.append(
            {
                "target_type": "road",
                "name": item.road_level,
                "target_id": item.target_id,
            }
        )
    for item in intent.zone_targets:
        targets.append(
            {
                "target_type": "zone",
                "name": item.land_use or "",
                "target_id": item.target_id,
            }
        )
    return targets


def _spec_directions(spec: SpatialReferenceSpec) -> list[str]:
    directions = [spec.direction] if spec.direction else []
    for child in spec.children:
        directions.extend(_spec_directions(child))
    return directions


def _spec_mentions(spec: SpatialReferenceSpec, tokens: list[str]) -> bool:
    blob = spec.model_dump_json()
    for token in tokens:
        if token and token in blob:
            return True
    directions = _spec_directions(spec)
    if not directions:
        return False
    for token in tokens:
        mapped = _DIRECTION_TO_8WIND.get(direction_from_location(token))
        if mapped in directions:
            return True
    return False


def _spec_ref_for_target(
    entry: dict[str, Any],
    target_meta: dict[str, str],
    specs: list[SpatialReferenceSpec],
) -> str:
    tokens = [entry["target_id"], entry["name"], target_meta.get("location_hint", "")]
    for spec in specs:
        if _spec_mentions(spec, tokens):
            return spec.type
    return "unmapped"


def _collect_target_meta(result: IntentCompilationResult) -> dict[str, dict[str, str]]:
    """Map intervention id -> location hints for spec_ref matching."""
    intent = result.typed_intent
    if intent is None:
        return {}
    meta: dict[str, dict[str, str]] = {}
    for item in intent.project_targets:
        hint = item.semantic.spatial_hint or item.location_hint if item.semantic else item.location_hint
        meta[item.target_id] = {"location_hint": hint}
    for item in intent.facilities:
        hint = item.semantic.spatial_hint if item.semantic else ""
        meta[item.target_id] = {"location_hint": hint or item.location_hint}
    for item in intent.road_targets:
        hint = item.semantic.spatial_hint if item.semantic else ""
        meta[item.target_id] = {"location_hint": hint}
    for item in intent.zone_targets:
        hint = item.semantic.spatial_hint if item.semantic else ""
        meta[item.target_id] = {"location_hint": hint}
    return meta


def build_parse_review_package(
    *,
    result: IntentCompilationResult,
    specs: list[SpatialReferenceSpec],
    gate_decision: GateDecision,
    artifact_ref: ArtifactRef,
    run_id: str = "",
) -> dict[str, Any]:
    """Construct the PARSE review package content dict (pure, no I/O)."""
    trace = result.trace
    mode = trace.mode.value if trace else "compile"

    intervention_count = 0
    if result.typed_intent is not None:
        intervention_count = (
            len(result.typed_intent.project_targets)
            + len(result.typed_intent.facilities)
            + len(result.typed_intent.road_targets)
            + len(result.typed_intent.zone_targets)
        )

    target_meta = _collect_target_meta(result)
    source_field_mapping = [
        {
            "target_type": entry["target_type"],
            "name": entry["name"],
            "target_id": entry["target_id"],
            "spec_ref": _spec_ref_for_target(
                entry, target_meta.get(entry["target_id"], {}), specs
            ),
        }
        for entry in _iter_targets(result)
    ]

    diagnostics = [
        {
            "severity": d.severity,
            "code": d.code,
            "message": d.message,
            "field_path": d.field_path,
        }
        for d in result.diagnostics
    ]

    patches = [
        {
            "field_path": p.field_path,
            "operation": p.operation.value,
            "actor": p.actor,
            "rationale": p.rationale,
        }
        for p in result.patches
    ]

    spec_list = [
        {
            "type": spec.type,
            "reference_kind": spec.reference.kind if spec.reference else None,
            "direction": spec.direction or None,
            "attr_filter": spec.attr_filter or None,
            "topo": spec.topo or None,
        }
        for spec in specs
    ]

    return {
        "metadata": {
            "module": "parse",
            "artifact_id": artifact_ref.artifact_id,
            "artifact_type": "IntentCompilationResult",
            "run_id": run_id,
            "revision": artifact_ref.revision,
            "compilation_status": result.compilation_status.value,
        },
        "编译摘要": {
            "mode": mode,
            "intervention_count": intervention_count,
            "spec_count": len(specs),
            "patch_count": len(result.patches),
            "confidence": result.confidence,
        },
        "源字段->结构化字段映射": source_field_mapping,
        "编译诊断": diagnostics,
        "补丁清单": patches,
        "SpatialReferenceSpec 清单": spec_list,
        "Gate 决定": {
            "passed": gate_decision.passed,
            "feedback_route": gate_decision.feedback_route,
            "pending_requests": [
                r.model_dump() for r in gate_decision.pending_requests
            ],
        },
        "profile trace": {
            "mode": mode,
            "steps": trace.steps if trace else [],
        },
    }


__all__ = ["build_parse_review_package"]
