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
from app.infrastructure.context_runtime.runtime import PlanningContext
from app.contracts.ports.planning_ports import PlanningPorts
from app.spatial.model.workspace import SpatialWorkspace
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _build_context_networks(workspace: SpatialWorkspace) -> dict[str, Any]:
    """Build the canonical current-road snapshot for relation evaluation.

    The snapshot is deliberately keyed by one stable semantic ref.  Typed
    Connect/Access/Service parameters must name this ref explicitly; no
    arbitrary network is inferred from a prose road count or a nearest line.
    """

    roads = list((getattr(workspace, "lines", {}) or {}).get("roads_current") or [])
    if not roads:
        return {}
    try:
        from app.spatial.network.network_graph import build_network_graph

        source_crs = "EPSG:4326"
        first = roads[0]
        candidate_crs = getattr(first, "crs", None)
        if candidate_crs is None and isinstance(first, dict):
            candidate_crs = first.get("crs") or (first.get("properties") or {}).get("crs")
        if candidate_crs:
            source_crs = str(candidate_crs)
        snapshot = build_network_graph(
            roads,
            impedance="travel_time_min",
            network_ref="network:road:current",
            source_crs=source_crs,
            metric_crs="EPSG:3857",
            snap_tolerance_m=5.0,
        )
        return {snapshot.network_ref: snapshot}
    except Exception as exc:
        logger.warning(
            "[PlanningContext] current-road network snapshot unavailable: %s",
            type(exc).__name__,
        )
        return {}


