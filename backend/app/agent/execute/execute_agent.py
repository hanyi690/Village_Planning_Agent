"""EXECUTE Agent - spatial execution subgraph.

Migrated from agent/gis/execute/agent.py per docs/architecture/agent-graph.md §5.

Consumes PARSE intent + SELECT SiteSelectionDecision, compiles them into a
complete PlannedState via the multi-worker subgraph (Wave O):

    route_tasks -> prepare_inputs -> project_worker -> zone_worker
      -> [facility_worker || axis_worker]   (LangGraph parallel fan-out)
      -> road_worker -> merge_worker_results -> geometry_materialize
      -> planned_state_builder -> execution_review

Core principles:
- EXECUTE never re-reads text, re-selects sites, or re-maps current land use.
  It only compiles ``SiteSelectionDecision + ExecutionPlan`` into a complete
  ``PlannedState``.
- The 5 workers each return a unified ``WorkerResult`` (no direct shared-state
  mutation); ``merge_worker_results`` merges them (BSM conflict detection +
  layout dedup + ParcelChangeSet).
- ``execution_review`` only performs execution checks (input completeness /
  worker-output completeness / change lineage / geometry validity / worker
  conflicts) and produces ``validation_result`` for the outer VALIDATE stage;
  it does NOT repeat the full VALIDATE aggregate (area conservation, hard
  constraints, topology, reachability, stage attribution live in post-L3).
- Empty ``candidate_bsms`` zones are solved by ``zone_worker`` via the
  ``ZoneAllocatorPort`` (PuLP MIP); infeasible -> ``design_unresolved``
  diagnostics, never silently skipped.

P1 wiring: nodes call the underlying generation helpers directly
(generate._generate_*, validate_aggregate) rather than the @tool wrappers,
bypassing InjectedState. This couples execute/ to tools/gis private helpers;
P2 should promote them to a public generation API.
"""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from langgraph.graph import StateGraph, END, START

from app.agent.execute.execute_state import ExecuteAgentState
from app.modules.schema.contracts.execution_plan_contracts import WorkerResult
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _checkpoint_safe(value: Any) -> Any:
    """Convert NumPy scalar containers to checkpoint-serializable primitives."""
    module_name = type(value).__module__
    if module_name == "numpy" or module_name.startswith("numpy."):
        if hasattr(value, "item"):
            return _checkpoint_safe(value.item())
        if hasattr(value, "tolist"):
            return _checkpoint_safe(value.tolist())
    if isinstance(value, dict):
        return {key: _checkpoint_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_checkpoint_safe(item) for item in value]
    return value


def _checkpoint_safe_node(
    node: Callable[[ExecuteAgentState], Awaitable[dict]],
) -> Callable[[ExecuteAgentState], Awaitable[dict]]:
    @wraps(node)
    async def wrapped(state: ExecuteAgentState) -> dict:
        return _checkpoint_safe(await node(state))

    return wrapped


def _execution_error(
    state: ExecuteAgentState,
    stage: str,
    code: str,
    message: str,
) -> dict:
    issue = {"stage": stage, "code": code, "message": message}
    existing = list(state.execution_errors or [])
    if not any(
        item.get("stage") == stage and item.get("code") == code
        for item in existing
    ):
        existing.append(issue)
    return {"execution_errors": existing}


# ── Shared helpers ───────────────────────────────────────────────────


def _intent_list(intent: Any, key: str) -> List[Any]:
    """Read a list field off a typed intent or a legacy intent dict."""
    if intent is None:
        return []
    if isinstance(intent, dict):
        value = intent.get(key)
    else:
        value = getattr(intent, key, None)
    return list(value or [])


