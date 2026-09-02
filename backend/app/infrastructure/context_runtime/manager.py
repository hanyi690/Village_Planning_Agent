"""Session planning context factory - single async build path.

Owns the lifecycle of the authoritative ``PlanningContext`` for a session:

    DATA catalog + World Model KG + gazetteer + constraint
    index + village anchors + reports

built *once* and reused across the EXPLORE / PARSE / GROUND / LAYOUT pipeline,
eliminating repeated catalog/report rebuilds in the workflow nodes.

Versioning: every rebuild bumps ``PlanningContext.version``. DATA products and
the session World Model are immutable/CAS-backed; ``build_planning_context``
only assembles derived parts (gazetteer / ports / constraint index / anchors /
evidence).
"""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any, Dict, Optional

from app.data.model.snapshot import SessionDataSnapshot
from app.infrastructure.context_runtime.runtime import PlanningContext
from app.contracts.ports.planning_ports import PlanningPorts
from app.spatial.model.workspace import SpatialWorkspace
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _model_value(value: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name, default)
    return getattr(value, field_name, default)


def _scope_name(value: Any) -> str:
    text = "".join(str(value or "").casefold().split())
    for suffix in (
        "村民委员会",
        "居民委员会",
        "村委会",
        "居委会",
        "行政村",
        "社区",
        "村",
    ):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


async def _load_session_administrative_scope(
    session_id: str,
    village_name: str,
) -> dict[str, str]:
    """Load the exact session scope used to filter reusable map caches."""

    values: dict[str, str] = {}
    try:
        from app.database.operations import get_planning_session_async

        session = await get_planning_session_async(session_id)
        if isinstance(session, Mapping):
            values = {
                key: str(session.get(key) or "").strip()
                for key in ("province", "city", "county", "township", "village_name")
                if str(session.get(key) or "").strip()
            }
    except Exception as exc:
        logger.warning(
            "[PlanningContext] administrative scope unavailable: %s",
            type(exc).__name__,
        )
    village = str(values.pop("village_name", "") or village_name or "").strip()
    if village:
        values["village"] = village
    return values


