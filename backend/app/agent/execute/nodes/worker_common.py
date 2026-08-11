"""Shared helpers for the EXECUTE worker nodes (parcel adaptation, task routing)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.agent.execute.execute_state import ExecuteAgentState


WORKER_ROUTE_KEYS = {
    "project_footprint": "project",
    "parcel_transformation": "layout",
    "facility_placement": "facility",
    "axis_construction": "axis",
    "road_construction": "road",
    "non_spatial_action": "action",
}

WORKER_RESULT_KEYS = {
    "project_footprint": "project",
    "parcel_transformation": "zone",
    "facility_placement": "facility",
    "axis_construction": "axis",
    "road_construction": "road",
    "non_spatial_action": "action",
}


def _worker_type_value(worker_type: Any) -> str:
    return str(getattr(worker_type, "value", worker_type))


def worker_route_key(worker_type: Any) -> str:
    """Canonical EXECUTE route key for a WorkerType or its serialized value."""
    return WORKER_ROUTE_KEYS.get(_worker_type_value(worker_type), "")


def worker_result_key(worker_type: Any) -> str:
    """Canonical WorkerResult label for a WorkerType or serialized value."""
    return WORKER_RESULT_KEYS.get(_worker_type_value(worker_type), "")


def _task_value(task: Any, name: str, default: Any = None) -> Any:
    return task.get(name, default) if isinstance(task, dict) else getattr(task, name, default)


def _plan_tasks(state: ExecuteAgentState, worker_types: Iterable[str] | None = None) -> list[Any]:
    """Read dispatchable tasks only from the authoritative ExecutionPlan."""
    plan = state.execution_plan
    tasks = list(_task_value(plan, "worker_tasks", []) or []) if plan is not None else []
    if worker_types is None:
        return tasks
    allowed = {str(item) for item in worker_types}
    return [
        task for task in tasks
        if _worker_type_value(_task_value(task, "worker_type", "")) in allowed
    ]


def _task_execution_result(
    state: ExecuteAgentState,
    worker_type: str,
    target_id: str,
    *,
    status: str,
    diagnostics: list[dict] | None = None,
    errors: list[str] | None = None,
) -> Any:
    """Build target-specific worker evidence for one plan task."""
    from app.modules.schema.contracts.execution_plan_contracts import ExecutionResult

    task = next(
        (
            item for item in _plan_tasks(state, {worker_type})
            if str(_task_value(item, "target_id", "")) == str(target_id)
        ),
        None,
    )
    if task is None:
        return None
    output_kind = _task_value(task, "expected_output_kind", "parcel")
    return ExecutionResult(
        task_id=str(_task_value(task, "task_id", "")),
        target_id=str(target_id),
        status=status,
        expected_output_kind=output_kind,
        output_artifacts=[output_kind] if status == "succeeded" else [],
        diagnostics=list(diagnostics or []),
        errors=list(errors or []),
    )


def _execution_intent_from_plan(state: ExecuteAgentState) -> Any:
    """Rebuild worker inputs from task snapshots, never from a stale intent."""
    if state.execution_plan is None:
        return state.intent
    from app.modules.schema.contracts.parse_contracts import (
        AxisTarget,
        FacilityTarget,
        ProjectTarget,
        RoadTarget,
        SpatialPlanningIntent,
        ZoneTarget,
    )

    model_by_type = {
        "project": ("project_targets", ProjectTarget),
        "zone": ("zone_targets", ZoneTarget),
        "facility": ("facilities", FacilityTarget),
        "axis": ("development_axes", AxisTarget),
        "road": ("road_targets", RoadTarget),
    }
    values: dict[str, list[Any]] = {field: [] for field, _ in model_by_type.values()}
    for task in _plan_tasks(state):
        target_type = str(_task_value(task, "target_type", ""))
        binding = _task_value(task, "assignment")
        payload = _task_value(binding, "target_binding", {}) or {}
        payload = dict(payload)
        anchor = _task_value(binding, "anchor_point")
        if anchor is not None:
            payload["anchor_point"] = anchor
        selected_bsm = str(_task_value(binding, "selected_bsm", "") or "")
        if selected_bsm:
            payload.setdefault("candidate_bsms", [selected_bsm])
        payload["target_id"] = str(_task_value(task, "target_id", payload.get("target_id", "")) or "")
        spec = model_by_type.get(target_type)
        if spec is not None:
            field, model = spec
            values[field].append(model.model_validate(payload))
    return SpatialPlanningIntent(**values)


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

    Invalid source geometry (e.g. self-intersecting cadastral polygons) is
    repaired at load time via buffer(0)/make_valid so downstream WKT output
    never carries an invalid geometry. GeometryCollection results are reduced
    to their areal parts (mirrors app/utils/geo_utils.py convention).
    """
    from types import SimpleNamespace

    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    props = feature.get("properties") or {}
    raw_geom = feature.get("geometry")
    if raw_geom and isinstance(raw_geom, dict) and raw_geom.get("type"):
        try:
            g = shape(raw_geom)
            if not g.is_valid:
                try:
                    g = g.buffer(0)
                except Exception:
                    g = make_valid(g)
                if g.geom_type == "GeometryCollection":
                    areal = [p for p in g.geoms if p.area > 0]
                    g = unary_union(areal) if len(areal) > 1 else areal[0]
                raw_geom = mapping(g)
        except Exception:
            pass
    return SimpleNamespace(
        bsm=str(props.get("BSM") or props.get("bsm") or ""),
        geometry=raw_geom,
        dlbm=str(props.get("DLBM") or props.get("dlbm") or ""),
        dlbm_system=str(props.get("DLBM_SYSTEM") or props.get("dlbm_system") or ""),
        area_sqm=float(props.get("area_sqm") or props.get("area") or 0),
        area_ha=float(props.get("area_ha") or 0),
    )


def _parcel_geometry(parcel: Any) -> dict:
    geometry = parcel.get("geometry") if isinstance(parcel, dict) else getattr(parcel, "geometry", None)
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