def _worker_result_get(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


def _worker_type(result: Any) -> str:
    return str(_worker_result_get(result, "worker_type", "") or "")


def _task_enabled(state: ExecuteAgentState, task: str) -> bool:
    """A task runs when no explicit routing was set, or when it is routed.

    Legacy nodes treated an empty ``tasks_to_run`` as "run everything"; the
    graph always populates ``tasks_to_run`` via ``_route_tasks_node``.
    """
    return not state.tasks_to_run or task in state.tasks_to_run


def _build_landuse_geojson(state: ExecuteAgentState) -> dict:
    """Resolve the current land-use GeoJSON from gis_bundle or gis_data."""
    gis_data = state.gis_data or {}
    gis_bundle = getattr(state, "gis_bundle", None)
    if gis_bundle is not None and hasattr(gis_bundle, "polygons") and (
        gis_bundle.polygons.get("landuse_current")
        or gis_bundle.polygons.get("landuse_planned")
    ):
        landuse = gis_bundle.to_geojson_dict().get("landuse_current_geojson")
    else:
        landuse = gis_data.get("landuse_current_geojson")
    return landuse or {}


def _build_parcel_by_bsm(state: ExecuteAgentState) -> Dict[str, Any]:
    """Map bsm -> parcel (Land Design Worker shape) from the current land use."""
    landuse = _build_landuse_geojson(state)
    return {
        str((feature.get("properties") or {}).get("BSM")
            or (feature.get("properties") or {}).get("bsm") or ""): _parcel_from_feature(feature)
        for feature in (landuse.get("features") or [])
    }


def _resolve_parcel_by_bsm(state: ExecuteAgentState) -> Dict[str, Any]:
    """Prepared parcel index, falling back to a fresh build when empty.

    Direct node/worker invocation in tests skips ``prepare_inputs``; this keeps
    the workers functional by deriving the index from gis_data on demand.
    """
    return dict(state.parcel_by_bsm or {}) or _build_parcel_by_bsm(state)


def _parcel_from_feature(feature: dict) -> Any:
    """Adapt a landuse GeoJSON feature into the Land Design Worker parcel shape.

    The worker reads .bsm/.geometry/.dlbm/.area_sqm from each parcel entry.
    """
    from types import SimpleNamespace

    props = feature.get("properties") or {}
    return SimpleNamespace(
        bsm=str(props.get("BSM") or props.get("bsm") or ""),
        geometry=feature.get("geometry"),
        dlbm=str(props.get("DLBM") or props.get("dlbm") or ""),
        area_sqm=float(props.get("area_sqm") or props.get("area") or 0),
        area_ha=float(props.get("area_ha") or 0),
    )


def _parcel_geometry(parcel: Any) -> dict:
    geometry = getattr(parcel, "geometry", None)
    return geometry if isinstance(geometry, dict) else {}


def _footprint_geometry(change: Any, fallback_geometry: dict) -> dict:
    """Polygon footprint for a planned feature.

    Prefer the change's after geometry (WKT -> GeoJSON); fall back to the
    source parcel geometry when the WKT is empty or invalid.
    """
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    after_wkt = getattr(change, "after_geometry_wkt", "") or ""
    if after_wkt:
        try:
            geom = wkt.loads(after_wkt)
            if not geom.is_empty:
                return geometry_mapping(geom)
        except Exception:
            pass
    return fallback_geometry or {}


def _assemble_execution_plan(state: ExecuteAgentState) -> Any:
    """Compile the ExecutionPlan envelope (Wave O contract) from upstream inputs."""
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan

    return ExecutionPlan(
        plan_id=f"execute-{state.session_id or 'current'}",
        intent=state.intent,
        site_selection=state.site_selection,
        land_design_briefs=list(state.land_design_briefs or []),
    )


# ── Node implementations ─────────────────────────────────────────────


async def _route_tasks_node(state: ExecuteAgentState) -> dict:
    """Determine which execution sub-tasks to run based on intent.

    Layout is the core allocation task. Facility, axis, and road tasks are
    routed only when the typed or legacy intent declares corresponding targets.
    """
    import os

    tasks = ["layout"]
    defer_road = os.getenv("GIS_DEFER_ROAD", "").strip().lower() in {"1", "true", "yes"}
    intent = state.intent
    if intent is not None:
        if isinstance(intent, dict):
            projects = intent.get("project_targets")
            facilities = intent.get("facilities")
            development_axes = intent.get("development_axes")
            road_targets = intent.get("road_targets")
        else:
            projects = getattr(intent, "project_targets", None)
            facilities = getattr(intent, "facilities", None)
            development_axes = getattr(intent, "development_axes", None)
            road_targets = getattr(intent, "road_targets", None)
        if projects:
            tasks.append("project")
        if facilities:
            tasks.append("facility")
        if development_axes:
            tasks.append("axis")
        if road_targets and not defer_road:
            tasks.append("road")
        elif road_targets and defer_road:
            logger.warning("[EXECUTE] road task deferred by GIS_DEFER_ROAD")
    logger.info("[EXECUTE] tasks routed: %s", tasks)
    result = {"tasks_to_run": tasks}
    session_id = getattr(state, "session_id", "")
    if session_id and intent is not None:
        try:
            from rdflib import RDF
            from app.modules.kg.manager import get_kg_manager
            from app.modules.kg.ontology import EntityTypes

            kg = get_kg_manager().get_session_kg(session_id)
            if kg is None:
                return _execution_error(
                    state,
                    "route",
                    "missing_session_kg",
                    "Session KG is required before EXECUTE.",
                ) | result
            expected = {
                EntityTypes.ProjectTarget: len(getattr(intent, "project_targets", None) or []),
                EntityTypes.ZoneTarget: len(getattr(intent, "zone_targets", None) or []),
                EntityTypes.FacilityTarget: len(getattr(intent, "facilities", None) or []),
                EntityTypes.AxisTarget: len(getattr(intent, "development_axes", None) or []),
                EntityTypes.RoadTarget: len(getattr(intent, "road_targets", None) or []),
            }
            mismatches = []
            for entity_type, expected_count in expected.items():
                actual_count = len(set(kg.g.subjects(RDF.type, entity_type)))
                if actual_count != expected_count:
                    mismatches.append(
                        f"{entity_type.split('/')[-1]} state={expected_count} kg={actual_count}"
                    )
            if mismatches:
                return _execution_error(
                    state,
                    "route",
                    "kg_l3_intent_mismatch",
                    "L3 intent mismatch: " + "; ".join(mismatches),
                ) | result
        except Exception as e:
            return _execution_error(
                state,
                "route",
                "kg_l3_validation_failed",
                str(e),
            ) | result
    return result


async def _prepare_inputs_node(state: ExecuteAgentState) -> dict:
    """Prepare execution inputs: parcel_by_bsm + constraint adjustments + ExecutionPlan.

    This is the single compile-entry point: it builds the parcel index once and
    applies any constraint_adjustments to the zone targets (legacy retry-loop
    shape) so the workers consume consistent inputs.
    """
    parcel_by_bsm = _build_parcel_by_bsm(state)
    zone_targets = _intent_list(state.intent, "zone_targets")
    applied = _apply_constraint_adjustments(
        zone_targets, list(state.constraint_adjustments or [])
    )
    execution_plan = _assemble_execution_plan(state)
    return {
        "parcel_by_bsm": parcel_by_bsm,
        "constraint_adjustments": applied,
        "execution_plan": execution_plan,
    }


# ── Project worker ───────────────────────────────────────────────────


def _project_worker(state: ExecuteAgentState) -> WorkerResult:
    """Project worker: place each L3 project on the SSD-selected parcel.

    Consumes ``SiteSelectionDecision.selected_combination`` (ordered BSM list,
    paired with land design briefs) and runs ``design_project_footprint``
    (OBB split) for real project footprints. Returns a ``WorkerResult``; never
    mutates shared state.
    """
    from app.agent.execute.land_design_worker import design_project_footprint

    if not _task_enabled(state, "project"):
        return WorkerResult(worker_type="project")

    projects = list(getattr(state.intent, "project_targets", None) or [])
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    selected = list(getattr(state.site_selection, "selected_combination", None) or [])
    if not selected:
        logger.warning("[EXECUTE:project] SELECT not wired; project worker produces no output")
        return WorkerResult(
            worker_type="project",
            diagnostics=[{
                "code": "no_selection",
                "message": "SELECT not wired; no selected parcels for projects.",
            }],
        )

    projects_by_id = {
        getattr(project, "project_id", ""): project for project in projects
    }
    briefs = list(state.land_design_briefs or [])
    features = []
    changes: List[ParcelChange] = []
    for index, bsm in enumerate(selected):
        parcel = parcel_by_bsm.get(str(bsm))
        if parcel is None or not _parcel_geometry(parcel):
            continue
        project = None
        brief = briefs[index] if index < len(briefs) else None
        if brief is not None:
            project = projects_by_id.get(getattr(brief, "project_ref", ""))
        worker_brief = brief if project is not None else None
        change_list = design_project_footprint(project, worker_brief, str(bsm), parcel_by_bsm)
        if not change_list:
            continue
        changes.extend(change_list)
        primary = change_list[0]
        project_id = ""
        if project is not None:
            project_id = getattr(project, "project_id", "")
        elif brief is not None:
            project_id = getattr(brief, "project_ref", "")
        props = {
            "project_id": project_id,
            "project_name": getattr(project, "name", ""),
            "project_category": getattr(project, "category", "other"),
            "action": getattr(project, "action", "new"),
            "scale_text": getattr(project, "scale_text", ""),
            "source_bsm": str(bsm),
            "source_instruction_id": getattr(project, "source_instruction_id", ""),
            "source_report_key": getattr(project, "source_report_key", ""),
            "candidate_bsms": list(getattr(project, "candidate_bsms", None) or []),
            "constraint_check": "passed",
            "geometry_source": "land_design_worker",
            "change_action": primary.action,
        }
        if brief is not None:
            props["project_ref"] = getattr(brief, "project_ref", "")
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": _footprint_geometry(primary, _parcel_geometry(parcel)),
        })

    layers = []
    if features:
        layers.append({
            "layerType": "planned_project",
            "layerName": "规划项目",
            "data": {"type": "FeatureCollection", "features": features},
        })
    unresolved = []
    if not features:
        unresolved.append({
            "code": "project_output_empty",
            "message": "Project targets exist but none could be placed on a constraint-safe candidate parcel.",
        })
    return WorkerResult(
        worker_type="project",
        layers=layers,
        parcel_changes=changes,
        unresolved_items=unresolved,
        diagnostics=[{"code": "project_ok", "projects_placed": len(features), "changes": len(changes)}],
    )


