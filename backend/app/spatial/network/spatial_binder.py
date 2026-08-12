"""Stage 3: bind evidence-backed road demands and constraints to GIS space.

The module consumes the standardized current-road network from Stage 1.  It
never reads the manually planned road, which remains evaluation-only data.
Stage-2.6 planning-node inputs are preferred when present, then Stage-2.5
resolved files, then raw Stage-2 data.  Unknown positions remain explicitly
unresolved.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import nearest_points, transform as transform_geometry, unary_union

from .schemas import SpatialBindingConfig, SpatialBindingResult


SCHEMA_VERSION = "1.0"
NAME_FIELDS = ("name", "NAME", "名称", "注记", "label", "text")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _normalise_name(value: Any) -> str:
    return re.sub(r"[\s_（）()、，,。·\-—]+", "", str(value or "")).lower()


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_list(value: Any) -> List[str]:
    return [str(item) for item in _as_list(value) if str(item or "").strip()]


def _feature_collection(name: str, crs: str, features: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": crs}},
        "features": list(features),
    }


def _collection_crs(payload: Mapping[str, Any], default: str) -> str:
    return str(
        ((payload.get("crs") or {}).get("properties") or {}).get("name") or default
    )


def _transformer(source_crs: str, target_crs: str) -> Optional[Transformer]:
    if source_crs.upper() == target_crs.upper():
        return None
    return Transformer.from_crs(source_crs, target_crs, always_xy=True)


def _transform(geometry: Any, transformer: Optional[Transformer]) -> Any:
    return geometry if transformer is None else transform_geometry(transformer.transform, geometry)


def _resolved_input_dir(config: SpatialBindingConfig) -> Tuple[Path, str]:
    required = ("demand_points.geojson", "road_projects.json", "road_constraints.json")
    candidate = config.stage2_6_dir
    if candidate is not None and all((candidate / name).exists() for name in required):
        if (candidate / "planning_nodes.geojson").exists() and (
            candidate / "road_planning_requests.json"
        ).exists():
            return candidate, "stage2_6_planning_nodes"
    candidate = config.stage2_5_resolved_dir
    if candidate is not None and all((candidate / name).exists() for name in required):
        return candidate, "stage2_5_resolved"
    return config.stage2_dir, "stage2_fallback"


def _stage2_6_planning_gate(input_dir: Path, input_mode: str) -> Dict[str, Any]:
    """Read the Stage-2.6 safety gate when that contract is the active input.

    Older Stage-2.6 exports did not include a report, so their absence remains
    compatible but is made explicit in the Stage-3 report.  A present, blocked
    Stage-2.6 gate must never be bypassed simply because compatibility demand
    points omit unresolved entities.
    """

    if input_mode != "stage2_6_planning_nodes":
        return {
            "available": False,
            "automatic_route_generation_allowed": True,
            "reason": None,
            "fallback": "not_using_stage2_6_input",
        }
    report_path = input_dir / "stage2_6_report.json"
    if not report_path.exists():
        return {
            "available": False,
            "automatic_route_generation_allowed": True,
            "reason": None,
            "fallback": "legacy_stage2_6_output_without_report",
        }
    payload = _read_json(report_path)
    gate = payload.get("planning_gate")
    if not isinstance(gate, Mapping) or "automatic_route_generation_allowed" not in gate:
        return {
            "available": False,
            "automatic_route_generation_allowed": True,
            "reason": None,
            "fallback": "stage2_6_report_without_planning_gate",
        }
    return {
        "available": True,
        "automatic_route_generation_allowed": bool(gate.get("automatic_route_generation_allowed")),
        "reason": str(gate.get("reason") or "Stage 2.6 planning gate blocked route generation."),
        "fallback": None,
    }


def _point_index(paths: Sequence[Path], display_crs: str) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for path in paths:
        frame = gpd.read_file(path)
        if frame.crs is None:
            raise ValueError(f"point source has no CRS: {path}")
        frame = frame.to_crs(display_crs)
        fields = [field for field in NAME_FIELDS if field in frame.columns]
        for feature_index, row in frame.iterrows():
            geometry = row.geometry
            if geometry is None or geometry.is_empty or geometry.geom_type != "Point":
                continue
            for field in fields:
                value = row.get(field)
                key = _normalise_name(value)
                if len(key) < 2:
                    continue
                result[key].append(
                    {
                        "name": str(value),
                        "geometry": mapping(geometry),
                        "source": _relative(path),
                        "feature_index": str(feature_index),
                        "matched_field": field,
                    }
                )
    return result


def _exact_match(
    index: Mapping[str, Sequence[Dict[str, Any]]], names: Iterable[Any]
) -> Optional[Dict[str, Any]]:
    for name in names:
        key = _normalise_name(name)
        if not key:
            continue
        unique: Dict[str, Dict[str, Any]] = {}
        for candidate in index.get(key, ()):
            geometry_key = json.dumps(candidate["geometry"], sort_keys=True)
            unique.setdefault(geometry_key, candidate)
        if len(unique) == 1:
            return next(iter(unique.values()))
    return None


def _prepare_roads(config: SpatialBindingConfig) -> Tuple[gpd.GeoDataFrame, str]:
    roads = gpd.read_file(config.road_edges_path)
    if roads.crs is None:
        raise ValueError(f"road edges have no CRS: {config.road_edges_path}")
    roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
    roads = roads[roads.geometry.geom_type.isin(["LineString", "MultiLineString"])].copy()
    if roads.empty:
        raise ValueError("standardized current-road input contains no usable line geometry")
    roads = roads.to_crs(config.metric_crs)
    if "edge_id" not in roads.columns:
        roads["edge_id"] = [f"E{index + 1:06d}" for index in range(len(roads))]
    if "component_id" not in roads.columns:
        roads["component_id"] = "C0001"
    roads["_length_m"] = roads.geometry.length
    roads = roads.sort_values("edge_id", kind="stable").reset_index(drop=True)
    component_lengths = roads.groupby("component_id", dropna=False)["_length_m"].sum()
    main_component = str(component_lengths.sort_values(ascending=False, kind="stable").index[0])
    return roads, main_component


def _nearest_road(point: Point, roads: gpd.GeoDataFrame) -> Tuple[Any, Point, float]:
    distances = roads.geometry.distance(point)
    minimum = float(distances.min())
    tolerance = max(1e-8, minimum * 1e-12)
    candidates = roads.loc[(distances - minimum).abs() <= tolerance]
    row = candidates.sort_values("edge_id", kind="stable").iloc[0]
    snapped = nearest_points(point, row.geometry)[1]
    return row, snapped, float(point.distance(snapped))


def _status(distance_m: float, config: SpatialBindingConfig) -> str:
    if distance_m <= config.connected_threshold_m:
        return "connected"
    if distance_m <= config.near_network_threshold_m:
        return "near_network"
    return "isolated"


def _service_fields(status: str) -> Dict[str, Any]:
    if status == "connected":
        return {
            "service_assessment": "already_satisfied",
            "served_by_current_network": True,
            "requires_short_connector": False,
            "requires_new_road": False,
        }
    if status == "near_network":
        return {
            "service_assessment": "short_access_needed",
            "served_by_current_network": False,
            "requires_short_connector": True,
            "requires_new_road": True,
        }
    if status == "isolated":
        return {
            "service_assessment": "new_route_needed",
            "served_by_current_network": False,
            "requires_short_connector": False,
            "requires_new_road": True,
        }
    return {
        "service_assessment": "blocked_unresolved",
        "served_by_current_network": None,
        "requires_short_connector": None,
        "requires_new_road": None,
    }


def _bind_demands(
    payload: Mapping[str, Any],
    roads: gpd.GeoDataFrame,
    main_component: str,
    config: SpatialBindingConfig,
    point_index: Mapping[str, Sequence[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    source_crs = _collection_crs(payload, config.display_crs)
    to_metric = _transformer(source_crs, config.metric_crs)
    to_display = _transformer(config.metric_crs, config.display_crs)
    source_to_display = _transformer(source_crs, config.display_crs)
    bound: List[Dict[str, Any]] = []
    connectors: List[Dict[str, Any]] = []
    ordered = sorted(
        payload.get("features", []),
        key=lambda feature: str((feature.get("properties") or {}).get("demand_id") or feature.get("id") or ""),
    )
    for feature in ordered:
        properties = dict(feature.get("properties") or {})
        demand_id = str(properties.get("demand_id") or feature.get("id") or "")
        geometry_payload = feature.get("geometry")
        if not geometry_payload:
            matched = _exact_match(
                point_index,
                (properties.get("place_name"), properties.get("name")),
            )
            if matched:
                geometry_payload = matched["geometry"]
                properties.update(
                    {
                        "location_status": "matched",
                        "location_confidence": 1.0,
                        "location_reason": "Stage 3 found one exact-name point-layer match",
                        "location_match": {key: value for key, value in matched.items() if key != "geometry"},
                        "requires_human_confirmation": False,
                    }
                )
                source_crs_for_feature = config.display_crs
                feature_to_metric = _transformer(source_crs_for_feature, config.metric_crs)
                feature_to_display = None
            else:
                properties.update(
                    {
                        "network_status": "unresolved",
                        "distance_to_road_m": None,
                        "nearest_edge_id": None,
                        "nearest_component_id": None,
                        "nearest_component_is_main": None,
                        "road_snap_geometry": None,
                        **_service_fields("unresolved"),
                    }
                )
                bound.append(
                    {"type": "Feature", "id": demand_id, "geometry": None, "properties": properties}
                )
                continue
        else:
            feature_to_metric = to_metric
            feature_to_display = source_to_display

        source_point = shape(geometry_payload)
        if source_point.is_empty or source_point.geom_type != "Point":
            properties.update(
                {
                    "network_status": "unresolved",
                    "distance_to_road_m": None,
                    "nearest_edge_id": None,
                    "nearest_component_id": None,
                    "nearest_component_is_main": None,
                    "road_snap_geometry": None,
                    "location_reason": "demand geometry is not a valid Point",
                    **_service_fields("unresolved"),
                }
            )
            bound.append(
                {"type": "Feature", "id": demand_id, "geometry": None, "properties": properties}
            )
            continue

        point_metric = _transform(source_point, feature_to_metric)
        road, snap_metric, distance_m = _nearest_road(point_metric, roads)
        network_status = _status(distance_m, config)
        point_display = _transform(source_point, feature_to_display)
        snap_display = _transform(snap_metric, to_display)
        component_id = str(road.get("component_id"))
        properties.update(
            {
                "network_status": network_status,
                "distance_to_road_m": round(distance_m, 3),
                "nearest_edge_id": str(road.get("edge_id")),
                "nearest_component_id": component_id,
                "nearest_component_is_main": component_id == main_component,
                "nearest_edge_is_isolated_component": bool(
                    road.get("is_isolated_component", False)
                ),
                "road_snap_geometry": mapping(snap_display),
                **_service_fields(network_status),
            }
        )
        bound.append(
            {
                "type": "Feature",
                "id": demand_id,
                "geometry": mapping(point_display),
                "properties": properties,
            }
        )
        if distance_m > 1e-6:
            connector_display = _transform(LineString([point_metric, snap_metric]), to_display)
            connector_role = {
                "connected": "diagnostic_snap",
                "near_network": "short_access_candidate",
                "isolated": "nearest_network_reference",
            }[network_status]
            connectors.append(
                {
                    "type": "Feature",
                    "id": f"CONN-{demand_id}",
                    "geometry": mapping(connector_display),
                    "properties": {
                        "demand_id": demand_id,
                        "network_status": network_status,
                        "connector_role": connector_role,
                        "distance_m": round(distance_m, 3),
                        "nearest_edge_id": str(road.get("edge_id")),
                        "is_planned_route": False,
                    },
                }
            )
    return bound, connectors


def _filter_constraint_frame(
    frame: gpd.GeoDataFrame, filters: Mapping[str, Sequence[str]]
) -> gpd.GeoDataFrame:
    if not filters:
        return frame
    selected = None
    for field, values in filters.items():
        if field not in frame.columns:
            continue
        mask = frame[field].astype(str).isin([str(value) for value in values])
        selected = mask if selected is None else selected | mask
    return frame.iloc[0:0] if selected is None else frame.loc[selected]


def _constraint_features(
    payload: Mapping[str, Any], config: SpatialBindingConfig
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    output: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    to_display = _transformer(config.metric_crs, config.display_crs)
    for constraint in sorted(payload.get("constraints", []), key=lambda item: item["constraint_id"]):
        constraint_id = str(constraint["constraint_id"])
        target = str(constraint.get("target_layer") or "")
        if constraint.get("constraint_type") == "design_standard" or target == "road_design":
            records.append(
                {
                    "constraint_id": constraint_id,
                    "target_layer": target,
                    "spatial_binding_status": "nonspatial_design_rule",
                    "reason": "This rule is checked against route design attributes, not a GIS mask.",
                }
            )
            continue
        inline_geometry_payload = constraint.get("geometry")
        if inline_geometry_payload:
            inline_crs = str(constraint.get("geometry_crs") or config.display_crs)
            geometry = _transform(shape(inline_geometry_payload), _transformer(inline_crs, config.metric_crs))
            if geometry.is_empty:
                records.append(
                    {
                        "constraint_id": constraint_id,
                        "target_layer": target,
                        "spatial_binding_status": "unresolved",
                        "reason": "Inline constraint geometry is empty.",
                    }
                )
                continue
            buffer_m = float(constraint.get("buffer_m") or 0.0)
            combined = geometry.buffer(buffer_m) if buffer_m > 0 else geometry
            display_geometry = _transform(combined, to_display)
            evidence = constraint.get("evidence") or {}
            properties = {
                "constraint_id": constraint_id,
                "constraint_type": constraint.get("constraint_type"),
                "target_layer": target,
                "severity": constraint.get("severity"),
                "buffer_m": buffer_m,
                "influence_area_m2": round(float(combined.area), 3),
                "source_paths": _string_list(constraint.get("source_paths")),
                "evidence_id": evidence.get("evidence_id"),
                "spatial_binding_status": "bound",
                "binding_source": "inline_stage2_6_geometry",
            }
            output.append(
                {
                    "type": "Feature",
                    "id": constraint_id,
                    "geometry": mapping(display_geometry),
                    "properties": properties,
                }
            )
            records.append(dict(properties))
            continue
        paths = tuple(config.constraint_layer_sources.get(target, ()))
        if not paths:
            records.append(
                {
                    "constraint_id": constraint_id,
                    "target_layer": target,
                    "spatial_binding_status": "unresolved",
                    "reason": "No authoritative GIS layer is configured for this text constraint.",
                }
            )
            continue
        geometries: List[Any] = []
        source_paths: List[str] = []
        geometry_types: set[str] = set()
        for path in paths:
            frame = gpd.read_file(path)
            if frame.crs is None:
                raise ValueError(f"constraint layer has no CRS: {path}")
            frame = _filter_constraint_frame(
                frame, config.constraint_layer_filters.get(target, {})
            )
            frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
            if frame.empty:
                continue
            frame = frame.to_crs(config.metric_crs)
            for geometry in frame.geometry:
                geometry_types.add(geometry.geom_type)
                geometries.append(geometry)
            source_paths.append(_relative(path))
        if not geometries:
            records.append(
                {
                    "constraint_id": constraint_id,
                    "target_layer": target,
                    "spatial_binding_status": "unresolved",
                    "reason": "Configured GIS layer contains no feature after filtering.",
                }
            )
            continue
        buffer_value = constraint.get("buffer_m")
        needs_buffer = any("Point" in kind or "LineString" in kind for kind in geometry_types)
        if needs_buffer and (buffer_value is None or float(buffer_value) <= 0):
            records.append(
                {
                    "constraint_id": constraint_id,
                    "target_layer": target,
                    "spatial_binding_status": "unresolved",
                    "reason": "Point/line constraint requires a confirmed positive buffer distance.",
                    "source_paths": source_paths,
                }
            )
            continue
        buffer_m = float(buffer_value or 0.0)
        influenced = [
            geometry.buffer(buffer_m) if buffer_m > 0 else geometry for geometry in geometries
        ]
        combined = unary_union(influenced)
        if combined.is_empty:
            continue
        display_geometry = _transform(combined, to_display)
        evidence = constraint.get("evidence") or {}
        properties = {
            "constraint_id": constraint_id,
            "constraint_type": constraint.get("constraint_type"),
            "target_layer": target,
            "severity": constraint.get("severity"),
            "buffer_m": buffer_m,
            "influence_area_m2": round(float(combined.area), 3),
            "source_paths": source_paths,
            "evidence_id": evidence.get("evidence_id"),
            "spatial_binding_status": "bound",
        }
        output.append(
            {
                "type": "Feature",
                "id": constraint_id,
                "geometry": mapping(display_geometry),
                "properties": properties,
            }
        )
        records.append(dict(properties))
    return output, records


def _bind_projects(
    payload: Mapping[str, Any],
    bound_demands: Sequence[Dict[str, Any]],
    roads: gpd.GeoDataFrame,
    main_component: str,
    config: SpatialBindingConfig,
    point_index: Mapping[str, Sequence[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Bind both project endpoints while preserving the Stage-2 evidence object."""

    to_metric = _transformer(config.display_crs, config.metric_crs)
    demand_by_id = {
        str((feature.get("properties") or {}).get("demand_id") or feature.get("id")): feature
        for feature in bound_demands
    }
    output: List[Dict[str, Any]] = []
    endpoint_features: List[Dict[str, Any]] = []
    for source_project in sorted(
        payload.get("projects", []), key=lambda item: str(item.get("project_id") or "")
    ):
        project = json.loads(json.dumps(source_project, ensure_ascii=False))
        project_id = str(project.get("project_id") or "")
        endpoint_results: Dict[str, Dict[str, Any]] = {}
        for side in ("start", "end"):
            geometry_payload = project.get(f"{side}_geometry")
            location_source = "stage2_project_geometry" if geometry_payload else None
            demand_id = project.get(f"{side}_demand_id")
            if not geometry_payload and demand_id:
                demand = demand_by_id.get(str(demand_id))
                if demand and demand.get("geometry"):
                    geometry_payload = demand["geometry"]
                    location_source = "linked_demand"
            if not geometry_payload:
                matched = _exact_match(point_index, (project.get(f"{side}_place"),))
                if matched:
                    geometry_payload = matched["geometry"]
                    location_source = "exact_point_layer_match"
            if not geometry_payload:
                endpoint_results[side] = {
                    "endpoint_status": "unresolved",
                    "network_status": "unresolved",
                    "distance_to_road_m": None,
                    "nearest_edge_id": None,
                    "road_snap_geometry": None,
                    "reason": "No confirmed or uniquely matched endpoint coordinate is available.",
                }
                continue
            point_display = shape(geometry_payload)
            if point_display.is_empty or point_display.geom_type != "Point":
                endpoint_results[side] = {
                    "endpoint_status": "unresolved",
                    "network_status": "unresolved",
                    "distance_to_road_m": None,
                    "nearest_edge_id": None,
                    "road_snap_geometry": None,
                    "reason": "Endpoint geometry is not a valid Point.",
                }
                continue
            point_metric = _transform(point_display, to_metric)
            road, snap_metric, distance_m = _nearest_road(point_metric, roads)
            network_status = _status(distance_m, config)
            to_display = _transformer(config.metric_crs, config.display_crs)
            snap_display = _transform(snap_metric, to_display)
            component_id = str(road.get("component_id"))
            endpoint_results[side] = {
                "endpoint_status": "resolved",
                "network_status": network_status,
                "location_source": location_source,
                "distance_to_road_m": round(distance_m, 3),
                "nearest_edge_id": str(road.get("edge_id")),
                "nearest_component_id": component_id,
                "nearest_component_is_main": component_id == main_component,
                "road_snap_geometry": mapping(snap_display),
            }
            endpoint_features.append(
                {
                    "type": "Feature",
                    "id": f"{project_id}-{side}",
                    "geometry": mapping(point_display),
                    "properties": {
                        "project_id": project_id,
                        "project_name": project.get("name"),
                        "endpoint": side,
                        "place_name": project.get(f"{side}_place"),
                        "network_status": network_status,
                        "distance_to_road_m": round(distance_m, 3),
                        "nearest_edge_id": str(road.get("edge_id")),
                    },
                }
            )
        project["start_network_binding"] = endpoint_results["start"]
        project["end_network_binding"] = endpoint_results["end"]
        project["spatial_binding_status"] = (
            "ready"
            if all(item["endpoint_status"] == "resolved" for item in endpoint_results.values())
            else "unresolved"
        )
        project["planning_need"] = {
            "new": "new_route",
            "widen": "widen_existing_road",
            "harden": "upgrade_existing_road_surface",
        }.get(str(project.get("action")), "action_needs_confirmation")
        output.append(project)
    return output, endpoint_features


