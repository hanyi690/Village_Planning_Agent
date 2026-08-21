"""Application query helpers for the public evidence boundary."""

from __future__ import annotations

from typing import Any, Dict, Optional


_active_external_provider: Any | None = None


async def hydrate_evidence_context(
    session_id: str,
    context: Any,
) -> Optional[Dict[str, Any]]:
    """Replay durable L1 spatial evidence into a query context when present.

    Runtime/checkpoint and workflow hydration details stay below the HTTP
    transport layer.  A session without a completed L1 artifact is still a
    valid partial evidence query, so callers receive ``None`` in that case.
    """
    from app.infrastructure.runtime.planning_runtime_service import (
        PlanningRuntimeService,
    )
    from app.workflow.layers.context_bootstrap import _hydrate_l1_spatial_facts

    state = await PlanningRuntimeService.aget_state_values_if_initialized(session_id)
    if state:
        await _hydrate_l1_spatial_facts(state, context)
    return state


async def hydrate_source_semantic_context(
    session_id: str,
    context: Any,
    state: Optional[Dict[str, Any]] = None,
) -> Any | None:
    """Replay or explicitly classify the source-semantic overlay.

    A matching durable artifact is replayed first.  When none exists, the
    shared runtime may call MiniMax only when ``SOURCE_SEMANTIC_LLM_ENABLED``
    is enabled; the default query path remains offline and reports its
    unresolved state in ``context.source_semantic_diagnostics``.
    """
    if (
        str(getattr(context, "source_semantic_fingerprint", "") or "")
        and bool(getattr(context, "source_semantic_decisions", {}) or {})
    ):
        return None
    if state is None:
        from app.infrastructure.runtime.planning_runtime_service import (
            PlanningRuntimeService,
        )

        state = await PlanningRuntimeService.aget_state_values_if_initialized(
            session_id
        )
    from app.contracts.evidence.source_semantic_contracts import (
        SourceSemanticClassificationSnapshot,
    )
    from app.infrastructure.artifacts.runtime import load_artifact

    snapshot = (
        load_artifact(
            state,
            "source_semantic_classification",
            SourceSemanticClassificationSnapshot,
        )
        if state
        else None
    )
    if snapshot is None:
        from app.evidence.identity.source_semantic_runtime import (
            classify_source_semantics,
        )

        runtime_snapshot, _accepted, diagnostics = await classify_source_semantics(context)
        context.source_semantic_diagnostics = list(diagnostics)
        return runtime_snapshot
    current_digest = str(
        getattr(getattr(context, "data_snapshot", None), "digest", "") or ""
    )
    if (
        current_digest
        and snapshot.source_snapshot_digest
        and snapshot.source_snapshot_digest != current_digest
    ):
        raise ValueError(
            "source semantic snapshot digest mismatch: "
            f"artifact={snapshot.source_snapshot_digest} current={current_digest}"
        )
    existing_fingerprint = str(
        getattr(context, "source_semantic_fingerprint", "") or ""
    )
    if existing_fingerprint == snapshot.fingerprint:
        return snapshot
    from app.evidence.identity.source_semantic_runtime import (
        install_source_semantic_snapshot,
    )

    install_source_semantic_snapshot(context, snapshot)
    context.source_semantic_diagnostics = [
        {
            "code": "SOURCE_SEMANTIC_ARTIFACT_REPLAYED",
            "message": "source semantic classification replayed from the matching durable snapshot",
        },
    ]
    return snapshot