async def _project_worker_node(state: ExecuteAgentState) -> dict:
    result = _project_worker(state)
    return {"worker_results": [result]}


# ── Zone worker ──────────────────────────────────────────────────────


def _resolve_zone_allocator(state: ExecuteAgentState) -> Any:
    """ZoneAllocatorPort from injected ports, else the default PuLP adapter."""
    ports = getattr(state, "ports", None)
    allocator = getattr(ports, "zone_allocator", None) if ports is not None else None
    if allocator is None:
        from app.agent.execute.zone_allocator_adapter import PuLPZoneAllocator

        allocator = PuLPZoneAllocator()
    return allocator


def _zone_target_key(zone_target: Any) -> str:
    return str(
        getattr(zone_target, "zone_id", None)
        or getattr(zone_target, "land_use", None)
        or ""
    )


def _allocate_empty_zone_targets(
    state: ExecuteAgentState,
    empty_targets: List[Any],
    parcel_by_bsm: Dict[str, Any],
    zone_changes: List[ParcelChange],
    diagnostics: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """MIP-allocate parcels for zone targets with no candidate_bsms.

    The unclaimed parcel pool (parcels not claimed by any non-empty zone target)
    is passed as the candidate set. Infeasible allocations are surfaced as
    ``design_unresolved`` diagnostics - never silently skipped.
    """
    unresolved: List[Dict[str, Any]] = []
    if not empty_targets:
        return unresolved

    claimed: set = set()
    for zone_target in _intent_list(state.intent, "zone_targets"):
        for bsm in getattr(zone_target, "candidate_bsms", None) or []:
            claimed.add(str(bsm))
    pool = [bsm for bsm in parcel_by_bsm if str(bsm) not in claimed]

    targets: Dict[str, float] = {}
    candidates: Dict[str, List[str]] = {}
    metadata: Dict[str, Any] = {"parcel_by_bsm": parcel_by_bsm}
    for zone_target in empty_targets:
        key = _zone_target_key(zone_target)
        if not key:
            continue
        targets[key] = float(getattr(zone_target, "area_ha", None) or 0.0)
        candidates[key] = list(pool)
        metadata[key] = {"land_use": getattr(zone_target, "land_use", "") or ""}

    if not targets:
        return unresolved

    allocator = _resolve_zone_allocator(state)
    try:
        solution = allocator.allocate(targets, candidates, constraints=None, metadata=metadata)
    except Exception as e:  # pragma: no cover - defensive
        for zone_target in empty_targets:
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_error",
                "target": _zone_target_key(zone_target),
                "message": str(e),
            })
        return unresolved

    if not getattr(solution, "feasible", False):
        for zone_target in empty_targets:
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_infeasible",
                "target": _zone_target_key(zone_target),
                "diagnostics": list(getattr(solution, "diagnostics", None) or []),
            })
        return unresolved

    from app.agent.execute.land_design_worker import design_zone_parcel

    for zone_target in empty_targets:
        key = _zone_target_key(zone_target)
        assigned_bsms = [
            entry.bsm
            for entry in getattr(solution, "assignments", None) or []
            if entry.zone_id == key
        ]
        if not assigned_bsms:
            unresolved.append({
                "code": "design_unresolved",
                "kind": "zone_allocation_empty",
                "target": key,
                "message": "Allocator returned no assignments for zone.",
            })
            continue
        allocated_target = zone_target.model_copy(update={"candidate_bsms": assigned_bsms})
        zone_changes.extend(design_zone_parcel(allocated_target, parcel_by_bsm))
        diagnostics.append({
            "code": "zone_allocated",
            "target": key,
            "assigned": len(assigned_bsms),
        })
    return unresolved


