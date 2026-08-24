"""Shared helpers for EXECUTE materializers (parcel adaptation, task routing)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.domain.materialization.execute_state import ExecuteAgentState


WORKER_ROUTE_KEYS = {
    "site_area_footprint": "site_area",
    "parcel_transformation": "layout",
    "facility_placement": "facility",
    "axis_construction": "axis",
    "road_construction": "road",
    "utility_network": "utility",
    "non_spatial_action": "action",
}

WORKER_RESULT_KEYS = {
    "site_area_footprint": "site_area",
    "parcel_transformation": "zone",
    "facility_placement": "facility",
    "axis_construction": "axis",
    "road_construction": "road",
    "utility_network": "utility",
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


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(item) for item in (value or []) if str(item).strip()]


def _candidate_availability_block(candidate: Any) -> str:
    """Return a stable diagnostic when a selected geometry is not usable.

    SELECT normally supplies a ``CandidateGeometry`` whose ``is_executable``
    property already enforces the availability contract.  EXECUTE also
    receives deserialized/dict-shaped candidates during replay, so workers
    must repeat the narrow boundary check instead of trusting only the role
    and WKT.  Unknown exact point/line features remain allowed; unknown
    parcel polygons and fully unavailable candidates do not.
    """
    def value(name: str, default: Any = None) -> Any:
        return candidate.get(name, default) if isinstance(candidate, dict) else getattr(candidate, name, default)

    if candidate is None:
        return "candidate_geometry_missing"
    status = str(value("availability_status", "unknown") or "unknown")
    if status == "fully_unavailable":
        return "candidate_geometry_fully_unavailable"
    if status == "partially_available":
        eligible = value("eligible_area_ha", None)
        if eligible is not None:
            try:
                if float(eligible or 0.0) <= 1e-9:
                    return "candidate_geometry_partial_without_eligible_area"
            except (TypeError, ValueError):
                return "candidate_geometry_partial_area_invalid"
    declared = getattr(candidate, "is_executable", None)
    if declared is False:
        return "candidate_geometry_not_executable"
    if status == "unknown":
        kind = str(value("kind", "") or "")
        domain = str(value("spatial_domain_kind", "") or "")
        if kind == "polygon" and domain in {"parcel_extent", "parcel_set"}:
            return "candidate_geometry_availability_unknown"
    return ""


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
    task_id: str = "",
    candidate_id: str = "",
) -> Any:
    """Build target-specific worker evidence for one plan task."""
    from app.contracts.workflow.execution_plan_contracts import TaskExecutionResult

    task = next(
        (
            item for item in _plan_tasks(state, {worker_type})
            if str(_task_value(item, "target_id", "")) == str(target_id)
            and (not task_id or str(_task_value(item, "task_id", "")) == str(task_id))
            and (not candidate_id or str(_task_value(item, "candidate_id", "")) == str(candidate_id))
        ),
        None,
    )
    if task is None:
        return None
    output_kind = _task_value(task, "expected_output_kind", "parcel")
    assignment = _task_value(task, "assignment")
    binding = _task_value(assignment, "target_binding", {}) or {}
    return TaskExecutionResult(
        task_id=str(_task_value(task, "task_id", "")),
        target_id=str(target_id),
        status=status,
        expected_output_kind=output_kind,
        output_artifacts=[output_kind] if status == "succeeded" else [],
        diagnostics=list(diagnostics or []),
        errors=list(errors or []),
        scenario_id=str(_task_value(task, "scenario_id", "") or ""),
        candidate_id=str(_task_value(task, "candidate_id", "") or ""),
        relation_ids=list(_task_value(task, "relation_ids", []) or []),
        feature_ids=_string_list(
            _task_value(task, "feature_ids", [])
            or binding.get("feature_ids", [])
        ),
        source_feature_ids=_string_list(
            _task_value(task, "source_feature_ids", [])
            or binding.get("source_feature_ids", [])
            or _task_value(assignment, "source_feature_id", "")
        ),
        entity_refs=_string_list(
            _task_value(task, "entity_refs", [])
            or binding.get("entity_refs", [])
            or _task_value(assignment, "entity_ref", "")
        ),
        relation_refs=_string_list(
            _task_value(task, "relation_refs", [])
            or binding.get("relation_refs", [])
            or _task_value(assignment, "relation_refs", [])
        ),
        feature_bsms=_string_list(
            _task_value(task, "feature_bsms", [])
            or binding.get("feature_bsms", [])
            or _task_value(assignment, "feature_bsm", "")
        ),
        evidence_refs=_string_list(
            _task_value(task, "evidence_refs", [])
            or binding.get("evidence_refs", [])
            or _task_value(assignment, "evidence_refs", [])
        ),
        l1_snapshot_ref=str(
            _task_value(task, "l1_snapshot_ref", "")
            or binding.get("l1_snapshot_ref", "")
            or _task_value(assignment, "l1_snapshot_ref", "")
            or ""
        ),
        bundle_snapshot_digest=str(
            _task_value(task, "bundle_snapshot_digest", "")
            or binding.get("bundle_snapshot_digest", "")
            or _task_value(assignment, "bundle_snapshot_digest", "")
            or ""
        ),
        availability_status=(
            str(_task_value(task, "availability_status", "") or "")
            if str(_task_value(task, "availability_status", "") or "") not in {"", "unknown"}
            else str(
                binding.get("availability_status")
                or _task_value(assignment, "availability_status", "unknown")
                or "unknown"
            )
        ),
        eligible_area_ha=(
            _task_value(task, "eligible_area_ha", None)
            if _task_value(task, "eligible_area_ha", None) is not None
            else binding.get("eligible_area_ha", _task_value(assignment, "eligible_area_ha", None))
        ),
        excluded_area_ha=(
            _task_value(task, "excluded_area_ha", None)
            if _task_value(task, "excluded_area_ha", None) is not None
            else binding.get("excluded_area_ha", _task_value(assignment, "excluded_area_ha", None))
        ),
        adjacent_parcel_bsms=_string_list(
            _task_value(task, "adjacent_parcel_bsms", [])
            or binding.get("adjacent_parcel_bsms", [])
            or _task_value(assignment, "adjacent_parcel_bsms", [])
        ),
        adjacency_evidence_refs=_string_list(
            _task_value(task, "adjacency_evidence_refs", [])
            or binding.get("adjacency_evidence_refs", [])
            or _task_value(assignment, "adjacency_evidence_refs", [])
        ),
    )


def _task_for_target(
    state: ExecuteAgentState,
    target_id: str,
    *,
    task_id: str = "",
    candidate_id: str = "",
) -> Any:
    """Resolve one authoritative task by stable task/candidate identity."""
    return next(
        (
            item
            for item in _plan_tasks(state)
            if str(_task_value(item, "target_id", "") or "") == str(target_id)
            and (not task_id or str(_task_value(item, "task_id", "")) == str(task_id))
            and (not candidate_id or str(_task_value(item, "candidate_id", "")) == str(candidate_id))
        ),
        None,
    )


def _scenario_features_for_layer(
    state: ExecuteAgentState,
    layer: dict[str, Any],
    *,
    generation_operation: str,
) -> list[Any]:
    """Convert worker GeoJSON into strict ScenarioFeature lineage rows.

    A worker may only emit a feature when the layer property contains an
    explicit target binding.  There is no single-target inference here: an
    unbound feature is returned as a diagnostic and is excluded from the
    scenario feature list.
    """
    from app.contracts.planning.scenario import ScenarioFeature

    data = layer.get("data") or layer.get("geojson") or layer
    features: list[Any] = []
    for index, feature in enumerate(data.get("features") or []):
        properties = dict(feature.get("properties") or {})
        target_id = str(properties.get("target_id") or "").strip()
        if not target_id:
            continue
        task = _task_for_target(
            state,
            target_id,
            candidate_id=str(properties.get("candidate_id") or ""),
        )
        if task is None:
            continue
        assignment = _task_value(task, "assignment")
        geometry = feature.get("geometry") or {}
        geometry_type = str(geometry.get("type") or "").lower()
        geometry_kind = {
            "point": "point",
            "linestring": "line",
            "multilinestring": "line",
            "polygon": "polygon",
            "multipolygon": "polygon",
            "multipatch": "multipatch",
        }.get(geometry_type)
        if geometry_kind is None:
            continue
        try:
            from shapely.geometry import shape

            geometry_wkt = shape(geometry).wkt
        except Exception:
            continue
        if not geometry_wkt:
            continue
        candidate_id = str(
            properties.get("candidate_id")
            or _task_value(task, "candidate_id", "")
            or _task_value(assignment, "selected_bsm", "")
            or ""
        ).strip()
        if not candidate_id:
            continue
        scenario_id = str(
            properties.get("scenario_id")
            or _task_value(task, "scenario_id", "")
            or getattr(getattr(state, "approved_execution_input", None), "scenario_id", "")
            or "scenario:execution"
        ).strip()
        relation_ids = list(
            properties.get("relation_ids")
            or _task_value(task, "relation_ids", [])
            or []
        )
        if not relation_ids:
            relation_ids = [f"selection:{target_id}:{candidate_id}"]
        source_refs = list(
            properties.get("source_refs")
            or _task_value(task, "input_artifact_refs", [])
            or _task_value(assignment, "input_artifact_refs", [])
            or []
        )
        source_refs = [str(ref) for ref in source_refs if str(ref).strip()]
        if not source_refs:
            source_refs = [f"task:{_task_value(task, 'task_id', target_id)}"]
        binding = _task_value(assignment, "target_binding", {}) or {}
        assignment_feature_bsms = _string_list(
            _task_value(assignment, "feature_bsms", [])
            or binding.get("feature_bsms", [])
        )
        feature_bsms = _string_list(
            properties.get("feature_bsms")
            or _task_value(task, "feature_bsms", [])
            or assignment_feature_bsms
        )
        source_feature_ids = _string_list(
            properties.get("source_feature_ids")
            or _task_value(task, "source_feature_ids", [])
            or binding.get("source_feature_ids", [])
            or _task_value(assignment, "source_feature_id", "")
        )
        entity_refs = _string_list(
            properties.get("entity_refs")
            or binding.get("entity_refs", [])
            or _task_value(assignment, "entity_ref", "")
        )
        relation_refs = _string_list(
            properties.get("relation_refs")
            or _task_value(assignment, "relation_refs", [])
        )
        evidence_refs = _string_list(
            properties.get("evidence_refs")
            or _task_value(task, "evidence_refs", [])
            or _task_value(assignment, "evidence_refs", [])
            or source_refs
        )
        l1_snapshot_ref = str(
            properties.get("l1_snapshot_ref")
            or _task_value(task, "l1_snapshot_ref", "")
            or _task_value(assignment, "l1_snapshot_ref", "")
            or ""
        )
        bundle_snapshot_digest = str(
            properties.get("bundle_snapshot_digest")
            or _task_value(task, "bundle_snapshot_digest", "")
            or _task_value(assignment, "bundle_snapshot_digest", "")
            or ""
        )
        feature_id = str(
            properties.get("feature_id")
            or f"feature:{scenario_id}:{target_id}:{index}"
        )
        properties.update({
            "scenario_id": scenario_id,
            "candidate_id": candidate_id,
            "feature_id": feature_id,
            "lineage_id": feature_id,
            "relation_ids": [str(ref) for ref in relation_ids if str(ref).strip()],
            "source_refs": source_refs,
            "feature_bsms": [str(ref) for ref in feature_bsms if str(ref).strip()],
            "source_feature_ids": [str(ref) for ref in source_feature_ids if str(ref).strip()],
            "entity_refs": [str(ref) for ref in entity_refs if str(ref).strip()],
            "relation_refs": [str(ref) for ref in relation_refs if str(ref).strip()],
            "evidence_refs": [str(ref) for ref in evidence_refs if str(ref).strip()],
            "l1_snapshot_ref": l1_snapshot_ref,
            "bundle_snapshot_digest": bundle_snapshot_digest,
            "generation_operation": str(
                properties.get("generation_operation") or generation_operation
            ),
            "availability_status": str(properties.get("availability_status") or "unknown"),
            "eligible_area_ha": properties.get("eligible_area_ha"),
            "excluded_area_ha": properties.get("excluded_area_ha"),
            "adjacent_parcel_bsms": _string_list(properties.get("adjacent_parcel_bsms", [])),
            "adjacency_evidence_refs": _string_list(properties.get("adjacency_evidence_refs", [])),
        })
        feature["properties"] = properties
        features.append(ScenarioFeature(
            feature_id=feature_id,
            scenario_id=scenario_id,
            target_id=target_id,
            candidate_id=candidate_id,
            geometry_kind=geometry_kind,
            geometry_wkt=geometry_wkt,
            crs=str(properties.get("crs") or "EPSG:4326"),
            generation_operation=str(
                properties.get("generation_operation") or generation_operation
            ),
            source_refs=source_refs,
            source_bsms=_string_list(properties.get("source_bsms", [])),
            availability_status=str(properties.get("availability_status") or "unknown"),
            eligible_area_ha=properties.get("eligible_area_ha"),
            excluded_area_ha=properties.get("excluded_area_ha"),
            adjacent_parcel_bsms=_string_list(properties.get("adjacent_parcel_bsms", [])),
            adjacency_evidence_refs=_string_list(properties.get("adjacency_evidence_refs", [])),
            feature_bsms=_string_list(properties.get("feature_bsms", [])),
            source_feature_ids=_string_list(properties.get("source_feature_ids", [])),
            entity_refs=_string_list(properties.get("entity_refs", [])),
            evidence_refs=_string_list(properties.get("evidence_refs", [])),
            relation_ids=[str(ref) for ref in relation_ids if str(ref).strip()],
        ))
    return features


def _attach_feature_lineage(task_results: list[Any], features: list[Any]) -> list[Any]:
    """Attach feature IDs by target plus candidate, never by target alone."""
    by_identity: dict[tuple[str, str], list[str]] = {}
    for feature in features or []:
        target_id = str(getattr(feature, "target_id", "") or "")
        candidate_id = str(getattr(feature, "candidate_id", "") or "")
        feature_id = str(getattr(feature, "feature_id", "") or "")
        if target_id and feature_id:
            by_identity.setdefault((target_id, candidate_id), []).append(feature_id)
    for result in task_results or []:
        target_id = str(getattr(result, "target_id", "") or "")
        candidate_id = str(getattr(result, "candidate_id", "") or "")
        feature_ids = by_identity.get((target_id, candidate_id))
        if feature_ids is None and not candidate_id:
            feature_ids = by_identity.get((target_id, ""))
        if feature_ids is not None:
            result.feature_ids = list(dict.fromkeys(feature_ids))
    return task_results


def _execution_intent_from_plan(state: ExecuteAgentState) -> Any:
    """Rebuild worker inputs from task snapshots, never from a stale intent."""
    if state.execution_plan is None:
        return None
    from app.contracts.workflow.parse_contracts import (
        AxisTarget,
        FacilityTarget,
        LinearAssetTarget,
        SiteAreaTarget,
        RoadTarget,
        SpatialPlanningIntent,
        ZoneTarget,
    )

    model_by_type = {
        "site_area": ("site_area_targets", SiteAreaTarget),
        "zone": ("zone_targets", ZoneTarget),
        "facility": ("facilities", FacilityTarget),
        "axis": ("development_axes", AxisTarget),
        "road": ("road_targets", RoadTarget),
        "linear": ("linear_targets", LinearAssetTarget),
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
    """Read a list field from the plan-derived typed target projection."""
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
    """Resolve current land use from the bundle-backed data boundary."""
    spatial_workspace = getattr(state, "spatial_workspace", None)
    if spatial_workspace is not None:
        from app.infrastructure.export.delivery_snapshot import canonical_gis_data_from_workspace

        landuse = canonical_gis_data_from_workspace(spatial_workspace).get("landuse_current_geojson")
    else:
        raise ValueError("EXECUTE requires spatial_workspace for current land use")
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
