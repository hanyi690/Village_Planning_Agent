"""TARGET_PROJECTION stage service.

The stage projects the persisted planning program into typed spatial
references.  It does not own graph routing, rendering, or raw GIS access.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import persist_stage_artifact
from app.modules.target_projection.validation import (
    evaluate_target_projection_gate,
    validate_target_projection_boundary,
)
from app.workflow.stages.support import (
    _adopt_context,
    _load_ref_artifact,
    _require_context,
    _retry_patch,
    _run_id,
    stage_completion_patch,
)

logger = get_logger(__name__)


def _spatial_spec_village_names(spec: Any) -> List[str]:
    names: List[str] = []
    for child in getattr(spec, "children", None) or []:
        names.extend(_spatial_spec_village_names(child))
    reference = getattr(spec, "reference", None)
    reference_kind = str(getattr(reference, "kind", "") or "")
    filt = getattr(reference, "filter", None) if reference is not None else None
    label = str((filt or {}).get("label_contains") or "").strip()
    if label and reference_kind in {"place_name", "village"}:
        names.append(label)
    return list(dict.fromkeys(names))


def _spec_has_source_support(spec: Any, context: Any) -> bool:
    """Check named-place support without requiring a legacy BSM.

    A named spatial reference is admissible when either the compatibility
    gazetteer resolves it to a parcel or the generic DATA catalog contains a
    source feature whose arbitrary attributes/normalized claims carry the
    label.  The latter is important for uploaded layers that have no BSM,
    parcel schema, or configured layer name.
    """
    labels = _spatial_spec_village_names(spec)
    if not labels:
        return True
    entries = getattr(getattr(context, "gazetteer", None), "entries", []) or []
    resolved_names: set[str] = set()
    for entry in entries:
        if getattr(entry, "bsms", None):
            resolved_names.add(str(getattr(entry, "name", "")))
            resolved_names.update(str(alias) for alias in (getattr(entry, "aliases", []) or []))
    catalog_names: set[str] = set()
    catalog = getattr(context, "data_resource_catalog", None)
    snapshot = getattr(catalog, "snapshot", None)
    for feature in list(getattr(snapshot, "features", None) or []):
        values = {
            **dict(getattr(feature, "raw_attributes", None) or {}),
            **dict(getattr(feature, "normalized_claims", None) or {}),
        }
        for key, value in values.items():
            # Only name-like fields participate in place support.  Arbitrary
            # numeric/coded attributes must not accidentally satisfy a label.
            key_text = str(key).casefold()
            if not any(token in key_text for token in ("name", "label", "title", "place", "地点", "名称", "别名")):
                continue
            if isinstance(value, (list, tuple, set)):
                catalog_names.update(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                catalog_names.add(value.strip())
    all_names = resolved_names | catalog_names
    return all(
        label in all_names
        or label.removesuffix("自然村").removesuffix("村") in all_names
        for label in labels
    )


def _filter_unsupported_spatial_specs(
    specs: List[Any],
    context: Any,
) -> tuple[List[Any], List[Dict[str, Any]]]:
    diagnostics: List[Dict[str, Any]] = []
    for spec in specs:
        if _spec_has_source_support(spec, context):
            continue
        diagnostics.append({
            "code": "UNSUPPORTED_SPATIAL_REFERENCE",
            "intervention_id": getattr(spec, "intervention_id", ""),
            "target_id": getattr(spec, "intervention_id", ""),
            "labels": _spatial_spec_village_names(spec),
            "message": (
                "named place has no gazetteer or generic DATA source evidence; "
                "GROUND must resolve or route HUMAN"
            ),
        })
    unsupported_ids = {
        str(item.get("intervention_id") or "")
        for item in diagnostics
    }
    return [
        spec for spec in specs
        if str(getattr(spec, "intervention_id", "") or "") not in unsupported_ids
    ], diagnostics


async def target_projection_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Project PlanningProgram into typed spatial references for GROUND."""
    from app.workflow.stages.support import require_upstream_gates

    require_upstream_gates(
        dict(state),
        ("data", "kg", "evidence", "l1", "l2", "l3"),
    )
    from app.modules.target_projection.aggregation import project_program_async
    from app.contracts.target_projection.parse_result_contracts import (
        ParseDiagnostic,
    )
    from app.contracts.l3.l3_contracts import PlanningProgram

    retry_patch = _retry_patch(state, "target_projection")
    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    if program is None:
        raise RuntimeError(
            "TARGET_PROJECTION_INPUT_MISSING: planning_program artifact is required"
        )
    context = await _require_context(state)
    context_patch = _adopt_context(state, context)
    result, specs, gate = await project_program_async(
        program,
        run_id=_run_id(state),
        context_version=str(getattr(context, "version", "")),
    )
    original_specs = list(specs)
    specs, unsupported = _filter_unsupported_spatial_specs(specs, context)
    result.spatial_reference_specs = specs
    unsupported_ids = {
        str(item.get("intervention_id") or "")
        for item in unsupported
    }
    if unsupported_ids:
        from app.contracts.target_projection.p1_closure import build_grounding_request
        from app.contracts.target_projection.parse_result_contracts import (
            TargetProjectionBypassRecord,
        )

        parked_specs = [
            spec.model_copy(update={"unresolved_reason": "unsupported_source"})
            for spec in original_specs
            if str(getattr(spec, "intervention_id", "") or "") in unsupported_ids
        ]
        result.pending_grounding_specs = [
            *list(getattr(result, "pending_grounding_specs", None) or []),
            *parked_specs,
        ]
        result.grounding_requests = [
            item for item in (getattr(result, "grounding_requests", None) or [])
            if item.target_ref not in unsupported_ids
        ]
        result.pending_grounding_requests = [
            *list(getattr(result, "pending_grounding_requests", None) or []),
            *[
                build_grounding_request(
                    spec,
                    physical_project_ref=str(getattr(spec, "physical_project_ref", "") or ""),
                    component_claim_refs=list(getattr(spec, "component_claim_refs", None) or []),
                    component_fact_refs=list(getattr(spec, "component_fact_refs", None) or []),
                    defer_reason="unsupported_spatial_reference",
                )
                for spec in parked_specs
            ],
        ]
        bypass_records = []
        for spec in parked_specs:
            target_ref = str(getattr(spec, "intervention_id", "") or "")
            bypass_ref = (
                f"target-projection-bypass:{target_ref}:unsupported-source"
            )
            bypass_records.append(TargetProjectionBypassRecord(
                bypass_ref=bypass_ref,
                target_ref=target_ref,
                condition="named spatial reference lacks current source support",
                reason_code="UNSUPPORTED_SPATIAL_REFERENCE",
                detail=str(getattr(spec, "unresolved_reason", "") or "unsupported_source"),
                source_refs=list(dict.fromkeys([
                    *list(getattr(spec, "l1_fact_refs", None) or []),
                    *list(getattr(spec, "component_fact_refs", None) or []),
                    str(getattr(spec, "source_snapshot_ref", "") or ""),
                ])),
            ))
            result.target_projection_rows = [
                row.model_copy(update={
                    "status": "pending_grounding",
                    "bypass_ref": bypass_ref,
                }) if row.target_ref == target_ref else row
                for row in result.target_projection_rows
            ]
        result.bypass_records = [
            *list(getattr(result, "bypass_records", None) or []),
            *bypass_records,
        ]
    if unsupported:
        diagnostics = list(getattr(result, "diagnostics", []) or [])
        diagnostics.extend(ParseDiagnostic(**item) for item in unsupported)
        result.diagnostics = diagnostics
        logger.warning(
            "[workflow:target_projection] parked %d spatial refs as pending unsupported requests",
            len(unsupported),
        )
    # The compiler gate is evaluated before source-semantic and authoritative
    # bundle support diagnostics are appended. Re-evaluate at the stage
    # boundary so a late spatial identity error cannot pass into GROUND.
    validate_target_projection_boundary(result)
    gate = evaluate_target_projection_gate(
        result,
        run_id=_run_id(state),
        context_version=str(getattr(context, "version", "")),
    )
    output_refs = {}
    intent_ref = persist_stage_artifact(
        state, "target_projection", "IntentCompilationResult", result
    )
    output_refs["target_projection"] = intent_ref
    return stage_completion_patch(
        state,
        "target_projection",
        output_refs=output_refs,
        gate=gate,
        context_patch=context_patch,
        retry_patch=retry_patch,
    )


__all__ = ["target_projection_node"]