async def prepare_evidence_context(
    session_id: str,
    village_name: str = "",
    *,
    include_reports: bool = True,
    refresh: bool = False,
) -> Any:
    """Prepare the one context used by HTTP, LLM tools, and retrieval.

    Context construction, durable L1 replay, report loading, and source
    semantic hydration must happen at the boundary before a query is routed.
    Keeping this preparation in one helper prevents the LLM tool path from
    silently seeing a cold context while the HTTP path sees L1 and reports.
    Hydration failures remain queryable but are recorded as typed diagnostics.
    """
    from app.infrastructure.context.planning_context_factory import (
        build_planning_context,
        get_cached_context,
    )

    context = None
    if not refresh:
        context = get_cached_context(session_id)
    if context is None:
        context = await build_planning_context(
            session_id,
            village_name=village_name,
            include_reports=include_reports,
            refresh=refresh,
        )
    # An empty report manifest is a valid loaded state for a session that has
    # not produced L1/L2/L3 reports yet.  Rebuilding solely because
    # ``context.reports`` is empty caused every evidence query to rebuild the
    # Bundle/KG/Gazetteer stack.  Refresh only when the cached context was
    # explicitly built without report hydration.
    if include_reports and not bool(getattr(context, "reports_loaded", False)):
        cached = get_cached_context(session_id)
        if cached is context:
            context = await build_planning_context(
                session_id,
                village_name=village_name,
                include_reports=True,
                refresh=True,
            )

    try:
        hydrated_state = await hydrate_evidence_context(session_id, context)
        await hydrate_source_semantic_context(
            session_id,
            context,
            hydrated_state,
        )
    except Exception as exc:  # noqa: BLE001 - partial evidence remains explicit
        diagnostics = list(
            getattr(context, "source_semantic_diagnostics", []) or []
        )
        diagnostics.append({
            "code": "SOURCE_SEMANTIC_HYDRATION_FAILED",
            "message": f"source semantic hydration failed: {type(exc).__name__}: {exc}",
        })
        context.source_semantic_diagnostics = diagnostics[-8:]
    return context


def get_configured_external_provider(categories: list[str] | None = None) -> Any | None:
    """Return the explicitly configured provider, never an implicit network client.

    ``fake`` is the deterministic offline provider used by local demos and
    simulated-LLM tests.  ``exa`` is opt-in and requires ``EXA_API_KEY``;
    otherwise the typed unavailable adapter is returned.  The caller owns the
    returned provider and must close it during application shutdown.
    """
    import os

    mode = str(os.getenv("EVIDENCE_EXTERNAL_PROVIDER", "disabled") or "").strip().lower()
    if mode == "fake":
        from app.infrastructure.search import FakeExternalSearchAdapter

        return FakeExternalSearchAdapter(
            enabled_domains=["statistics", "economics", "planning"],
            enabled_categories=[
                str(item).strip()
                for item in (categories or ["population", "industry", "transport", "water"])[:8]
                if str(item).strip()
            ],
        )
    if mode == "exa":
        api_key = str(os.getenv("EXA_API_KEY", "") or "").strip()
        if api_key:
            from app.infrastructure.search import ExaHTTPExternalSearchAdapter

            try:
                timeout_s = float(os.getenv("EXA_TIMEOUT_S", "8"))
            except (TypeError, ValueError):
                timeout_s = 8.0
            return ExaHTTPExternalSearchAdapter(
                api_key,
                endpoint=os.getenv("EXA_ENDPOINT", "https://api.exa.ai/search"),
                timeout_s=timeout_s,
            )
    from app.infrastructure.search import UnavailableExternalSearchAdapter

    return UnavailableExternalSearchAdapter()


def configure_external_provider(app: Any) -> Any:
    """Attach one provider to the FastAPI app lifecycle and return it."""
    global _active_external_provider
    provider = get_configured_external_provider()
    app.state.evidence_external_provider = provider
    _active_external_provider = provider
    return provider


async def close_external_provider(app: Any) -> None:
    """Close an app-scoped provider without assuming it owns resources."""
    global _active_external_provider
    provider = getattr(getattr(app, "state", None), "evidence_external_provider", None)
    close = getattr(provider, "close", None)
    if close is None:
        _active_external_provider = None
        return
    try:
        result = close()
        if hasattr(result, "__await__"):
            await result
    finally:
        _active_external_provider = None


def get_active_external_provider() -> Any | None:
    """Return the lifecycle-owned provider for workflow/application reuse."""
    return _active_external_provider


def build_external_evidence_policy(
    dimension_key: str,
    categories: list[str] | None = None,
) -> Any:
    """Build the narrow policy for one explicit external evidence request."""
    from app.evidence.retrieval.external_search_policy import ExternalSearchPolicy

    return ExternalSearchPolicy(
        allowed_dimensions=[str(dimension_key or "")],
    )


__all__ = [
    "build_external_evidence_policy",
    "close_external_provider",
    "configure_external_provider",
    "get_active_external_provider",
    "get_configured_external_provider",
    "hydrate_evidence_context",
    "hydrate_source_semantic_context",
    "prepare_evidence_context",
]