def _zone_worker(state: ExecuteAgentState) -> WorkerResult:
    """Zone worker: deterministic zone reclassification + MIP allocation.

    Reclassifies each zone target's candidate parcels to the zone's planning
    land use via the Land Design Worker. Zone targets with empty
    ``candidate_bsms`` are solved through the ``ZoneAllocatorPort`` (PuLP MIP);
    infeasible allocations become ``design_unresolved`` diagnostics.
    """
    from app.agent.execute.land_design_worker import design_zone_parcel

    if not _task_enabled(state, "layout"):
        return WorkerResult(worker_type="zone")

    landuse = _build_landuse_geojson(state)
    zone_targets = _intent_list(state.intent, "zone_targets")
    custom_targets = _intent_list(state.intent, "custom_zone_targets")
    parcel_by_bsm = _resolve_parcel_by_bsm(state)

    diagnostics: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []

    if not zone_targets and not custom_targets:
        message = "No explicit planning zone targets were derived from the reports."
        logger.error("[EXECUTE:zone] %s", message)
        unresolved.append({"code": "missing_zone_targets", "message": message})
        return WorkerResult(
            worker_type="zone", unresolved_items=unresolved, diagnostics=diagnostics
        )

    zone_changes: List[ParcelChange] = []
    empty_targets = []
    for zone_target in zone_targets:
        if not getattr(zone_target, "candidate_bsms", None):
            empty_targets.append(zone_target)
            continue
        zone_changes.extend(design_zone_parcel(zone_target, parcel_by_bsm))

    unresolved.extend(
        _allocate_empty_zone_targets(
            state, empty_targets, parcel_by_bsm, zone_changes, diagnostics
        )
    )

    layers = []
    func_layer = _function_zone_layer(zone_changes)
    if func_layer:
        layers.append(func_layer)

    if custom_targets:
        try:
            custom_layer = _build_custom_planning_layer(state, landuse, custom_targets)
            if custom_layer:
                layers.append(custom_layer)
                diagnostics.append({
                    "code": "custom_zone_built",
                    "features": len((custom_layer.get("data") or {}).get("features") or []),
                })
        except Exception as e:
            logger.error("[EXECUTE:zone] custom zoning failed: %s", e, exc_info=True)
            diagnostics.append({"code": "custom_zoning_failed", "message": str(e)})

    return WorkerResult(
        worker_type="zone",
        layers=layers,
        parcel_changes=zone_changes,
        unresolved_items=unresolved,
        diagnostics=diagnostics,
    )


async def _zone_worker_node(state: ExecuteAgentState) -> dict:
    if not _task_enabled(state, "layout"):
        return {}
    result = _zone_worker(state)
    update: Dict[str, Any] = {"worker_results": [result]}
    if any(item.get("code") == "missing_zone_targets" for item in result.unresolved_items):
        update["execution_errors"] = _execution_error(
            state, "layout", "missing_zone_targets",
            "No explicit planning zone targets were derived from the reports.",
        )["execution_errors"]
    landuse = _build_landuse_geojson(state)
    if landuse.get("features"):
        zone_changes = list(result.parcel_changes)
        update["allocated_geojson"] = _allocated_geojson_from_changes(landuse, zone_changes)
        update["allocation_summary"] = {
            "mode": "deterministic",
            "allocated_count": len(zone_changes),
            "zone_target_count": len(_intent_list(state.intent, "zone_targets")),
            "adjustments_applied": len(list(state.constraint_adjustments or [])),
            "custom_zone_count": sum(
                1 for layer in result.layers
                if (layer.get("layerType") or layer.get("layer_type")) == "custom_planning_zone"
            ),
        }
    return update


# ── Facility worker ──────────────────────────────────────────────────


def _facility_worker(state: ExecuteAgentState) -> WorkerResult:
    """Facility worker: decision-driven facility footprint placement.

    Builds a Polygon footprint for each FacilityTarget anchor via the Land
    Design Worker. Passes the real ``parcel_by_bsm`` so the containing-parcel
    branch of ``design_facility_parcel`` activates when an anchor sits inside
    an existing parcel. No KG POI lookup, no FacilityPlacer.
    """
    from app.agent.execute.land_design_worker import design_facility_parcel
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    if not _task_enabled(state, "facility"):
        return WorkerResult(worker_type="facility")

    facilities = list(getattr(state.intent, "facilities", None) or [])
    parcel_by_bsm = _resolve_parcel_by_bsm(state)
    features = []
    changes: List[ParcelChange] = []
    for facility in facilities:
        change = design_facility_parcel(facility, parcel_by_bsm, None)
        if change is None:
            logger.warning(
                "[EXECUTE:facility] skipped %s (no anchor_point)",
                getattr(facility, "type", ""),
            )
            continue
        changes.append(change)
        geometry = {}
        after_wkt = getattr(change, "after_geometry_wkt", "") or ""
        if after_wkt:
            try:
                geom = wkt.loads(after_wkt)
                if not geom.is_empty:
                    geometry = geometry_mapping(geom)
            except Exception:
                geometry = {}
        features.append({
            "type": "Feature",
            "properties": {
                "facility_id": change.bsm,
                "facility_type": getattr(facility, "type", ""),
                "status": "planned_new",
                "source_bsm": change.bsm,
                "change_action": change.action,
            },
            "geometry": geometry,
        })

    layers = []
    if features:
        layers.append({
            "layerType": "facility_point",
            "layerName": "公共服务设施",
            "data": {"type": "FeatureCollection", "features": features},
        })
    unresolved = []
    if not features:
        unresolved.append({
            "code": "facility_output_empty",
            "message": "Facility targets exist but no facility layer was produced.",
        })
    return WorkerResult(
        worker_type="facility",
        layers=layers,
        parcel_changes=changes,
        unresolved_items=unresolved,
        diagnostics=[{"code": "facility_ok", "placed": len(features)}],
    )


async def _facility_worker_node(state: ExecuteAgentState) -> dict:
    try:
        result = _facility_worker(state)
        return {"worker_results": [result]}
    except Exception as e:
        logger.error("[EXECUTE:facility] failed: %s", e, exc_info=True)
        return _execution_error(state, "facility", "facility_failed", str(e))


# ── Axis worker ──────────────────────────────────────────────────────


def _axis_worker(state: ExecuteAgentState) -> WorkerResult:
    """Axis worker: development-axis layer (decision-driven from intent)."""
    from types import SimpleNamespace

    from app.tools.gis._generation.axis_builder import AxisBuilder

    if not _task_enabled(state, "axis"):
        return WorkerResult(worker_type="axis")

    gis_data = state.gis_data or {}
    axes = _intent_list(state.intent, "development_axes") or _intent_list(state.intent, "axes")
    if not axes:
        return WorkerResult(
            worker_type="axis",
            unresolved_items=[{
                "code": "axis_output_empty",
                "message": "Axis targets exist but no development-axis layer was produced.",
            }],
        )

    layers = []
    unresolved = []
    try:
        axis_layer = AxisBuilder().build(
            intent=SimpleNamespace(axes=axes, metadata={}),
            boundary_geojson=gis_data.get("boundary_geojson"),
            landuse_current_geojson=gis_data.get("landuse_current_geojson"),
        )
        if axis_layer and axis_layer.get("features"):
            layers.append({"layerType": "infrastructure", "data": axis_layer})
        else:
            unresolved.append({
                "code": "axis_output_empty",
                "message": "Axis targets exist but no development-axis layer was produced.",
            })
    except Exception as e:
        logger.error("[EXECUTE:axis] failed: %s", e, exc_info=True)
        unresolved.append({"code": "axis_failed", "message": str(e)})

    return WorkerResult(
        worker_type="axis",
        layers=layers,
        unresolved_items=unresolved,
        diagnostics=[{"code": "axis_ok", "layers": len(layers)}],
    )


