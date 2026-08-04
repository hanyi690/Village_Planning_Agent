"""Session planning context factory - single async build path.

Owns the lifecycle of the authoritative ``PlanningContext`` for a session:

    bundle + session KG + gazetteer + constraint index + village anchors + reports

built *once* and reused across the EXPLORE / PARSE / GROUND / LAYOUT pipeline,
eliminating the repeated Bundle/KG/report rebuilds in ``gis_agent_node``,
``ensure_session_kg`` and ``layout_pipeline._fetch/_build_kg``.

Versioning: every rebuild bumps ``PlanningContext.version``. The bundle is
cached in ``app.services.session_bundle``; the session KG is idempotent in
``KGManager``. ``build_planning_context`` reuses both and only assembles the
derived parts (gazetteer / constraint index / anchors / kg_query_fn).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.modules.context.planning_context import PlanningContext
from app.utils.logger import get_logger

logger = get_logger(__name__)

# In-process cache: session_id -> PlanningContext
_context_cache: Dict[str, PlanningContext] = {}
# Monotonic build counter for version bumps
_build_counter: Dict[str, int] = {}


def _next_version(session_id: str) -> int:
    _build_counter[session_id] = _build_counter.get(session_id, 0) + 1
    return _build_counter[session_id]


def get_cached_context(session_id: str) -> Optional[PlanningContext]:
    """Return the cached context, or None."""
    return _context_cache.get(session_id)


async def build_planning_context(
    session_id: str,
    village_name: str = "",
    refresh: bool = False,
    include_reports: bool = True,
) -> PlanningContext:
    """Build (and cache) the authoritative PlanningContext for a session.

    Args:
        session_id: Planning session identifier.
        village_name: Village name override. When empty, resolved from the
            session record via the bundle factory.
        refresh: Force a rebuild even when a cached context exists.
        include_reports: Load layer report content + summary index (DB I/O).
            Set False for pure spatial bootstrapping.

    Returns:
        Versioned ``PlanningContext`` (never None; fields may be empty when
        the underlying data is unavailable).
    """
    if not refresh:
        cached = get_cached_context(session_id)
        if cached is not None:
            return cached

    from app.services.session_bundle import build_session_bundle
    from app.services.session_kg import ensure_session_kg

    version = _next_version(session_id)

    # 1. Bundle (cached by session_bundle; village_name resolved there)
    bundle = None
    try:
        bundle = await build_session_bundle(session_id, village_name or None)
    except Exception as e:
        logger.warning("[PlanningContext] bundle build failed: %s", e)

    resolved_village = str(getattr(bundle, "village_name", "") or "") or village_name

    # 2. Session KG (idempotent: pre-built sessions short-circuit)
    kg_session_ref = ""
    kg_version = 0
    kg = None
    if session_id:
        try:
            snap = await ensure_session_kg(session_id, resolved_village)
            if snap and not snap.get("cache_hit"):
                kg_version = int(snap.get("version", 0) or 0)
            if snap:
                kg_session_ref = session_id
            from app.modules.kg.manager import get_kg_manager

            kg = get_kg_manager().get_session_kg(session_id)
            if kg is not None and kg_session_ref:
                try:
                    kg_version = get_kg_manager().get_session_version(session_id)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[PlanningContext] session KG access failed: %s", e)

    # 3. Gazetteer
    gazetteer = None
    if resolved_village:
        try:
            from app.modules.kg.gazetteer import load_gazetteer

            gazetteer = load_gazetteer(resolved_village)
        except Exception as e:
            logger.warning("[PlanningContext] gazetteer load failed: %s", e)

    # 4. Constraint index
    constraint_index = None
    if bundle is not None:
        try:
            from app.modules.spatial_ops import build_constraint_index

            constraint_index = build_constraint_index(bundle)
        except Exception as e:
            logger.warning("[PlanningContext] constraint index build failed: %s", e)

    # 5. Village anchors + kg_query_fn (only when KG is live)
    village_anchors: list = []
    kg_query_fn = None
    if kg is not None and kg_session_ref:
        try:
            from app.modules.kg.queries.sparql import query_kg

            village_anchors = query_kg(kg, "get_village_anchors") or []
        except Exception as e:
            logger.warning("[PlanningContext] village anchors query failed: %s", e)
        try:
            from app.modules.kg.queries.sparql import query_kg as _qkg

            def kg_query_fn(template_name: str, **kw):
                return _qkg(kg, template_name, **kw)
        except Exception:
            kg_query_fn = None

    # 6. Reports + summary index (DB I/O, optional)
    reports: Dict[str, Dict[str, Any]] = {}
    report_summary_index: Dict[str, Dict[str, Any]] = {}
    if include_reports and session_id:
        try:
            from app.services.report_store import ReportStore

            store = ReportStore.get_instance()
            for layer in (1, 2, 3):
                layer_reports = await store.get_layer_reports_with_sources(
                    session_id, layer
                )
                if layer_reports:
                    for dk, rec in layer_reports.items():
                        reports.setdefault(dk, {}).update(
                            {"content": rec.get("content", ""), "instruction": rec.get("instruction", "")}
                        )
            for layer in (1, 2, 3):
                layer_summaries = await store.get_layer_summaries(session_id, layer) or {}
                report_summary_index.update(layer_summaries)
        except Exception as e:
            logger.warning("[PlanningContext] report load failed: %s", e)

    context = PlanningContext(
        session_id=session_id,
        village_name=resolved_village,
        version=version,
        bundle=bundle,
        kg=kg,
        kg_session_ref=kg_session_ref,
        kg_version=kg_version,
        gazetteer=gazetteer,
        constraint_index=constraint_index,
        village_anchors=village_anchors,
        reports=reports,
        report_summary_index=report_summary_index,
        kg_query_fn=kg_query_fn,
    )
    _context_cache[session_id] = context
    logger.info(
        "[PlanningContext] built v%d for %s (%s): bundle=%s kg=%s gaz=%s cidx=%s reports=%d anchors=%d",
        version,
        session_id,
        resolved_village or "(none)",
        bundle is not None,
        kg is not None,
        gazetteer is not None,
        constraint_index is not None,
        len(reports),
        len(village_anchors),
    )
    return context


def invalidate_planning_context(session_id: str) -> None:
    """Drop the cached context so the next build is a fresh version."""
    if session_id in _context_cache:
        del _context_cache[session_id]
    if session_id in _build_counter:
        del _build_counter[session_id]


__all__ = [
    "build_planning_context",
    "get_cached_context",
    "invalidate_planning_context",
]
