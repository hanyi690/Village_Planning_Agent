"""TARGET_PROJECTION stage service.

The stage projects the persisted planning program into typed spatial
references.  It does not own graph routing, rendering, or raw GIS access.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.evidence.identity.source_semantic_runtime import (
    classify_source_semantics,
    collect_authoritative_source_features,
    install_source_semantic_snapshot,
    source_descriptors,
)
from app.infrastructure.logging import get_logger
from app.workflow.stage_adapter import persist_stage_artifact
from app.domain.program.target_projection.gate import evaluate_target_projection_gate
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


async def _classify_source_semantics(
    state: Dict[str, Any],
    context: Any,
    source_features: dict[str, list[object]],
) -> tuple[Any | None, dict[str, object], list[Dict[str, Any]]]:
    """Run or replay the shared explicit source-semantic overlay."""
    from app.contracts.evidence.source_semantic_contracts import (
        SourceSemanticClassificationSnapshot,
    )

    items, missing_identity = source_descriptors(source_features)
    diagnostics: list[Dict[str, Any]] = []
    if missing_identity:
        diagnostics.append({
            "code": "SOURCE_FEATURE_ID_REQUIRED",
            "message": (
                f"{missing_identity} source feature(s) have no durable source_feature_id; "
                "semantic binding remains unresolved"
            ),
        })
    if not items:
        return None, {}, diagnostics

    cached = _load_ref_artifact(
        state,
        "source_semantic_classification",
        SourceSemanticClassificationSnapshot,
    )
    current_snapshot_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    )
    if (
        cached is not None
        and current_snapshot_digest
        and cached.source_snapshot_digest
        and cached.source_snapshot_digest != current_snapshot_digest
    ):
        diagnostics.append({
            "code": "SOURCE_SEMANTIC_SNAPSHOT_MISMATCH",
            "message": (
                "persisted source semantic classification belongs to a different "
                "bundle snapshot and was not reused"
            ),
        })
        cached = None
    if cached is not None:
        try:
            install_source_semantic_snapshot(context, cached)
        except Exception as exc:
            diagnostics.append({
                "code": "SOURCE_SEMANTIC_GRAPH_REBUILD_FAILED",
                "message": f"accepted overlay was not installed into EvidenceGraph: {exc}",
            })
        snapshot = cached
        from app.evidence.identity.flash_source_semantic_classifier import (
            accepted_semantic_decisions,
        )

        accepted = accepted_semantic_decisions(snapshot)
    else:
        config = state.get("config") or {}
        enabled = state.get(
            "source_semantic_llm_enabled",
            config.get("source_semantic_llm_enabled"),
        )
        snapshot, accepted, runtime_diagnostics = await classify_source_semantics(
            context,
            enabled=enabled,
            source_features=source_features,
            classifier=state.get("source_semantic_classifier"),
        )
        diagnostics.extend(runtime_diagnostics)
        return snapshot, accepted, diagnostics
    nonaccepted = [
        decision.source_feature_id
        for decision in snapshot.decisions
        if decision.status != "accepted"
    ]
    if nonaccepted:
        diagnostics.append({
            "code": "SOURCE_SEMANTIC_DECISION_NOT_ACCEPTED",
            "message": (
                f"{len(nonaccepted)} source feature(s) remain "
                "ambiguous/unresolved and cannot be used for exact binding"
            ),
        })
    context.source_semantic_diagnostics = list(diagnostics)
    return snapshot, accepted, diagnostics


async def target_projection_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Project PlanningProgram into typed spatial references for GROUND."""
    from app.domain.program.target_projection.aggregate import project_program_async
    from app.contracts.workflow.parse_result_contracts import (
        CompilationStatus,
        ParseDiagnostic,
    )
    from app.contracts.domain.l3_contracts import PlanningProgram
    from app.contracts.evidence.identity_contracts import (
        EvidenceObservationSnapshot,
        GroundedEntityBindingSnapshot,
    )

    retry_patch = _retry_patch(state, "target_projection")
    program = _load_ref_artifact(state, "planning_program", PlanningProgram)
    if program is None:
        raise RuntimeError(
            "TARGET_PROJECTION_INPUT_MISSING: planning_program artifact is required"
        )
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
    source_features = collect_authoritative_source_features(context)
    semantic_snapshot, semantic_decisions, semantic_diagnostics = await _classify_source_semantics(
        state,
        context,
        source_features,
    )
    # Stabilize context provenance only after source-semantic replay/classification
    # has installed its snapshot-local decisions.  The same final context must
    # be fingerprinted on the first run and on resume; adopting it before this
    # step would make the first descriptor differ from every replay descriptor.
    context_patch = _adopt_context(state, context)
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
        source_semantic_decisions=semantic_decisions,
    )
    if semantic_diagnostics:
        result.diagnostics = [
            *list(getattr(result, "diagnostics", []) or []),
            *(ParseDiagnostic(**item) for item in semantic_diagnostics),
        ]
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
        result.compilation_status = CompilationStatus.NEEDS_REVIEW
        logger.warning(
            "[workflow:target_projection] retained %d spatial refs with unsupported-source diagnostics",
            len(unsupported),
        )
    # The compiler gate is evaluated before source-semantic and authoritative
    # bundle support diagnostics are appended. Re-evaluate at the stage
    # boundary so a late spatial identity error cannot pass into GROUND.
    gate = evaluate_target_projection_gate(
        result,
        run_id=_run_id(state),
        context_version=str(getattr(context, "version", "")),
    )
    # Persist the semantic snapshot before TARGET_PROJECTION so its digest is
    # part of the projection's parent lineage on the first run as well as on
    # resume.  Writing the projection first made the payload look identical
    # while its parent set changed on the second pass, producing a new digest
    # and violating zero-increment replay.
    output_refs = {}
    if semantic_snapshot is not None:
        semantic_ref = persist_stage_artifact(
            state,
            "target_projection",
            "SourceSemanticClassificationSnapshot",
            semantic_snapshot,
        )
        state.setdefault("artifact_refs", {})[
            "source_semantic_classification"
        ] = semantic_ref
        output_refs["source_semantic_classification"] = semantic_ref
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