async def _axis_worker_node(state: ExecuteAgentState) -> dict:
    result = _axis_worker(state)
    return {"worker_results": [result]}


# ── Road worker ──────────────────────────────────────────────────────


def _road_worker(state: ExecuteAgentState) -> WorkerResult:
    """Road worker: planned road network generation.

    Primary path: the injected ``RoadPlannerPort`` when available; otherwise the
    remote Stage 0-6 generator (confirmation gates 2.6/3/4, ported from
    origin/agent/kg-schema-gis-handoff-20260730), falling back to the
    lightweight local ``plan_roads``. If declared road targets still produce no
    geometry, the worker records an unresolved item (formal output is gated by
    the outer VALIDATE).
    """
    if not _task_enabled(state, "road"):
        return WorkerResult(worker_type="road")

    intent = state.intent
    road_targets = _intent_list(intent, "road_targets")

    ports = getattr(state, "ports", None)
    planner = getattr(ports, "road_planner", None) if ports is not None else None
    if planner is not None:
        try:
            if planner.is_available():
                plan_result = planner.plan(state)
                return WorkerResult(
                    worker_type="road",
                    layers=list(getattr(plan_result, "layers", None) or []),
                    unresolved_items=list(getattr(plan_result, "unresolved_items", None) or []),
                    diagnostics=[{"code": "road_planner_port", "available": True}],
                )
        except Exception as e:
            logger.warning("[EXECUTE:road] planner port failed: %s", e)

    diagnostic_layers: List[Dict[str, Any]] = []
    try:
        from app.agent.execute.road_generator import (
            execute_road_planning_from_agent_state,
        )

        result = execute_road_planning_from_agent_state(state)
        layers = result.get("layout_layers") or []
        diagnostic_layers = list(layers)
        formal_road_layers = [
            layer
            for layer in layers
            if (layer.get("layerType") or layer.get("layer_type"))
            in {"planned_road", "planned_road_candidates"}
            and ((layer.get("data") or {}).get("features") or layer.get("features"))
        ]
        if formal_road_layers:
            for layer in formal_road_layers:
                data = layer.get("data")
                if isinstance(data, dict):
                    data.pop("crs", None)
                layer.pop("crs", None)
            logger.info(
                "[EXECUTE:road] stage generator: ran=%s targets=%d layers=%d",
                result.get("ran"), result.get("road_target_count", 0), len(layers),
            )
            return WorkerResult(
                worker_type="road",
                layers=list(layers),
                diagnostics=[{"code": "road_stage_generator", "ran": bool(result.get("ran"))}],
            )
        logger.info("[EXECUTE:road] stage generator skipped: %s", result.get("reason"))
    except Exception as e:
        logger.warning(
            "[EXECUTE:road] stage generator failed, falling back to local plan_roads: %s", e
        )

    try:
        from app.modules.spatial_ops.road_planner import plan_roads
    except ImportError:  # pragma: no cover - fallback module removed
        logger.warning("[EXECUTE:road] local plan_roads unavailable; road worker unresolved")
        return WorkerResult(
            worker_type="road",
            unresolved_items=[{
                "code": "road_failed",
                "message": "Local plan_roads fallback is unavailable.",
            }],
        )

    try:
        if not intent or not road_targets:
            logger.info("[EXECUTE:road] no road targets in intent, skipping")
            return WorkerResult(worker_type="road")

        bundle = state.gis_bundle
        current_roads = []
        if bundle is not None:
            roads = bundle.lines.get("roads_current") if bundle.lines is not None else None
            if roads is not None:
                current_roads = list(roads)
            if not current_roads:
                current_roads = getattr(bundle, "roads", [])

        planned_roads = plan_roads(
            road_targets=road_targets,
            current_roads=current_roads,
        )
    except Exception as e:
        logger.warning("[EXECUTE:road] failed: %s", e)
        return WorkerResult(
            worker_type="road",
            unresolved_items=[{"code": "road_failed", "message": str(e)}],
        )

    if not planned_roads:
        logger.info("[EXECUTE:road] no roads generated")
        return WorkerResult(
            worker_type="road",
            unresolved_items=[{
                "code": "road_output_empty",
                "message": "Road targets exist but no planned road was produced.",
            }],
        )

    for road in planned_roads:
        geometry = road.get("geometry")
        if isinstance(geometry, str):
            try:
                road["geometry"] = json.loads(geometry)
            except json.JSONDecodeError:
                road["geometry"] = None

    road_layer = {
        "layer_type": "planned_road",
        "features": planned_roads,
        "count": len(planned_roads),
    }
    return WorkerResult(
        worker_type="road",
        layers=[road_layer] + diagnostic_layers,
        diagnostics=[{
            "code": "road_plan_ok",
            "count": len(planned_roads),
            "upgrade": sum(1 for r in planned_roads if r.get("operation") == "upgrade"),
            "create": sum(1 for r in planned_roads if r.get("operation") == "create"),
            "preserve": sum(1 for r in planned_roads if r.get("operation") == "preserve"),
        }],
    )


async def _road_worker_node(state: ExecuteAgentState) -> dict:
    result = _road_worker(state)
    return {"worker_results": [result]}


# ── Merge / materialize / planned-state / review ─────────────────────


async def _merge_worker_results_node(state: ExecuteAgentState) -> dict:
    """Merge all WorkerResults into a unified ParcelChangeSet + layout_configs."""
    from app.agent.execute.merge import merge_worker_results

    changeset, layout_configs, diagnostics = merge_worker_results(
        list(state.worker_results)
    )
    update: Dict[str, Any] = {
        "parcel_changeset": changeset,
        "layout_configs": layout_configs,
        "worker_conflict_diagnostics": diagnostics,
    }
    if changeset is not None:
        update["parcel_changes"] = list(changeset.changes)

    unresolved = []
    for result in state.worker_results:
        unresolved.extend(_worker_result_get(result, "unresolved_items") or [])
    if unresolved:
        update["unresolved_targets"] = (
            list(state.unresolved_targets or []) + unresolved
        )
    return update


