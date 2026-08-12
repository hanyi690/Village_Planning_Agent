"""Session planning context factory - single async build path.

Owns the lifecycle of the authoritative ``PlanningContext`` for a session:

    bundle + session KG + gazetteer + constraint index + village anchors + reports

built *once* and reused across the EXPLORE / PARSE / GROUND / LAYOUT pipeline,
eliminating the repeated Bundle/KG/report rebuilds in ``gis_agent_node``,
``ensure_session_kg`` and ``layout_pipeline._fetch/_build_kg``.

Versioning: every rebuild bumps ``PlanningContext.version``. The bundle is
cached in ``app.application.sessions.session_bundle``; the session KG is idempotent in
``KGManager``. ``build_planning_context`` reuses both and only assembles the
derived parts (gazetteer / ports / constraint index / anchors / evidence).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.data.model.snapshot import SessionDataSnapshot
from app.infrastructure.context.planning_context import PlanningContext
from app.contracts.ports.planning_ports import PlanningPorts
from app.spatial.model.workspace import SpatialWorkspace
from app.utils.logger import get_logger

logger = get_logger(__name__)

# In-process cache: session_id -> PlanningContext
_context_cache: Dict[str, PlanningContext] = {}
# Monotonic build counter for version bumps
_build_counter: Dict[str, int] = {}


class ContextBuildError(RuntimeError):
    pass


def _load_session_semantic_memory(session_id: str) -> Any:
    """Restore the latest persisted KG semantic annotations for a session.

    L1 enrichment writes village→ResidentialCluster bindings to the semantic
    memory round files.  A resumed LangGraph thread may run in a fresh worker
    where the process singleton is empty; rebuilding a gazetteer without this
    persisted memory silently drops the L1 bindings and makes GROUND diverge
    from the checkpoint.  Loading the latest round is deterministic and scoped
    to the session id, so it does not introduce cross-session state.
    """
    try:
        from app.infrastructure.kg.memory import (
            SemanticMemoryStore,
            get_memory_dir,
            load_memory_state,
        )

        candidates = list(get_memory_dir().glob(f"{session_id}_round_*.json"))
        if not candidates:
            return SemanticMemoryStore()

        def round_number(path: Any) -> int:
            try:
                return int(path.stem.rsplit("_round_", 1)[1])
            except (IndexError, TypeError, ValueError):
                return -1

        latest = max(candidates, key=round_number)
        round_num = round_number(latest)
        if round_num < 0:
            return SemanticMemoryStore()
        return load_memory_state(session_id, round_num)
    except Exception as exc:
        logger.warning("[PlanningContext] semantic memory restore failed: %s", exc)
        try:
            from app.infrastructure.kg.memory import SemanticMemoryStore

            return SemanticMemoryStore()
        except Exception:
            return None


def _next_version(session_id: str) -> int:
    _build_counter[session_id] = _build_counter.get(session_id, 0) + 1
    return _build_counter[session_id]


async def _next_persisted_version(session_id: str) -> int:
    """Get a monotonic version from the DB so it survives process restart."""
    try:
        import aiosqlite
        from app.database.engine import get_db_path

        async with aiosqlite.connect(str(get_db_path())) as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS context_version (session_id TEXT PRIMARY KEY, version INTEGER)"
            )
            await conn.execute(
                "INSERT INTO context_version(session_id, version) VALUES(?, 1) "
                "ON CONFLICT(session_id) DO UPDATE SET version = version + 1",
                (session_id,),
            )
            await conn.commit()
            async with conn.execute(
                "SELECT version FROM context_version WHERE session_id = ?", (session_id,)
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 1
    except Exception as e:
        logger.warning("[PlanningContext] persisted version failed, using in-process fallback: %s", e)
        return _next_version(session_id)


def get_cached_context(session_id: str) -> Optional[PlanningContext]:
    """Return the cached context, or None."""
    return _context_cache.get(session_id)


async def build_planning_context(
    session_id: str,
    village_name: str = "",
    refresh: bool = False,
    include_reports: bool = True,
    version: int | None = None,
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

    from app.application.sessions.session_bundle import build_session_bundle
    from app.infrastructure.kg.session_kg import ensure_session_kg

    version = version if version is not None else await _next_persisted_version(session_id)

    # 1. Bundle (cached by session_bundle; village_name resolved there)
    bundle = None
    bundle_error: Optional[str] = None
    try:
        bundle = await build_session_bundle(session_id, village_name or None)
    except Exception as e:
        bundle_error = str(e)
        logger.warning("[PlanningContext] bundle build failed: %s", e)

    resolved_village = str(getattr(bundle, "village_name", "") or "") or village_name

    # 2. Session KG (idempotent: pre-built sessions short-circuit)
    kg_session_ref = ""
    kg_version = 0
    kg = None
    kg_error: Optional[str] = None
    if session_id:
        try:
            snap = await ensure_session_kg(session_id, resolved_village)
            if snap and not snap.get("cache_hit"):
                kg_version = int(snap.get("version", 0) or 0)
            if snap:
                kg_session_ref = session_id
            from app.infrastructure.kg.manager import get_kg_manager

            kg = get_kg_manager().get_session_kg(session_id)
            if kg is not None and kg_session_ref:
                try:
                    kg_version = get_kg_manager().get_session_version(session_id)
                except Exception:
                    pass
        except Exception as e:
            kg_error = str(e)
            logger.warning("[PlanningContext] session KG access failed: %s", e)

    # 3. Gazetteer
    gazetteer = None
    if resolved_village:
        try:
            from app.infrastructure.kg.gazetteer import build_gazetteer

            if kg is not None and bundle is not None and getattr(kg, "g", None) is not None:
                # The latest L1/L2/L3 enrichment round is part of the
                # authoritative context inputs.  It must be restored before
                # any checkpoint replay; otherwise the same thread sees a
                # different gazetteer after process restart.
                memory = _load_session_semantic_memory(session_id)
                gazetteer = build_gazetteer(kg, bundle, memory=memory)
        except Exception as e:
            logger.warning("[PlanningContext] gazetteer build failed: %s", e)

    # 3.5 Injected ports (kg adapters: gazetteer + spatial_query)
    gazetteer_port = None
    spatial_query_port = None
    semantic_query_port = None
    try:
        if gazetteer is not None:
            from app.infrastructure.kg.adapters.gazetteer_adapter import KGGazetteerAdapter

            gazetteer_port = KGGazetteerAdapter(gazetteer)
    except Exception as e:
        logger.warning("[PlanningContext] gazetteer adapter build failed: %s", e)
    try:
        if kg is not None:
            from app.infrastructure.kg.adapters.spatial_query_adapter import KGSpatialQueryAdapter

            spatial_query_port = KGSpatialQueryAdapter(kg)
    except Exception as e:
        logger.warning("[PlanningContext] spatial_query adapter build failed: %s", e)
    try:
        if kg is not None:
            from app.infrastructure.kg.adapters.semantic_query_adapter import KGSemanticQueryAdapter

            semantic_query_port = KGSemanticQueryAdapter(kg)
    except Exception as e:
        logger.warning("[PlanningContext] semantic_query adapter build failed: %s", e)
    ports = PlanningPorts(
        gazetteer=gazetteer_port,
        spatial_query=spatial_query_port,
        semantic_query=semantic_query_port,
    )
    try:
        from app.data.ingestion.bundle_assembly_adapter import DataBundleAssemblyAdapter

        ports.bundle_assembly = DataBundleAssemblyAdapter()
    except Exception as e:
        logger.warning("[PlanningContext] bundle_assembly adapter build failed: %s", e)

    # 4. Constraint index
    constraint_index = None
    if bundle is not None:
        try:
            from app.spatial.query.bridge import build_constraint_index

            constraint_index = build_constraint_index(bundle)
        except Exception as e:
            logger.warning("[PlanningContext] constraint index build failed: %s", e)

    # 5. Village anchors (only when KG is live)
    village_anchors: list = []
    if kg is not None and kg_session_ref:
        try:
            from app.infrastructure.kg.queries.sparql import query_kg

            village_anchors = query_kg(kg, "get_village_anchors") or []
        except Exception as e:
            logger.warning("[PlanningContext] village anchors query failed: %s", e)

    # 6. Reports + summary index (DB I/O, optional)
    reports: Dict[str, Dict[str, Any]] = {}
    report_summary_index: Dict[str, Dict[str, Any]] = {}
    if include_reports and session_id:
        try:
            from app.infrastructure.reports.report_store import ReportStore

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
        except Exception as e:
            logger.warning("[PlanningContext] report load failed: %s", e)

    if bundle is None:
        raise ContextBuildError(
            f"required capability 'bundle' missing (bundle_error={bundle_error})"
        )

    data_snapshot = SessionDataSnapshot.from_bundle(
        bundle,
        session_id=session_id,
        source="data_catalog",
    )
    workspace = SpatialWorkspace(data_snapshot, bundle)
    context = PlanningContext(
        session_id=session_id,
        village_name=resolved_village,
        version=version,
        workspace=workspace,
        data_snapshot=data_snapshot,
        kg=kg,
        kg_session_ref=kg_session_ref,
        kg_version=kg_version,
        gazetteer=gazetteer,
        constraint_index=constraint_index,
        village_anchors=village_anchors,
        reports=reports,
        report_summary_index=report_summary_index,
        ports=ports,
    )

    parcel_count = len(context.current_parcels())
    context._content_inputs = {
        "session_id": session_id,
        "village_name": resolved_village,
        "version": version,
        "parcel_count": parcel_count,
        "data_snapshot_digest": data_snapshot.digest,
        "kg_session_ref": kg_session_ref,
        "kg_version": kg_version,
        "has_constraint_index": constraint_index is not None,
        "report_count": len(reports),
        "report_keys": sorted(reports.keys()),
    }
    context._record_capabilities()
    context.required_capabilities_missing = [
        cap for cap, present in context.capabilities.items()
        if not present and cap != "bundle"
    ]
    context._recompute_hash()

    # 6.5 PlaceEvidenceIndex (non-fatal; None on failure)
    try:
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        context.evidence_index = PlaceEvidenceIndex.build(context)
    except Exception as e:
        logger.warning("[PlanningContext] evidence index build failed: %s", e)
    _context_cache[session_id] = context
    logger.info(
        "[PlanningContext] built v%d for %s (%s): snapshot=%s kg=%s gaz=%s cidx=%s reports=%d anchors=%d",
        version,
        session_id,
        resolved_village or "(none)",
        data_snapshot.digest,
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
    "ContextBuildError",
]