def _project_scope_bbox_wgs84(
    data_catalog: Any,
    schema_mapping_snapshot: Any,
    village_name: str,
) -> tuple[float, float, float, float] | None:
    """Derive an advisory project bbox from supported local geometry.

    A filename or layer key is never treated as a boundary. The candidate
    must be a polygon whose accepted canonical-name field names this village,
    and whose bounded schema decision selected an administrative-area concept
    or administrative-extent representation. The bbox filters cached source
    observations only; it is never an executable planning geometry.
    """

    if data_catalog is None or schema_mapping_snapshot is None or not village_name:
        return None
    profiles = tuple(
        _model_value(schema_mapping_snapshot, "collection_profiles", ()) or ()
    )
    decisions = tuple(_model_value(schema_mapping_snapshot, "decisions", ()) or ())
    profile_by_ref = {
        str(_model_value(profile, "collection_ref", "") or ""): profile
        for profile in profiles
    }
    name_fields: dict[tuple[str, str], set[str]] = {}
    concepts: dict[tuple[str, str], tuple[str, str]] = {}
    roles: dict[tuple[str, str], tuple[str, str]] = {}
    source_metadata_fields = {
        "filename",
        "upload_filename",
        "document_name",
        "source_uri",
        "source_dataset_ref",
        "source_feature_ref",
        "source_record_id",
        "layer_ref",
    }
    for decision in decisions:
        profile = profile_by_ref.get(
            str(_model_value(decision, "collection_ref", "") or "")
        )
        if profile is None:
            continue
        key = (
            str(_model_value(profile, "dataset_ref", "") or ""),
            str(_model_value(profile, "layer_ref", "") or ""),
        )
        status = str(_model_value(decision, "status", "unresolved") or "unresolved")
        field_name = str(_model_value(decision, "field_name", "") or "")
        property_ref = str(
            _model_value(decision, "candidate_property_ref", "") or ""
        )
        if (
            status == "accepted"
            and property_ref == "canonical_name"
            and field_name.casefold() not in source_metadata_fields
        ):
            name_fields.setdefault(key, set()).add(field_name)
        concept = str(_model_value(decision, "candidate_concept_ref", "") or "")
        role = str(_model_value(decision, "representation_role_ref", "") or "")
        if field_name == "__concept__" and concept:
            concepts[key] = concept, status
        if field_name.startswith("__representation__:") and role:
            roles[key] = role, status

    expected_name = _scope_name(village_name)
    candidates: list[tuple[int, tuple[float, float, float, float], str]] = []
    snapshot = _model_value(data_catalog, "snapshot", data_catalog)
    for feature in tuple(_model_value(snapshot, "features", ()) or ()):
        if str(_model_value(feature, "geometry_kind", "") or "") != "polygon":
            continue
        key = (
            str(_model_value(feature, "dataset_ref", "") or ""),
            str(_model_value(feature, "layer_ref", "") or ""),
        )
        fields = name_fields.get(key, set())
        attributes = dict(_model_value(feature, "raw_attributes", {}) or {})
        if not any(
            _scope_name(attributes.get(field_name)) == expected_name
            for field_name in fields
            if attributes.get(field_name) not in (None, "", [], {}, ())
        ):
            continue
        concept, concept_status = concepts.get(key, ("", "unresolved"))
        role, role_status = roles.get(key, ("", "unresolved"))
        concept_supported = concept in {"administrative_area", "place_extent"}
        role_supported = role == "administrative_extent"
        if not concept_supported and not role_supported:
            continue
        geometry = _model_value(feature, "normalized_geometry", None)
        if not isinstance(geometry, Mapping):
            continue
        try:
            from shapely.geometry import shape

            candidate = shape(dict(geometry))
            if candidate.is_empty or not candidate.is_valid:
                continue
            bounds = tuple(float(item) for item in candidate.bounds)
            if len(bounds) != 4:
                continue
        except Exception:
            continue
        score = 4
        if concept_supported:
            score += 3 if concept_status == "accepted" else 2
        if role_supported:
            score += 3 if role_status == "accepted" else 2
        candidates.append(
            (
                score,
                (bounds[0], bounds[1], bounds[2], bounds[3]),
                str(_model_value(feature, "source_feature_ref", "") or ""),
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[2]))
    highest_score = candidates[0][0]
    highest = [item for item in candidates if item[0] == highest_score]
    if len({item[1] for item in highest}) != 1:
        logger.warning(
            "[PlanningContext] conflicting project scope geometries; "
            "cache bbox filtering disabled"
        )
        return None
    return highest[0][1]


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


def context_has_cognition_ports(
    context: PlanningContext | None,
    *,
    world_model_mode: str | None = None,
) -> bool:
    """Return whether a Context satisfies the configured cognition boundary.

    DATA bootstrap may intentionally publish a Context before Cognition runs.
    Such a Context is useful to KG, but it is not reusable by EVIDENCE/L1 in a
    V2-authoritative mode.  Keeping this predicate in Context Runtime prevents
    workflow stages from inventing different definitions of "KG ready".
    """

    if context is None:
        return False
    mode = str(
        world_model_mode
        if world_model_mode is not None
        else getattr(context, "world_model_mode", "off")
        or "off"
    ).strip().lower()
    if mode not in {"shadow", "prefer_v2", "v2_only"}:
        return True
    model = getattr(context, "world_model", None) or getattr(
        context,
        "world_model_shadow",
        None,
    )
    ports = getattr(context, "ports", None)
    return bool(
        model is not None
        and getattr(ports, "current_world", None) is not None
        and getattr(ports, "world_model_commit", None) is not None
    )