async def _geometry_materialize_node(state: ExecuteAgentState) -> dict:
    """Confirm the already-determined geometry operations (no site selection).

    Lightweight confirmation: the design phase produced the ParcelChanges; this
    node only validates that geometry-mutating changes carry a usable
    ``after_geometry_wkt`` so the later checks can trust the changeset.
    """
    changeset = state.parcel_changeset
    diagnostics: List[Dict[str, Any]] = []
    geometry_valid = True
    checked = 0
    for change in (changeset.changes if changeset is not None else []):
        checked += 1
        if change.action in {"create", "split", "merge"} and not (
            getattr(change, "after_geometry_wkt", "") or ""
        ):
            geometry_valid = False
            diagnostics.append({
                "code": "missing_after_geometry",
                "bsm": getattr(change, "bsm", ""),
                "action": change.action,
            })
    report = {
        "geometry_valid": geometry_valid,
        "checked_changes": checked,
        "diagnostics": diagnostics,
    }
    return {"geometry_materialize_report": report}


async def _planned_state_builder_node(state: ExecuteAgentState) -> dict:
    """Produce the authoritative PlannedState from the merged ParcelChangeSet."""
    from app.agent.execute.planned_state_builder import changeset_to_planned_state

    if state.parcel_changeset is None:
        return {}
    planned_state = changeset_to_planned_state(state.parcel_changeset, state.intent)
    return {"planned_state": planned_state}


# Task name -> worker_type produced for it (used by execution review).
_TASK_WORKER_TYPE: Dict[str, str] = {
    "layout": "zone",
    "project": "project",
    "facility": "facility",
    "axis": "axis",
    "road": "road",
}


async def _execution_review_node(state: ExecuteAgentState) -> dict:
    """Execution review: execution-checks only (no full VALIDATE aggregate).

    Checks: input completeness / worker-output completeness / change lineage /
    geometry validity / worker conflicts. Produces ``execution_review_report``
    diagnostics and ``validation_result`` for the outer post-L3 VALIDATE stage.
    """
    checks: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []

    input_ok = bool(state.parcel_by_bsm)
    if not input_ok:
        violations.append({
            "check": "missing_parcel_input",
            "message": "No parcel_by_bsm prepared (landuse input missing).",
        })
    checks.append({"check": "input_completeness", "passed": input_ok})

    routed = set(state.tasks_to_run or [])
    expected_worker_types = {_TASK_WORKER_TYPE.get(task, task) for task in routed}
    worker_types = {_worker_type(result) for result in state.worker_results}
    missing = sorted(expected_worker_types - worker_types)
    workers_ok = not missing
    for worker_type in missing:
        violations.append({
            "check": "missing_worker_output",
            "worker_type": worker_type,
            "message": f"No result produced for routed worker: {worker_type}",
        })
    checks.append({"check": "worker_output_completeness", "passed": workers_ok, "missing": missing})

    lineage_ok = True
    for change in (state.parcel_changeset.changes if state.parcel_changeset is not None else []):
        # Created parcels (e.g. facility buffers) legitimately have no source
        # parcel; lineage is required only for transformations of existing parcels.
        if getattr(change, "action", "") == "create":
            continue
        if not (getattr(change, "derived_from_bsms", None) or []):
            lineage_ok = False
            violations.append({
                "check": "missing_lineage",
                "bsm": getattr(change, "bsm", ""),
                "message": "Change has no derived_from_bsms.",
            })
    checks.append({"check": "change_lineage", "passed": lineage_ok})

    geom_report = state.geometry_materialize_report or {}
    geometry_ok = bool(geom_report.get("geometry_valid", True))
    if not geometry_ok:
        for diag in geom_report.get("diagnostics") or []:
            violations.append({
                "check": diag.get("code", "geometry_invalid"),
                "message": diag.get("message") or f"geometry invalid on {diag.get('bsm')}",
            })
    checks.append({"check": "geometry_validity", "passed": geometry_ok})

    conflicts = list(state.worker_conflict_diagnostics or [])
    conflicts_ok = not conflicts
    for conflict in conflicts:
        violations.append({
            "check": "worker_conflict",
            "message": f"BSM conflict on {conflict.get('bsm')}: {conflict.get('workers')}",
        })
    checks.append({"check": "worker_conflicts", "passed": conflicts_ok, "conflicts": len(conflicts)})

    for issue in state.execution_errors or []:
        violations.append({
            "check": issue.get("code", "execution_error"),
            "message": issue.get("message", "Execution failed"),
        })
    checks.append({"check": "execution_errors", "passed": not state.execution_errors})

    passed = all(check.get("passed", False) for check in checks)
    report = {"passed": passed, "checks": checks, "violations": violations}
    validation_result = {
        "passed": passed,
        "status": "pass" if passed else "fail",
        "violations": violations,
        "reason": "" if passed else "execution_review_failed",
    }
    logger.info(
        "[EXECUTE:review] round %d: %s (%d violations)",
        state.validation_round + 1, "PASS" if passed else "FAIL", len(violations),
    )
    return {
        "execution_review_report": report,
        "validation_result": validation_result,
        "validation_round": state.validation_round + 1,
    }


# ── Conditional routing ──────────────────────────────────────────────


def _route_after_execution_review(
    state: ExecuteAgentState,
) -> Literal["pass", "retry", "human"]:
    """Route after execution review: pass -> END, fail -> retry (max 3 rounds -> human)."""
    result = state.validation_result or {}
    if result.get("passed", False):
        return "pass"
    if state.validation_round >= 3:
        logger.warning(
            "[EXECUTE] execution review exceeded %d rounds - routing to human review",
            state.validation_round,
        )
        return "human"
    return "retry"


# ── L4 Write-back ────────────────────────────────────────────────────


