"""Build and hydrate the context consumed by evidence retrieval."""

from __future__ import annotations

from typing import Any


async def hydrate_evidence_context(session_id: str, context: Any) -> dict[str, Any] | None:
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.workflow.layers.context_bootstrap import _hydrate_l1_spatial_facts

    state = await PlanningRuntimeService.aget_state_values_if_initialized(session_id)
    if state:
        await _hydrate_l1_spatial_facts(state, context)
    return state


async def hydrate_source_semantic_context(
    session_id: str,
    context: Any,
    state: dict[str, Any] | None = None,
) -> Any | None:
    if getattr(context, 'source_semantic_fingerprint', '') and getattr(context, 'source_semantic_decisions', {}):
        return None
    if state is None:
        from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

        state = await PlanningRuntimeService.aget_state_values_if_initialized(session_id)
    from app.contracts.evidence.source_semantic_contracts import SourceSemanticClassificationSnapshot
    from app.infrastructure.artifacts.runtime import load_artifact

    snapshot = load_artifact(state, 'source_semantic_classification', SourceSemanticClassificationSnapshot) if state else None
    if snapshot is None:
        from app.evidence.identity.source_semantic_runtime import classify_source_semantics

        runtime_snapshot, _, diagnostics = await classify_source_semantics(context)
        context.source_semantic_diagnostics = list(diagnostics)
        return runtime_snapshot
    current_digest = str(getattr(getattr(context, 'data_snapshot', None), 'digest', '') or '')
    if current_digest and snapshot.source_snapshot_digest and snapshot.source_snapshot_digest != current_digest:
        raise ValueError('source semantic snapshot digest mismatch')
    if getattr(context, 'source_semantic_fingerprint', '') == snapshot.fingerprint:
        return snapshot
    from app.evidence.identity.source_semantic_runtime import install_source_semantic_snapshot

    install_source_semantic_snapshot(context, snapshot)
    context.source_semantic_diagnostics = [{'code': 'SOURCE_SEMANTIC_ARTIFACT_REPLAYED', 'message': 'source semantic classification replayed from the matching durable snapshot'}]
    return snapshot


async def prepare_evidence_context(session_id: str, village_name: str = '', *, include_reports: bool = True, refresh: bool = False) -> Any:
    from app.infrastructure.context.planning_context_factory import build_planning_context, get_cached_context

    context = None if refresh else get_cached_context(session_id)
    if context is None:
        context = await build_planning_context(session_id, village_name=village_name, include_reports=include_reports, refresh=refresh)
    if include_reports and not getattr(context, 'reports_loaded', False) and get_cached_context(session_id) is context:
        context = await build_planning_context(session_id, village_name=village_name, include_reports=True, refresh=True)
    try:
        state = await hydrate_evidence_context(session_id, context)
        await hydrate_source_semantic_context(session_id, context, state)
    except Exception as exc:
        diagnostics = list(getattr(context, 'source_semantic_diagnostics', []) or [])
        diagnostics.append({'code': 'SOURCE_SEMANTIC_HYDRATION_FAILED', 'message': f'{type(exc).__name__}: {exc}'})
        context.source_semantic_diagnostics = diagnostics[-8:]
    return context


def build_external_evidence_policy(dimension_key: str, categories: list[str] | None = None) -> Any:
    from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy

    return ExternalSearchPolicy(allowed_dimensions=[str(dimension_key or '')])