async def build_planning_context(
    session_id: str,
    village_name: str = "",
    refresh: bool = False,
    include_reports: bool = True,
    version: int | None = None,
    expected_snapshot_digest: str | None = None,
    expected_world_model_digest: str | None = None,
    data_catalog: Any = None,
    boundary_scope_artifact: Any = None,
    schema_mapping_snapshot: Any = None,
    schema_mapping_artifact_ref: str = "",
    artifact_root: str = "",
    defer_cognition_bootstrap: bool = False,
) -> PlanningContext:
    """Build (and cache) the authoritative PlanningContext for a session.

    Args:
        session_id: Planning session identifier.
        village_name: Village name override. When empty, resolved from the
            session record via the DATA catalog artifact.
        refresh: Force a rebuild even when a cached context exists.
        include_reports: Load layer report content + summary index (DB I/O).
            Set False for pure spatial bootstrapping.
        data_catalog: Optional normalized catalog or raw records. Required by
            ``COGNITION_WORLD_MODEL_MODE=prefer_v2|v2_only`` and used as the generic
            source failure when the DATA catalog is unavailable.
        boundary_scope_artifact: Optional immutable admitted boundary used to
            scope provider observations; it is never reconstructed from a filename.
        schema_mapping_snapshot: Optional persisted cognition mapping. When
            supplied, Context Runtime must reuse this exact semantic version.
        schema_mapping_artifact_ref: CAS descriptor digest for that mapping.
        artifact_root: Explicit root shared by workflow artifacts and the
            World Model CAS; omitted callers use the configured runtime root.
        expected_world_model_digest: Optional committed cognition digest. A
            cached or restored Context must expose this exact immutable graph.

    Returns:
        Versioned ``PlanningContext`` (never None; fields may be empty when
        the underlying data is unavailable).
    """
    build_started = perf_counter()
    from app.core.settings import COGNITION_WORLD_MODEL_MODE

    world_model_mode = str(COGNITION_WORLD_MODEL_MODE or "off").strip().lower()
    if not refresh:
        cached = get_cached_context(session_id)
        if cached is not None:
            cached_version_matches = (
                version is None or str(getattr(cached, "version", "")) == str(version)
            )
            cached_mode_matches = (
                str(getattr(cached, "world_model_mode", "off") or "off").strip().lower()
                == world_model_mode
            )
            cached_snapshot = getattr(cached, "data_snapshot", None)
            cached_snapshot_matches = (
                not expected_snapshot_digest
                or str(getattr(cached_snapshot, "digest", ""))
                == str(expected_snapshot_digest)
            )
            incoming_catalog_digest = str(
                getattr(getattr(data_catalog, "snapshot", None), "digest", "") or ""
            )
            cached_catalog_digest = str(
                getattr(
                    getattr(getattr(cached, "data_resource_catalog", None), "snapshot", None),
                    "digest",
                    "",
                )
                or ""
            )
            cached_catalog_matches = (
                not incoming_catalog_digest
                or incoming_catalog_digest == cached_catalog_digest
            )
            incoming_boundary_ref = str(
                getattr(boundary_scope_artifact, "scope_ref", "") or ""
            )
            cached_boundary_ref = str(
                getattr(getattr(cached, "boundary_scope_artifact", None), "scope_ref", "")
                or ""
            )
            cached_boundary_matches = (
                not incoming_boundary_ref or incoming_boundary_ref == cached_boundary_ref
            )
            incoming_mapping_digest = str(
                getattr(schema_mapping_snapshot, "mapping_fingerprint", "")
                or getattr(schema_mapping_snapshot, "decision_fingerprint", "")
                or ""
            )
            cached_world_model = (
                getattr(cached, "world_model", None)
                or getattr(cached, "world_model_shadow", None)
            )
            cached_world_model_matches = (
                not expected_world_model_digest
                or str(getattr(cached_world_model, "snapshot_digest", "") or "")
                == str(expected_world_model_digest)
            )
            cached_mapping_digest = str(
                getattr(cached_world_model, "schema_mapping_digest", "")
                or ""
            )
            cached_mapping_ref = str(
                getattr(cached_world_model, "schema_mapping_artifact_ref", "")
                or ""
            )
            cached_mapping_matches = (
                (not incoming_mapping_digest or incoming_mapping_digest == cached_mapping_digest)
                and (
                    not schema_mapping_artifact_ref
                    or str(schema_mapping_artifact_ref) == cached_mapping_ref
                )
            )
            cached_cognition_ready = bool(defer_cognition_bootstrap) or (
                context_has_cognition_ports(
                    cached,
                    world_model_mode=world_model_mode,
                )
            )
            if (
                cached_version_matches
                and cached_snapshot_matches
                and cached_mode_matches
                and cached_catalog_matches
                and cached_boundary_matches
                and cached_mapping_matches
                and cached_world_model_matches
                and cached_cognition_ready
            ):
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

    if data_catalog is None:
        raise ContextBuildError(
            "context requires a normalized DATA catalog"
        )

    version = version if version is not None else await _next_persisted_version(session_id)

    resolved_village = village_name

    # Normalize arbitrary records once at the DATA boundary.  Downstream
    # modules always receive a catalog snapshot, so generators/GeoJSON
    # mappings cannot be accidentally consumed twice or leak their ad-hoc
    # field shapes into KG/GROUND.
    if data_catalog is not None:
        from app.data.resource_catalog import DataResourceCatalog

        if not isinstance(data_catalog, DataResourceCatalog):
            data_catalog = DataResourceCatalog.from_records(
                data_catalog,
                dataset_ref=f"session:{session_id}:input",
                name=resolved_village,
            )

    # 1.5 Data manifest and generic resource catalog. DATA is materialized
    # before KG so every later semantic projection has a stable snapshot and
    # capability inventory to reference. A caller-supplied catalog is a
    incoming_dependency_digest = str(
        getattr(data_catalog, "data_dependency_graph_digest", "") or ""
    )
    data_snapshot = SessionDataSnapshot.from_data_catalog(
        data_catalog,
        session_id=session_id,
        village_name=resolved_village,
        source="data_catalog",
    )
    workspace = SpatialWorkspace(data_snapshot, catalog=data_catalog)
    data_resource_catalog = None
    try:
        data_resource_catalog = workspace.to_resource_catalog(
            snapshot_id=data_snapshot.snapshot_id,
        )
    except Exception as exc:
        logger.warning(
            "[PlanningContext] generic data resource catalog unavailable: %s",
            type(exc).__name__,
        )
    if data_resource_catalog is not None:
        try:
            from app.data.admission import (
                assert_current_world_catalog,
                current_world_snapshot,
            )
            from app.data.resource_catalog import DataResourceCatalog

            # Canonicalize once before the DATA snapshot and World Model are
            # built.  DATA artifact persistence performs the same idempotent
            # admission projection; using its canonical view here guarantees
            # that DATA, KG and EVIDENCE share one catalog digest.
            data_resource_catalog = DataResourceCatalog(
                current_world_snapshot(data_resource_catalog.snapshot)
            )
            assert_current_world_catalog(data_resource_catalog.snapshot)
            if incoming_dependency_digest:
                data_resource_catalog.data_dependency_graph_digest = incoming_dependency_digest
            else:
                from app.modules.data.invalidation import build_data_dependency_graph

                data_resource_catalog.data_dependency_graph_digest = (
                    build_data_dependency_graph(
                        data_resource_catalog,
                    ).graph_digest
                )
        except (TypeError, ValueError) as exc:
            raise ContextBuildError(
                "DATA current-world admission invariant failed"
            ) from exc
        # Build the authoritative DATA snapshot after all admitted resources
        # have been normalized, otherwise valid generic layers can exist in
        # the catalog without appearing in the frozen session inventory.
        data_snapshot = SessionDataSnapshot.from_data_catalog(
            data_resource_catalog,
            session_id=session_id,
            village_name=resolved_village,
            source="data_catalog",
        )
        workspace.snapshot = data_snapshot
    if expected_snapshot_digest and data_snapshot.digest != expected_snapshot_digest:
        raise ContextBuildError(
            "context snapshot digest mismatch: "
            f"expected={expected_snapshot_digest} actual={data_snapshot.digest}"
        )
    if data_resource_catalog is not None:
        try:
            # Keep the workspace and context on one normalized DATA view.
            workspace.attach_resource_catalog(data_resource_catalog)
        except Exception as exc:
            logger.warning(
                "[PlanningContext] resource catalog attachment failed: %s",
                type(exc).__name__,
            )
        if schema_mapping_snapshot is None and not defer_cognition_bootstrap:
            try:
                from app.modules.cognition.schema_understanding import (
                    build_schema_mapping_snapshot,
                )

                schema_mapping_snapshot = build_schema_mapping_snapshot(
                    data_resource_catalog,
                    source_snapshot_ref=data_snapshot.snapshot_id,
                )
            except Exception as exc:
                logger.warning(
                    "[PlanningContext] schema mapping snapshot unavailable: %s",
                    type(exc).__name__,
                )

    # 2. DATA-backed World Model (idempotent: pre-built products short-circuit)
    kg_session_ref = ""
    kg_version = 0
    kg = None
    world_model = None
    world_model_shadow = None
    kg_error: Optional[str] = None
    # Build the store once. The old implementation performed the same cached
    # lookup again for v2 modes, which obscured the authority boundary.
    if (
        data_resource_catalog is not None
        and not defer_cognition_bootstrap
    ):
        try:
            from app.infrastructure.cognition_runtime.world_model_store import (
                get_world_model_store,
            )

            world_model = get_world_model_store(
                session_id,
                resolved_village,
                data_resource_catalog,
                schema_mapping_snapshot=schema_mapping_snapshot,
                schema_mapping_artifact_ref=schema_mapping_artifact_ref,
                artifact_root=artifact_root,
                expected_snapshot_digest=str(expected_world_model_digest or ""),
            )
            if world_model_mode == "shadow":
                world_model_shadow = world_model
            else:
                kg = world_model
                kg_session_ref = world_model.session_ref
                kg_version = world_model.version
        except Exception as exc:
            kg_error = type(exc).__name__
            logger.warning(
                "[PlanningContext] generic World Model build failed: %s",
                type(exc).__name__,
            )

    # 3. Gazetteer
    gazetteer = None

    # 3.5 Injected ports (gazetteer, spatial query, semantic query, world model)
    gazetteer_port = None
    spatial_query_port = None
    semantic_query_port = None
    current_world_port = None
    network_retry_port = None
    world_model_commit_port = None
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
        if kg is not None and world_model_mode not in {"prefer_v2", "v2_only"}:
            from app.infrastructure.kg.adapters.spatial_query_adapter import KGSpatialQueryAdapter

            spatial_query_port = KGSpatialQueryAdapter(kg)
    except Exception as e:
        logger.warning(
            "[PlanningContext] spatial_query adapter build failed: %s",
            type(e).__name__,
        )
    try:
        if kg is not None and world_model_mode not in {"prefer_v2", "v2_only"}:
            from app.infrastructure.kg.adapters.semantic_query_adapter import KGSemanticQueryAdapter

            semantic_query_port = KGSemanticQueryAdapter(kg)
    except Exception as e:
        logger.warning(
            "[PlanningContext] semantic_query adapter build failed: %s",
            type(e).__name__,
        )
    try:
        # Current consumers receive the explicitly scoped source/world view.
        world_model_for_port = world_model or (
            world_model_shadow if world_model_mode == "shadow" else None
        ) or kg
        if world_model_for_port is not None:
            current_world_port = getattr(
                world_model_for_port,
                "current_world",
                None,
            )
            if current_world_port is None:
                raise RuntimeError(
                    "DATA-backed World Model has no CurrentWorldQueryPort"
                )
            from app.infrastructure.kg.adapters.world_model_adapter import (
                KGWorldModelAdapter,
            )

            network_retry_port = KGWorldModelAdapter(
                world_model_for_port
            ).build_network_retry_adapter()
    except Exception as e:
        logger.warning(
            "[PlanningContext] world_model adapter build failed: %s",
            type(e).__name__,
        )
    try:
        world_model_for_commit = world_model or (
            world_model_shadow if world_model_mode == "shadow" else None
        )
        if world_model_for_commit is not None or kg is not None:
            if world_model_mode == "shadow" and world_model_shadow is not None:
                world_model_commit_port = world_model_shadow
            else:
                world_model_commit_port = world_model_for_commit or kg
    except Exception as e:
        logger.warning(
            "[PlanningContext] world_model commit adapter build failed: %s",
            type(e).__name__,
        )
    # The DATA-backed graph is a valid write surface for intent and planned
    # lineage in a cold-start session. Current assertions remain a later
    # Cognition transaction concern.
    if world_model_mode == "shadow" and world_model_shadow is not None:
        world_model_commit_port = world_model_shadow
    ports = PlanningPorts(
        gazetteer=gazetteer_port,
        spatial_query=spatial_query_port,
        semantic_query=semantic_query_port,
        current_world=current_world_port,
        network_retry=network_retry_port,
        world_model_commit=world_model_commit_port,
    )
    # 4. Constraint index
    constraint_index = None

    # 5. Report manifest + summary index (document-channel, no report bodies)
    reports: Dict[str, Dict[str, Any]] = {}
    report_summary_index: Dict[str, Dict[str, Any]] = {}
    # Reports are loaded through the explicitly admitted document channel.

    runtime_documents: list[Dict[str, Any]] = []
    if session_id:
        try:
            from app.data.catalog.session_documents import (
                evidence_documents,
                load_session_documents,
            )

            source_documents = evidence_documents(
                await load_session_documents(session_id, resolved_village)
            )
            runtime_documents = source_documents
        except Exception as exc:
            logger.warning(
                "[PlanningContext] input document resolution failed: %s",
                type(exc).__name__,
            )

    # Generic DATA is projected once into the cognition World Model.
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
    external_observation_snapshot = None
    administrative_scope = await _load_session_administrative_scope(
        session_id,
        resolved_village,
    )
    project_scope_bbox_wgs84 = _project_scope_bbox_wgs84(
        data_resource_catalog,
        schema_mapping_snapshot,
        administrative_scope.get("village", resolved_village),
    )
    try:
        from app.core.settings import EXTERNAL_MAP_CACHE_ROOT
        from app.data.catalog.external_observation_cache import (
            load_cached_external_observation_snapshot,
        )

        external_observation_snapshot = load_cached_external_observation_snapshot(
            resolved_village,
            root=EXTERNAL_MAP_CACHE_ROOT,
            administrative_scope=administrative_scope,
            project_bbox_wgs84=project_scope_bbox_wgs84,
        )
    except Exception as exc:
        logger.warning(
            "[PlanningContext] cached map observations unavailable: %s",
            type(exc).__name__,
        )
    # Context hydration is read-only.  Cached coordinates remain available to
    # Evidence and GROUND through ``external_observation_snapshot``; only the
    # Cognition application may project support assertions and publish a new
    # immutable World Model snapshot.  Mutating a restored store here would
    # change its digest after the Cognition CAS commit.
    world_model_shadow_diff = None
    world_model_shadow_diff_ref = ""
    if world_model_shadow is not None and data_resource_catalog is not None:
        try:
            from app.infrastructure.cognition_runtime.shadow_compare import (
                build_shadow_diff,
                persist_shadow_diff,
            )

            world_model_shadow_diff = build_shadow_diff(
                session_id=session_id,
                v1_kg=kg,
                v2_world_model=world_model_shadow,
                source_features=getattr(data_resource_catalog.snapshot, "features", ()) or (),
                v1_snapshot_ref=str(getattr(kg, "session_id", "") or session_id),
                v1_snapshot_digest=str(getattr(kg, "snapshot_digest", "") or ""),
            )
            world_model_shadow_diff_ref = persist_shadow_diff(world_model_shadow_diff)
        except Exception as exc:
            logger.warning(
                "[PlanningContext] world-model shadow diff unavailable: %s",
                type(exc).__name__,
            )
    if kg is not None:
        kg_version = int(getattr(kg, "version", kg_version) or kg_version)
    context = PlanningContext(
        session_id=session_id,
        village_name=resolved_village,
        administrative_scope=administrative_scope,
        project_scope_bbox_wgs84=project_scope_bbox_wgs84,
        version=version,
        workspace=workspace,
        data_resource_catalog=data_resource_catalog,
        data_snapshot=data_snapshot,
        boundary_scope_artifact=boundary_scope_artifact,
        networks=networks,
        demands=demands,
        kg=kg,
        world_model=world_model,
        kg_session_ref=kg_session_ref,
        kg_version=kg_version,
        world_model_mode=world_model_mode,
        world_model_shadow=world_model_shadow,
        world_model_shadow_diff=world_model_shadow_diff,
        world_model_shadow_diff_ref=world_model_shadow_diff_ref,
        schema_mapping_snapshot=schema_mapping_snapshot,
        gazetteer=gazetteer,
        constraint_index=constraint_index,
        input_documents=runtime_documents,
        reports=reports,
        reports_loaded=bool(include_reports and session_id and runtime_documents),
        report_summary_index=report_summary_index,
        external_search_port=external_search_port,
        external_observation_snapshot=external_observation_snapshot,
        ports=ports,
    )

    parcel_count = len(context.current_parcels())
    context._content_inputs = {
        "session_id": session_id,
        "village_name": resolved_village,
        "administrative_scope": administrative_scope,
        "project_scope_bbox_wgs84": project_scope_bbox_wgs84,
        "version": version,
        "parcel_count": parcel_count,
        "data_snapshot_digest": data_snapshot.digest,
        "data_resource_catalog_digest": str(
            getattr(getattr(data_resource_catalog, "snapshot", None), "digest", "") or ""
        ),
        "boundary_scope_ref": str(
            getattr(boundary_scope_artifact, "scope_ref", "") or ""
        ),
        "boundary_digest": str(
            getattr(boundary_scope_artifact, "boundary_digest", "") or ""
        ),
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
        "generic_world_model_snapshot_ref": str(
            getattr(world_model, "snapshot_ref", "") or ""
        ),
        "generic_world_model_snapshot_digest": str(
            getattr(world_model, "snapshot_digest", "") or ""
        ),
        "world_model_mode": world_model_mode,
        "world_model_snapshot_ref": str(getattr(kg, "snapshot_ref", "") or ""),
        "world_model_snapshot_digest": str(getattr(kg, "snapshot_digest", "") or ""),
        "world_model_shadow_snapshot_ref": str(
            getattr(world_model_shadow, "snapshot_ref", "") or ""
        ),
        "world_model_shadow_snapshot_digest": str(
            getattr(world_model_shadow, "snapshot_digest", "") or ""
        ),
        "world_model_shadow_diff_digest": str(
            getattr(world_model_shadow_diff, "digest", "") or ""
        ),
        "world_model_shadow_diff_ref": world_model_shadow_diff_ref,
        "schema_mapping_digest": str(
            getattr(schema_mapping_snapshot, "digest", "")
            or getattr(schema_mapping_snapshot, "candidate_digest", "")
            or ""
        ),
        "has_constraint_index": constraint_index is not None,
        "report_count": len(reports),
        "reports_loaded": context.reports_loaded,
        "report_keys": sorted(reports.keys()),
        "external_observation_digest": str(
            getattr(external_observation_snapshot, "digest", "") or ""
        ),
        "external_observation_count": len(
            getattr(external_observation_snapshot, "observations", []) or []
        ),
    }
    context._record_capabilities()
    context.required_capabilities_missing = [
        cap for cap, present in context.capabilities.items()
        if not present and cap != "external_observations"
    ]
    context._recompute_hash()

    actual_world_model_digest = str(
        getattr(
            getattr(context, "world_model", None)
            or getattr(context, "world_model_shadow", None),
            "snapshot_digest",
            "",
        )
        or ""
    )
    if (
        expected_world_model_digest
        and actual_world_model_digest != str(expected_world_model_digest)
    ):
        raise ContextBuildError(
            "context WorldModel digest mismatch: "
            f"expected={expected_world_model_digest} actual={actual_world_model_digest}"
        )

    if (
        not defer_cognition_bootstrap
        and world_model_mode in {"shadow", "prefer_v2", "v2_only"}
        and not context_has_cognition_ports(
            context,
            world_model_mode=world_model_mode,
        )
    ):
        raise ContextBuildError(
            "cognition context is incomplete: WorldModel read/commit ports are required"
        )

    # 6.5 EvidenceGraph is the compatibility spatial-evidence boundary.  A
    # prefer_v2/v2_only context must not construct it; V2 callers use the injected
    # world-model/catalog ports and explicit Evidence Runtime adapters.
    if world_model_mode not in {"shadow", "prefer_v2", "v2_only"}:
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
        "[PlanningContext] built v%d for %s (%s): snapshot=%s kg=%s gaz=%s cidx=%s reports=%d elapsed_ms=%.1f",
        version,
        session_id,
        resolved_village or "(none)",
        data_snapshot.digest,
        kg is not None,
        gazetteer is not None,
        constraint_index is not None,
        len(reports),
        (perf_counter() - build_started) * 1000,
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
    "context_has_cognition_ports",
    "get_cached_context",
    "invalidate_planning_context",
    "ContextBuildError",
]