async def _write_l4_node(state: ExecuteAgentState) -> dict:
    """Write L4 planned entities (PlannedParcel, PlannedZone, PlannedFacility, etc.) to KG.

    Consumes the ParcelChangeSet (or the already-built PlannedState). Called
    after execute completes to persist the planned layout back to KG.
    """
    if (state.validation_result or {}).get("partial_usable"):
        logger.warning("[EXECUTE:l4_write] Skipped for partial result; road stage is deferred")
        return {}
    if not (state.validation_result or {}).get("passed", False):
        logger.error("[EXECUTE:l4_write] Skipped because validation did not pass")
        return {}

    session_id = getattr(state, "session_id", "")
    if not session_id:
        logger.warning("[EXECUTE:l4_write] No session_id - skipping L4 write")
        return {}

    try:
        from app.modules.kg.manager import get_kg_manager
        manager = get_kg_manager()
        kg = manager.get_session_kg(session_id)
        if kg is None:
            logger.warning("[EXECUTE:l4_write] No KG for session %s", session_id)
            return {}
    except Exception as e:
        logger.warning("[EXECUTE:l4_write] KG access failed: %s", e)
        return {}

    from app.modules.kg.builder.layer4 import apply_planned_state

    planned_state = None
    if getattr(state, "parcel_changeset", None) is not None:
        from app.agent.execute.planned_state_builder import changeset_to_planned_state

        planned_state = changeset_to_planned_state(state.parcel_changeset, state.intent)
        logger.info(
            "[EXECUTE:l4_write] building PlannedState from ParcelChangeSet (%d changes)",
            len(state.parcel_changeset.changes),
        )
    elif getattr(state, "planned_state", None) is not None:
        planned_state = state.planned_state

    if planned_state is None:
        logger.warning("[EXECUTE:l4_write] no parcel_changeset/planned_state; skipping L4 write")
        return {}

    written = sum(
        len(items)
        for items in (
            planned_state.parcels,
            planned_state.zones,
            planned_state.facilities,
            planned_state.roads,
            planned_state.axes,
        )
    )
    if written:
        apply_planned_state(kg, planned_state)
        manager.bump_version(session_id)
        logger.info("[EXECUTE:l4_write] Wrote %d L4 entities to KG", written)

    return {}


# ── Graph builder ────────────────────────────────────────────────────


def build_execute_agent_graph():
    """Build the EXECUTE Agent StateGraph.

    Wave O multi-worker subgraph:
        route_tasks -> prepare_inputs -> project_worker -> zone_worker
          -> [facility_worker || axis_worker]  (parallel fan-out diamond)
          -> road_worker -> merge_worker_results -> geometry_materialize
          -> planned_state_builder -> execution_review
    Execution-review retry loop on failure (max 3 rounds -> human review).

    Parallel implementation: a static fan-out diamond - ``zone_worker`` edges
    to both ``facility_worker`` and ``axis_worker`` (LangGraph runs them
    concurrently), which fan back in at ``road_worker``. ``worker_results`` uses
    an upsert reducer so concurrent writes and retry re-runs merge correctly.
    """
    graph = StateGraph(ExecuteAgentState)

    graph.add_node("route_tasks", _checkpoint_safe_node(_route_tasks_node))
    graph.add_node("prepare_inputs", _checkpoint_safe_node(_prepare_inputs_node))
    graph.add_node("project_worker", _checkpoint_safe_node(_project_worker_node))
    graph.add_node("zone_worker", _checkpoint_safe_node(_zone_worker_node))
    graph.add_node("facility_worker", _checkpoint_safe_node(_facility_worker_node))
    graph.add_node("axis_worker", _checkpoint_safe_node(_axis_worker_node))
    graph.add_node("road_worker", _checkpoint_safe_node(_road_worker_node))
    graph.add_node("merge_worker_results", _checkpoint_safe_node(_merge_worker_results_node))
    graph.add_node("geometry_materialize", _checkpoint_safe_node(_geometry_materialize_node))
    graph.add_node("planned_state_builder", _checkpoint_safe_node(_planned_state_builder_node))
    graph.add_node("execution_review", _checkpoint_safe_node(_execution_review_node))

    graph.add_edge(START, "route_tasks")
    graph.add_edge("route_tasks", "prepare_inputs")
    graph.add_edge("prepare_inputs", "project_worker")
    graph.add_edge("project_worker", "zone_worker")
    # Parallel fan-out: zone_worker -> [facility_worker || axis_worker]
    graph.add_edge("zone_worker", "facility_worker")
    graph.add_edge("zone_worker", "axis_worker")
    # Fan-in: both workers join at road_worker
    graph.add_edge("facility_worker", "road_worker")
    graph.add_edge("axis_worker", "road_worker")
    graph.add_edge("road_worker", "merge_worker_results")
    graph.add_edge("merge_worker_results", "geometry_materialize")
    graph.add_edge("geometry_materialize", "planned_state_builder")
    graph.add_edge("planned_state_builder", "execution_review")

    graph.add_conditional_edges(
        "execution_review",
        _route_after_execution_review,
        {"retry": "zone_worker", "pass": END, "human": END},
    )

    compiled = graph.compile()
    logger.info(
        "[EXECUTE] Agent graph compiled: 11 nodes (multi-worker subgraph), 1 conditional edge"
    )
    return compiled


# ── Legacy layer helpers (kept for zone/allocated layer construction) ─


def _function_zone_layer(zone_changes: list) -> dict | None:
    """Build the function_zone layer from reclassified ParcelChange entries."""
    from shapely import wkt
    from shapely.geometry import mapping as geometry_mapping

    features = []
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        geometry = {}
        after_wkt = getattr(change, "after_geometry_wkt", "") or ""
        if after_wkt:
            try:
                geom = wkt.loads(after_wkt)
                if not geom.is_empty:
                    geometry = geometry_mapping(geom)
            except Exception:
                geometry = {}
        if not geometry:
            continue
        cls = getattr(change, "after_classification", None)
        bsm = str(getattr(change, "bsm", ""))
        features.append({
            "type": "Feature",
            "properties": {
                "bsm": bsm,
                "planning_land_use": str(getattr(cls, "code", "") or ""),
                "zone_type": str(getattr(cls, "canonical_name", "") or ""),
                "action": getattr(change, "action", ""),
                "source_bsm": bsm,
                "area_ha": round(float(getattr(change, "new_area_ha", 0) or 0), 2),
            },
            "geometry": geometry,
        })
    if not features:
        return None
    return {
        "layerType": "function_zone",
        "layerName": "功能分区",
        "data": {"type": "FeatureCollection", "features": features},
    }