def _build_context_demands(workspace: SpatialWorkspace) -> dict[str, Any]:
    """Build demand snapshots only from an explicit typed demand layer.

    Existing annotations, population tables and facility counts are not
    demand points.  They remain available to evidence/grounding until a
    producer supplies a layer with an explicit demand value and unit.
    """

    points_by_layer = getattr(workspace, "points", {}) or {}
    for layer_key in ("demand_points", "population_demand"):
        raw_points = list(points_by_layer.get(layer_key) or [])
        if not raw_points:
            continue
        try:
            from app.modules.l2.facility_demand_model import (
                FacilityDemandPoint,
                build_demand_snapshot,
            )

            points: list[FacilityDemandPoint] = []
            for feature in raw_points:
                properties = (
                    feature.get("properties", {})
                    if isinstance(feature, dict)
                    else getattr(feature, "properties", {}) or {}
                )
                demand_id = str(
                    properties.get("demand_id")
                    or getattr(feature, "demand_id", "")
                    or ""
                ).strip()
                demand_value = properties.get("demand_value")
                demand_unit = str(properties.get("demand_unit") or "").strip()
                if (
                    not demand_id
                    or not isinstance(demand_value, (int, float))
                    or isinstance(demand_value, bool)
                    or demand_value < 0
                    or not demand_unit
                ):
                    continue
                facility_types = properties.get("facility_types") or ()
                if isinstance(facility_types, str):
                    facility_types = (facility_types,)
                points.append(
                    FacilityDemandPoint.from_feature(
                        feature,
                        demand_id=demand_id,
                        demand_value=float(demand_value),
                        demand_unit=demand_unit,
                        facility_types=facility_types,
                    )
                )
            if not points:
                continue
            demand_ref = f"demand:{layer_key}"
            snapshot_digest = str(getattr(getattr(workspace, "snapshot", None), "digest", "") or "")
            snapshot = build_demand_snapshot(
                demand_ref,
                points,
                source_refs=tuple(
                    ref for ref in (f"data_snapshot:{snapshot_digest}" if snapshot_digest else "", layer_key)
                    if ref
                ),
            )
            return {demand_ref: snapshot}
        except Exception as exc:
            logger.warning(
                "[PlanningContext] typed demand snapshot unavailable: %s",
                type(exc).__name__,
            )
            continue
    return {}
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
        logger.warning(
            "[PlanningContext] semantic memory restore failed: %s",
            type(exc).__name__,
        )
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
        logger.warning(
            "[PlanningContext] persisted version failed, using in-process fallback: %s",
            type(e).__name__,
        )
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
    expected_snapshot_digest: str | None = None,
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
            cached_version_matches = (
                version is None or str(getattr(cached, "version", "")) == str(version)
            )
            cached_snapshot = getattr(cached, "data_snapshot", None)
            cached_snapshot_matches = (
                not expected_snapshot_digest
                or str(getattr(cached_snapshot, "digest", ""))
                == str(expected_snapshot_digest)
            )
            if cached_version_matches and cached_snapshot_matches:
                return cached
            logger.info(
                "[PlanningContext] invalidating cached context for %s "
                "(version=%s/%s snapshot=%s/%s)",
                session_id,
                getattr(cached, "version", ""),
                version,
                getattr(cached_snapshot, "digest", ""),
                expected_snapshot_digest,
            )

    from app.application.sessions.session_bundle import build_session_bundle
    from app.infrastructure.kg.session_kg import ensure_session_kg

    version = version if version is not None else await _next_persisted_version(session_id)

    # 1. Bundle.  During checkpoint replay, prefer the persisted bundle that
    # produced the checkpoint.  Rebuilding from the live catalog can reorder
    # synthetic legacy features or otherwise produce a different snapshot
    # digest even when the authoritative source files are unchanged.  The
    # expected digest is still checked below, so this remains fail-closed.
    bundle = None
    bundle_error: Optional[str] = None
    try:
        if expected_snapshot_digest:
            from app.application.sessions.session_bundle import (
                invalidate_session_bundle,
                restore_session_bundle,
            )

            invalidate_session_bundle(session_id)
            bundle = await restore_session_bundle(session_id)
        if bundle is None:
            bundle = await build_session_bundle(session_id, village_name or None)
    except Exception as e:
        bundle_error = type(e).__name__
        logger.warning("[PlanningContext] bundle build failed: %s", type(e).__name__)

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
            kg_error = type(e).__name__
            logger.warning(
                "[PlanningContext] session KG access failed: %s",
                type(e).__name__,
            )

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
                gazetteer = build_gazetteer(
                    kg,
                    bundle,
                    memory=memory,
                    village_name=resolved_village,
                )
        except Exception as e:
            logger.warning(
                "[PlanningContext] gazetteer build failed: %s",
                type(e).__name__,
            )

    # 3.5 Injected ports (kg adapters: gazetteer + spatial_query)
    gazetteer_port = None
    spatial_query_port = None
    semantic_query_port = None
    try:
        if gazetteer is not None:
            from app.infrastructure.kg.adapters.gazetteer_adapter import KGGazetteerAdapter

            gazetteer_port = KGGazetteerAdapter(gazetteer)
    except Exception as e:
        logger.warning(
            "[PlanningContext] gazetteer adapter build failed: %s",
            type(e).__name__,
        )
    try:
        if kg is not None:
            from app.infrastructure.kg.adapters.spatial_query_adapter import KGSpatialQueryAdapter

            spatial_query_port = KGSpatialQueryAdapter(kg)
    except Exception as e:
        logger.warning(
            "[PlanningContext] spatial_query adapter build failed: %s",
            type(e).__name__,
        )
    try:
        if kg is not None:
            from app.infrastructure.kg.adapters.semantic_query_adapter import KGSemanticQueryAdapter

            semantic_query_port = KGSemanticQueryAdapter(kg)
    except Exception as e:
        logger.warning(
            "[PlanningContext] semantic_query adapter build failed: %s",
            type(e).__name__,
        )
    ports = PlanningPorts(
        gazetteer=gazetteer_port,
        spatial_query=spatial_query_port,
        semantic_query=semantic_query_port,
    )
    try:
        from app.data.ingestion.bundle_assembly_adapter import DataBundleAssemblyAdapter

        ports.bundle_assembly = DataBundleAssemblyAdapter()
    except Exception as e:
        logger.warning(
            "[PlanningContext] bundle_assembly adapter build failed: %s",
            type(e).__name__,
        )

    # 4. Constraint index
    constraint_index = None
    if bundle is not None:
        try:
            from app.spatial.query.bridge import build_constraint_index

            constraint_index = build_constraint_index(bundle)
        except Exception as e:
            logger.warning(
                "[PlanningContext] constraint index build failed: %s",
                type(e).__name__,
            )

    # 5. Report manifest + summary index (bundle-owned, no report bodies)
    reports: Dict[str, Dict[str, Any]] = {}
    report_summary_index: Dict[str, Dict[str, Any]] = {}
    if include_reports and session_id and bundle is not None:
        for ref in list(getattr(bundle.documents, "report_refs", []) or []):
            dk = str(ref.get("dimension_key") or "")
            layer = int(ref.get("layer") or 0)
            if not dk or layer not in (1, 2, 3):
                continue
            entry = reports.setdefault(dk, {})
            entry.update({
                "summary": ref.get("summary", ""),
                "instruction": ref.get("instruction", ""),
                "layer": layer,
                "report_id": ref.get("report_id", ""),
            })
            entry.setdefault("layers", {})[f"L{layer}"] = {
                "summary": ref.get("summary", ""),
                "instruction": ref.get("instruction", ""),
                "knowledge_sources": ref.get("knowledge_sources", []),
                "report_id": ref.get("report_id", ""),
                "version": ref.get("version", ""),
            }
            summary_entry = report_summary_index.setdefault(dk, {})
            summary_entry.setdefault("layers", {})[f"L{layer}"] = {
                "summary": ref.get("summary", ""),
                "report_id": ref.get("report_id", ""),
                "version": ref.get("version", ""),
            }

    if bundle is None:
        raise ContextBuildError(
            f"required capability 'bundle' missing (bundle_error={bundle_error})"
        )

    runtime_documents: list[Dict[str, Any]] = []
    if session_id:
        try:
            from app.data.catalog.session_documents import load_session_documents

            source_documents = await load_session_documents(
                session_id, bundle.village_name
            )
            allowed_refs = {
                (
                    str(ref.get("source") or ""),
                    str(ref.get("name") or ""),
                    str(ref.get("content_digest") or ""),
                )
                for ref in list(getattr(bundle.documents, "document_refs", []) or [])
            }
            runtime_documents = [
                document for document in source_documents
                if (
                    str(document.get("source") or ""),
                    str(document.get("name") or ""),
                    str(document.get("content_digest") or ""),
                ) in allowed_refs
            ]
        except Exception as exc:
            logger.warning(
                "[PlanningContext] input document resolution failed: %s",
                type(exc).__name__,
            )

    data_snapshot = SessionDataSnapshot.from_bundle(
        bundle,
        session_id=session_id,
        source="data_catalog",
    )
    if expected_snapshot_digest and data_snapshot.digest != expected_snapshot_digest:
        raise ContextBuildError(
            "context snapshot digest mismatch: "
            f"expected={expected_snapshot_digest} actual={data_snapshot.digest}"
        )
    workspace = SpatialWorkspace(data_snapshot, bundle)
    networks = _build_context_networks(workspace)
    demands = _build_context_demands(workspace)
    external_search_port = None
    try:
        from app.infrastructure.search.provider_registry import get_active_external_provider

        external_search_port = get_active_external_provider()
    except Exception as exc:
        logger.debug(
            "[PlanningContext] external provider unavailable: %s",
            type(exc).__name__,
        )
    context = PlanningContext(
        session_id=session_id,
        village_name=resolved_village,
        version=version,
        workspace=workspace,
        data_snapshot=data_snapshot,
        networks=networks,
        demands=demands,
        kg=kg,
        kg_session_ref=kg_session_ref,
        kg_version=kg_version,
        gazetteer=gazetteer,
        constraint_index=constraint_index,
        input_documents=runtime_documents,
        reports=reports,
        reports_loaded=bool(include_reports and session_id and bundle is not None),
        report_summary_index=report_summary_index,
        external_search_port=external_search_port,
        ports=ports,
    )

    parcel_count = len(context.current_parcels())
    context._content_inputs = {
        "session_id": session_id,
        "village_name": resolved_village,
        "version": version,
        "parcel_count": parcel_count,
        "data_snapshot_digest": data_snapshot.digest,
        "network_refs": sorted(networks),
        "network_fingerprints": {
            str(key): str(getattr(value, "fingerprint", "") or "")
            for key, value in networks.items()
        },
        "demand_refs": sorted(demands),
        "demand_fingerprints": {
            str(key): str(getattr(value, "fingerprint", "") or "")
            for key, value in demands.items()
        },
        "kg_session_ref": kg_session_ref,
        "kg_version": kg_version,
        "has_constraint_index": constraint_index is not None,
        "report_count": len(reports),
        "reports_loaded": context.reports_loaded,
        "report_keys": sorted(reports.keys()),
    }
    context._record_capabilities()
    context.required_capabilities_missing = [
        cap for cap, present in context.capabilities.items()
        if not present and cap != "bundle"
    ]
    context._recompute_hash()

    # 6.5 EvidenceGraph is the single spatial-evidence boundary.  Its
    # deterministic index remains private to the graph implementation.
    try:
        from app.infrastructure.evidence_runtime.evidence_graph import EvidenceGraph

        context.evidence_graph = EvidenceGraph.build(context)
    except Exception as e:
        logger.warning(
            "[PlanningContext] evidence graph build failed: %s",
            type(e).__name__,
        )
    _context_cache[session_id] = context
    logger.info(
        "[PlanningContext] built v%d for %s (%s): snapshot=%s kg=%s gaz=%s cidx=%s reports=%d",
        version,
        session_id,
        resolved_village or "(none)",
        data_snapshot.digest,
        kg is not None,
        gazetteer is not None,
        constraint_index is not None,
        len(reports),
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