def bind_road_spatial_requirements(config: SpatialBindingConfig) -> SpatialBindingResult:
    """Run Stage 3 and write deterministic GIS-displayable outputs."""

    config.validate()
    input_dir, input_mode = _resolved_input_dir(config)
    stage2_6_gate = _stage2_6_planning_gate(input_dir, input_mode)
    demand_payload = _read_json(input_dir / "demand_points.geojson")
    project_payload = _read_json(input_dir / "road_projects.json")
    constraint_payload = _read_json(input_dir / "road_constraints.json")
    roads, main_component = _prepare_roads(config)
    sources = list(config.point_sources)
    confirmed_locations = input_dir / "confirmed_locations.geojson"
    if confirmed_locations.exists():
        sources.append(confirmed_locations)
    point_index = _point_index(tuple(dict.fromkeys(sources)), config.display_crs)
    demands, connectors = _bind_demands(
        demand_payload, roads, main_component, config, point_index
    )
    projects, project_endpoints = _bind_projects(
        project_payload, demands, roads, main_component, config, point_index
    )
    constraints, constraint_records = _constraint_features(constraint_payload, config)

    status_counts = Counter(
        feature["properties"]["network_status"] for feature in demands
    )
    by_type: Dict[str, Counter[str]] = defaultdict(Counter)
    for feature in demands:
        props = feature["properties"]
        by_type[str(props.get("demand_type") or "unknown")][props["network_status"]] += 1
    unresolved_constraints = [
        item for item in constraint_records if item["spatial_binding_status"] == "unresolved"
    ]
    nonspatial_constraints = [
        item
        for item in constraint_records
        if item["spatial_binding_status"] == "nonspatial_design_rule"
    ]
    project_status_counts = Counter(project["spatial_binding_status"] for project in projects)
    project_action_counts = Counter(str(project.get("action") or "unspecified") for project in projects)
    gate_block_reasons: List[str] = []
    if status_counts.get("unresolved", 0):
        gate_block_reasons.append("Unresolved demand locations must be confirmed.")
    if project_status_counts.get("unresolved", 0):
        gate_block_reasons.append("Unresolved road-project endpoints must be confirmed.")
    if unresolved_constraints:
        gate_block_reasons.append("Unresolved spatial constraint parameters must be confirmed.")
    if not stage2_6_gate["automatic_route_generation_allowed"]:
        gate_block_reasons.append(f"Stage 2.6 gate: {stage2_6_gate['reason']}")
    automatic_route_generation_allowed = not gate_block_reasons
    report = {
        "schema_version": SCHEMA_VERSION,
        "data_mode": demand_payload.get("data_mode", "production"),
        "input_mode": input_mode,
        "input_dir": _relative(input_dir),
        "stage2_5_interface": {
            "configured_stage2_6_dir": _relative(config.stage2_6_dir)
            if config.stage2_6_dir
            else None,
            "stage2_6_files_used": input_mode == "stage2_6_planning_nodes",
            "configured_resolved_dir": _relative(config.stage2_5_resolved_dir)
            if config.stage2_5_resolved_dir
            else None,
            "resolved_files_used": input_mode == "stage2_5_resolved",
            "fallback_behavior": "Stage 2.6 planning nodes are preferred; otherwise Stage 2.5 resolved files or Stage 2 raw outputs are used.",
        },
        "road_input": _relative(config.road_edges_path),
        "road_input_role": "standardized_current_network",
        "main_component_id": main_component,
        "metric_crs": config.metric_crs,
        "display_crs": config.display_crs,
        "thresholds_m": {
            "connected": config.connected_threshold_m,
            "near_network": config.near_network_threshold_m,
        },
        "demand_count": len(demands),
        "demand_status_counts": {
            status: status_counts.get(status, 0)
            for status in ("connected", "near_network", "isolated", "unresolved")
        },
        "demand_status_by_type": {
            kind: {
                status: counts.get(status, 0)
                for status in ("connected", "near_network", "isolated", "unresolved")
            }
            for kind, counts in sorted(by_type.items())
        },
        "already_satisfied_count": status_counts.get("connected", 0),
        "short_connector_required_count": status_counts.get("near_network", 0),
        "new_route_required_count": status_counts.get("isolated", 0),
        "blocked_unresolved_count": status_counts.get("unresolved", 0),
        "road_project_count": len(projects),
        "spatially_ready_project_count": project_status_counts.get("ready", 0),
        "unresolved_project_count": project_status_counts.get("unresolved", 0),
        "road_project_action_counts": dict(sorted(project_action_counts.items())),
        "constraint_count": len(constraint_payload.get("constraints", [])),
        "spatially_bound_constraint_count": len(constraints),
        "unresolved_constraint_count": len(unresolved_constraints),
        "nonspatial_design_constraint_count": len(nonspatial_constraints),
        "constraint_bindings": constraint_records,
        "stage2_6_planning_gate": stage2_6_gate,
        "leakage_guard": {
            "planned_road_read": False,
            "rule": "Only Stage-1 standardized current-road edges are accepted by default.",
        },
        "planning_gate": {
            "automatic_route_generation_allowed": automatic_route_generation_allowed,
            "reason": " ".join(gate_block_reasons)
            if gate_block_reasons
            else "All demand locations, spatial constraints, and Stage 2.6 gates are executable.",
        },
    }

    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    binding_path = output_dir / "demand_network_binding.geojson"
    project_binding_path = output_dir / "road_project_spatial_binding.json"
    project_endpoints_path = output_dir / "road_project_endpoints.geojson"
    connectors_path = output_dir / "demand_road_connectors.geojson"
    constraints_path = output_dir / "spatial_constraints.geojson"
    unserved_path = output_dir / "unserved_demands.geojson"
    preview_path = output_dir / "stage3_preview.geojson"
    report_path = output_dir / "stage3_report.json"
    unserved = [
        feature
        for feature in demands
        if feature["properties"]["network_status"] != "connected"
    ]
    preview: List[Dict[str, Any]] = []
    for feature in demands:
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["preview_role"] = "demand"
        preview.append(copied)
    for feature in connectors:
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["preview_role"] = "connector"
        preview.append(copied)
    for feature in project_endpoints:
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["preview_role"] = "project_endpoint"
        preview.append(copied)
    for feature in constraints:
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["preview_role"] = "constraint"
        preview.append(copied)

    _write_json(binding_path, _feature_collection("demand_network_binding", config.display_crs, demands))
    _write_json(
        project_binding_path,
        {
            "type": "RoadProjectSpatialBindingCollection",
            "schema_version": SCHEMA_VERSION,
            "projects": projects,
        },
    )
    _write_json(
        project_endpoints_path,
        _feature_collection("road_project_endpoints", config.display_crs, project_endpoints),
    )
    _write_json(connectors_path, _feature_collection("demand_road_connectors", config.display_crs, connectors))
    _write_json(constraints_path, _feature_collection("spatial_constraints", config.display_crs, constraints))
    _write_json(unserved_path, _feature_collection("unserved_demands", config.display_crs, unserved))
    _write_json(preview_path, _feature_collection("stage3_preview", config.display_crs, preview))
    _write_json(report_path, report)
    return SpatialBindingResult(
        output_dir=output_dir,
        demand_binding_path=binding_path,
        project_binding_path=project_binding_path,
        project_endpoints_path=project_endpoints_path,
        connectors_path=connectors_path,
        constraints_path=constraints_path,
        unserved_path=unserved_path,
        preview_path=preview_path,
        report_path=report_path,
        report=report,
    )


__all__ = ["bind_road_spatial_requirements"]
