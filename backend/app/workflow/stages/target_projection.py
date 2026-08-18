"""TARGET_PROJECTION stage service.

The stage projects the persisted planning program into typed spatial
references.  It does not own graph routing, rendering, or raw GIS access.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import persist_stage_artifact
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
    filt = getattr(reference, "filter", None) if reference is not None else None
    label = str((filt or {}).get("label_contains") or "").strip()
    if label:
        names.append(label)
    return list(dict.fromkeys(names))


def _spec_has_source_support(spec: Any, context: Any) -> bool:
    """Require a BSM-backed gazetteer entry for named village specs."""
    labels = _spatial_spec_village_names(spec)
    if not labels:
        return True
    entries = getattr(getattr(context, "gazetteer", None), "entries", []) or []
    resolved_names: set[str] = set()
    for entry in entries:
        if getattr(entry, "bsms", None):
            resolved_names.add(str(getattr(entry, "name", "")))
            resolved_names.update(str(alias) for alias in (getattr(entry, "aliases", []) or []))
    return all(
        label in resolved_names
        or label.removesuffix("自然村").removesuffix("村") in resolved_names
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
            "labels": _spatial_spec_village_names(spec),
            "message": (
                "named village has no GIS BSM binding and no object-specific "
                "source evidence; GROUND must resolve or route HUMAN"
            ),
        })
    return list(specs), diagnostics


async def target_projection_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Project PlanningProgram into typed spatial references for GROUND."""
    from app.domain.program.target_projection.aggregate import project_program_async
    from app.contracts.workflow.parse_result_contracts import ParseDiagnostic
    from app.contracts.domain.l3_contracts import PlanningProgram
    from app.contracts.evidence.identity_contracts import (
        EvidenceObservationSnapshot,
        GroundedEntityBindingSnapshot,
    )

    retry_patch = _retry_patch(state, "target_projection")
    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    if program is None:
        logger.warning("[workflow:target_projection] no planning_program")
    context = await _require_context(state)
    observation_snapshot = _load_ref_artifact(
        state,
        "l1_observations",
        EvidenceObservationSnapshot,
    )
    binding_snapshot = _load_ref_artifact(
        state,
        "l1_bindings",
        GroundedEntityBindingSnapshot,
    )
    workspace = getattr(context, "workspace", None)
    point_layers = getattr(workspace, "points", None)
    line_layers = getattr(workspace, "lines", None)

    def _all_layer_features(group: object, preferred: tuple[str, ...]) -> list[object]:
        """Collect only explicitly authoritative source layers.

        Planned annotations/roads, hazard points, and administrative lines
        are not interchangeable with existing facilities/roads.  Including
        every group made a strict quantity binding fail (for example 13
        current shrines became 16 after planned annotations were appended),
        or allowed a planned line layer to masquerade as an existing road.
        The caller therefore supplies the small set of current source layers;
        features without provenance remain candidate evidence and cannot
        become exact.
        """
        get = getattr(group, "get", None)
        layer_names = list(preferred)
        result: list[object] = []
        seen: set[str] = set()
        for name in layer_names:
            values = get(name) if callable(get) else []
            for feature in values or []:
                raw = getattr(feature, "_raw", {}) or {}
                source_id = str(raw.get("source_feature_id") or "").strip()
                identity = source_id or f"object:{id(feature)}"
                if identity in seen:
                    continue
                seen.add(identity)
                result.append(feature)
        return result

    source_features = {
        "facility": _all_layer_features(point_layers, ("annotations_current", "facilities_current")),
        "road": _all_layer_features(line_layers, ("roads_current",)),
    }
    result, specs, gate = await project_program_async(
        program,
        run_id=_run_id(state),
        context_version=str(getattr(context, "version", "")),
        observations=(
            list(observation_snapshot.observations)
            if observation_snapshot is not None
            else []
        ),
        bindings=(
            list(binding_snapshot.bindings)
            if binding_snapshot is not None
            else []
        ),
        source_features=source_features,
    )
    # Design 03: IntentGraph is written by the IntentCompiler (this stage),
    # not deferred to EXECUTE, so GROUND/EXECUTE route_prepare can read the
    # L3 intent entities on the first pass (kg_l3_intent_mismatch guard).
    intent = getattr(result, "typed_intent", None)
    kg = getattr(context, "kg", None)
    if intent is not None and kg is not None:
        try:
            from app.infrastructure.kg.builder.layer3 import build_intent_layer
            build_intent_layer(kg, intent)
        except Exception as exc:
            logger.warning("[workflow:target_projection] build_intent_layer failed: %s", exc)
    specs, unsupported = _filter_unsupported_spatial_specs(specs, context)
    result.spatial_reference_specs = specs
    if unsupported:
        diagnostics = list(getattr(result, "diagnostics", []) or [])
        diagnostics.extend(ParseDiagnostic(**item) for item in unsupported)
        result.diagnostics = diagnostics
        logger.warning(
            "[workflow:target_projection] retained %d spatial refs with unsupported-source diagnostics",
            len(unsupported),
        )
    intent_ref = persist_stage_artifact(
        state, "target_projection", "IntentCompilationResult", result
    )
    return stage_completion_patch(
        state,
        "target_projection",
        output_refs={"target_projection": intent_ref},
        gate=gate,
        context_patch=_adopt_context(state, context),
        retry_patch=retry_patch,
    )


__all__ = ["target_projection_node"]