def _allocated_geojson_from_changes(landuse: dict, zone_changes: list) -> dict:
    """landuse features with reclassified parcels tagged with their planning land use."""
    assigned = {}
    for change in zone_changes:
        if getattr(change, "action", "") != "reclassify":
            continue
        cls = getattr(change, "after_classification", None)
        assigned[str(getattr(change, "bsm", ""))] = {
            "planning_land_use": str(getattr(cls, "code", "") or ""),
            "zone_type": str(getattr(cls, "canonical_name", "") or ""),
        }
    features = []
    for feature in landuse.get("features") or []:
        props = dict(feature.get("properties") or {})
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        if bsm in assigned:
            props["planning_land_use"] = assigned[bsm]["planning_land_use"]
            props["zone_type"] = assigned[bsm]["zone_type"]
        new_feature = dict(feature)
        new_feature["properties"] = props
        features.append(new_feature)
    return {"type": "FeatureCollection", "features": features}


def _assign_custom_zone_features(landuse: dict, candidates: dict, pending_zone_name: str) -> dict:
    """Tag every landuse feature with its custom zone (pending for unclaimed parcels)."""
    bsm_to_zone = {}
    for zone_name, bsms in (candidates or {}).items():
        for bsm in bsms:
            bsm_to_zone[str(bsm)] = zone_name
    features = []
    for feature in landuse.get("features") or []:
        props = dict(feature.get("properties") or {})
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        props["assigned_zone"] = bsm_to_zone.get(bsm, pending_zone_name)
        new_feature = dict(feature)
        new_feature["properties"] = props
        features.append(new_feature)
    return {"type": "FeatureCollection", "features": features}


def _build_custom_planning_layer(
    state: ExecuteAgentState,
    landuse: dict,
    custom_targets: list,
) -> dict | None:
    """Build the custom_planning_zone layer via the vocabulary-driven generator (no MIP)."""
    from app.modules.spatial_ops.custom_planning import (
        PENDING_ZONE_NAME,
        build_custom_planning_zone_layer,
        build_custom_zone_allocation_inputs,
    )
    from app.tools.gis._generation.custom_zone_generator import CustomZoningGenerator
    from shapely.geometry import shape

    gis_bundle = getattr(state, "gis_bundle", None)
    parcels = [
        {
            "bsm": str(f.get("properties", {}).get("BSM", "") or f.get("properties", {}).get("bsm", "")),
            "dlbm": str(f.get("properties", {}).get("DLBM", "") or f.get("properties", {}).get("dlbm", "")),
            "area_ha": float(f.get("properties", {}).get("area_sqm", 0) or 0) / 10000.0,
            "geometry": shape(f["geometry"]) if f.get("geometry") else None,
        }
        for f in (landuse.get("features") or [])
    ]
    parcels = [p for p in parcels if p["bsm"] and p["geometry"] is not None]

    try:
        from app.agent.execute.vocab_context import build_parcel_contexts

        ctxs = build_parcel_contexts(parcels, gis_bundle)
        for p in parcels:
            p.update(ctxs.get(str(p["bsm"]), {}))
    except Exception as e:
        logger.warning("[EXECUTE:layout] parcel context build failed: %s", e)

    three_lines = {}
    if gis_bundle is not None:
        for bundle_key, subtype in (
            ("ecological_redline", "ecological_redline"),
            ("farmland_protection", "farmland_redline"),
        ):
            geoms = [
                getattr(f, "geometry", None)
                for f in (gis_bundle.polygons.get(bundle_key) or [])
            ]
            three_lines[subtype] = [{"geometry": shape(g)} for g in geoms if g]
    for gis_key, subtype in (
        ("ecological_protection_geojson", "ecological_redline"),
        ("farmland_protection_geojson", "farmland_redline"),
    ):
        if three_lines.get(subtype):
            continue
        source = (state.gis_data or {}).get(gis_key) or {}
        three_lines[subtype] = [
            {"geometry": shape(feature["geometry"])}
            for feature in source.get("features") or []
            if feature.get("geometry")
        ]

    intent_dict = (
        state.intent.model_dump(exclude_none=True)
        if hasattr(state.intent, "model_dump")
        else dict(state.intent or {})
    )
    if intent_dict.get("custom_zone_targets") and not intent_dict.get("vocabulary_name"):
        intent_dict["vocabulary_name"] = intent_dict["custom_zone_targets"][0].get("vocabulary_name", "")
    if not intent_dict.get("vocabulary_name"):
        logger.warning("[EXECUTE:layout] custom targets present but no vocabulary_name - skipping custom layer")
        return None

    gen = CustomZoningGenerator(parcels, intent_dict, three_lines=three_lines)
    zones, _audit = gen.generate_with_validation()
    if not zones:
        return None
    _targets, candidates, metadata = build_custom_zone_allocation_inputs(landuse, zones)
    custom_allocated = _assign_custom_zone_features(landuse, candidates, PENDING_ZONE_NAME)
    custom_layer = build_custom_planning_zone_layer(custom_allocated, metadata)
    if not custom_layer.get("features"):
        return None
    return {
        "layerType": "custom_planning_zone",
        "layerName": "自定义规划分区",
        "data": custom_layer,
    }


def _adjustment_get(adjustment: Any, key: str, default: Any = None) -> Any:
    """Read a field from a legacy adjustment dict or an attribute-carrying object."""
    if isinstance(adjustment, dict):
        return adjustment.get(key, default)
    value = getattr(adjustment, key, None)
    return default if value is None else value


def _apply_constraint_adjustments(zone_targets: list, adjustments: list) -> list:
    """Apply constraint_adjustments (legacy {zone, delta_ha} shape) to zone targets.

    Matches each adjustment to a zone target by land_use / planning_zone /
    zone_id and shifts its area_ha target by delta_ha (positive or negative).
    Unmatched zones are skipped safely. Returns the applied adjustments.
    """
    applied: List[dict] = []
    if not adjustments:
        return applied
    target_by_zone: Dict[str, Any] = {}
    for target in zone_targets:
        for key in (
            getattr(target, "land_use", None),
            getattr(target, "planning_zone", None),
            getattr(target, "zone_id", None),
        ):
            if key:
                target_by_zone.setdefault(str(key), target)
    for adjustment in adjustments or []:
        zone = _adjustment_get(adjustment, "zone", "")
        if not zone:
            continue
        target = target_by_zone.get(str(zone))
        if target is None:
            continue
        delta_ha = _adjustment_get(adjustment, "delta_ha", 0.0) or 0.0
        try:
            delta_ha = float(delta_ha)
        except (TypeError, ValueError):
            delta_ha = 0.0
        current = getattr(target, "area_ha", None)
        setattr(target, "area_ha", (float(current) if current is not None else 0.0) + delta_ha)
        applied.append(adjustment)
    return applied


__all__ = ["build_execute_agent_graph"]
