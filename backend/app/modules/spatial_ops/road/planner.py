"""Stage 4 current-network analysis and explainable corridor generation.

This first version deliberately uses deterministic geometric alternatives and
transparent scoring.  It produces village-road corridor concepts, not
construction alignments, and never reads the held-out manually planned road.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import geopandas as gpd
import networkx as nx
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import LineString, MultiPoint, Point, mapping, shape
from shapely.ops import transform as transform_geometry, unary_union

from .schemas import RoadPlanningConfig, RoadPlanningResult
from .terrain_router import (
    TerrainContext,
    generate_least_cost_routes,
    line_parts,
    load_terrain_context,
    route_impact_metrics,
)


SCHEMA_VERSION = "1.0"
FACILITY_TYPES = {"education", "healthcare", "eldercare", "public_service", "emergency"}
HARD_CONSTRAINT_TARGETS = {
    "water": "crosses_water",
    "ecological_protection": "crosses_ecological_protection",
    "farmland_protection": "occupies_basic_farmland",
    "historical_protection": "crosses_historical_protection",
}


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _feature_collection(name: str, crs: str, features: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": crs}},
        "features": list(features),
    }


def _transformer(source: str, target: str) -> Optional[Transformer]:
    if source.upper() == target.upper():
        return None
    return Transformer.from_crs(source, target, always_xy=True)


def _transform(geometry: Any, transformer: Optional[Transformer]) -> Any:
    return geometry if transformer is None else transform_geometry(transformer.transform, geometry)


def _payload_crs(payload: Mapping[str, Any], default: str) -> str:
    return str(((payload.get("crs") or {}).get("properties") or {}).get("name") or default)


def _load_network(config: RoadPlanningConfig) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, nx.Graph]:
    nodes = gpd.read_file(config.road_nodes_path)
    edges = gpd.read_file(config.road_edges_path)
    if nodes.crs is None or edges.crs is None:
        raise ValueError("Stage-1 node/edge files must declare CRS")
    nodes = nodes.to_crs(config.metric_crs).sort_values("node_id", kind="stable").reset_index(drop=True)
    edges = edges.to_crs(config.metric_crs).sort_values("edge_id", kind="stable").reset_index(drop=True)
    graph = nx.Graph()
    for _, row in nodes.iterrows():
        graph.add_node(
            str(row["node_id"]),
            x=float(row.geometry.x),
            y=float(row.geometry.y),
            component_id=str(row.get("component_id") or ""),
        )
    speed_mps = config.default_speed_kmh * 1000.0 / 3600.0
    for _, row in edges.iterrows():
        left, right = str(row["from_node"]), str(row["to_node"])
        if left not in graph or right not in graph:
            raise ValueError(f"edge references missing node: {row['edge_id']}")
        length = float(row.geometry.length)
        attributes = {
            "edge_id": str(row["edge_id"]),
            "length_m": length,
            "travel_time_s": length / speed_mps,
        }
        if graph.has_edge(left, right):
            if length < graph[left][right]["length_m"]:
                graph[left][right].update(attributes)
        else:
            graph.add_edge(left, right, **attributes)
    return nodes, edges, graph


def _component_records(graph: nx.Graph) -> Tuple[List[Dict[str, Any]], Dict[str, str], str]:
    components = sorted(
        (sorted(component) for component in nx.connected_components(graph)),
        key=lambda members: (-len(members), members[0]),
    )
    records: List[Dict[str, Any]] = []
    node_component: Dict[str, str] = {}
    for index, members in enumerate(components, 1):
        component_id = f"NC{index:04d}"
        subgraph = graph.subgraph(members)
        length = sum(float(data["length_m"]) for _, _, data in subgraph.edges(data=True))
        record = {
            "component_id": component_id,
            "node_count": len(members),
            "edge_count": subgraph.number_of_edges(),
            "total_length_m": round(length, 3),
            "is_single_edge_component": len(members) == 2 and subgraph.number_of_edges() == 1,
            "node_ids": members,
        }
        records.append(record)
        node_component.update({node_id: component_id for node_id in members})
    return records, node_component, records[0]["component_id"]


def _nearest_node(point: Point, nodes: gpd.GeoDataFrame) -> Tuple[str, Point, float]:
    distances = nodes.geometry.distance(point)
    minimum = float(distances.min())
    candidates = nodes.loc[(distances - minimum).abs() <= max(1e-8, minimum * 1e-12)]
    row = candidates.sort_values("node_id", kind="stable").iloc[0]
    return str(row["node_id"]), row.geometry, minimum


def _nearest_road_point(point: Point, edges: gpd.GeoDataFrame) -> Tuple[Point, float]:
    distances = edges.geometry.distance(point)
    minimum = float(distances.min())
    candidates = edges.loc[(distances - minimum).abs() <= max(1e-8, minimum * 1e-12)].copy()
    sort_fields = [field for field in ("edge_id", "from_node", "to_node") if field in candidates.columns]
    if sort_fields:
        candidates = candidates.sort_values(sort_fields, kind="stable")
    row = candidates.iloc[0]
    road_line = row.geometry
    projected = road_line.interpolate(road_line.project(point))
    return projected, minimum


def _network_analysis(
    nodes: gpd.GeoDataFrame,
    edges: gpd.GeoDataFrame,
    graph: nx.Graph,
    config: RoadPlanningConfig,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, str], str]:
    components, node_component, main_component = _component_records(graph)
    deadends = sorted(node for node, degree in graph.degree() if degree == 1)
    isolated_edges = [item for item in components if item["is_single_edge_component"]]
    diagnostics: List[Dict[str, Any]] = []
    node_rows = nodes.set_index("node_id")
    to_display = _transformer(config.metric_crs, config.display_crs)
    for node_id in deadends:
        point = node_rows.loc[node_id].geometry
        diagnostics.append(
            {
                "type": "Feature",
                "id": f"DE-{node_id}",
                "geometry": mapping(_transform(point, to_display)),
                "properties": {
                    "diagnostic_type": "dead_end",
                    "node_id": node_id,
                    "component_id": node_component[node_id],
                    "degree": 1,
                },
            }
        )
    analysis = {
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "total_length_m": round(float(edges.geometry.length.sum()), 3),
        "connected_component_count": len(components),
        "largest_component_node_ratio": round(components[0]["node_count"] / graph.number_of_nodes(), 6),
        "dead_end_node_count": len(deadends),
        "dead_end_node_ids": deadends,
        "isolated_single_edge_component_count": len(isolated_edges),
        "isolated_single_edge_component_ids": [item["component_id"] for item in isolated_edges],
        "default_speed_kmh": config.default_speed_kmh,
        "edge_travel_time_method": "length_m / configured default speed",
        "shortest_path_weight": "length_m",
        "shortest_travel_time_weight": "travel_time_s",
        "components": components,
    }
    return analysis, diagnostics, node_component, main_component


def _metric_demand_features(payload: Mapping[str, Any], config: RoadPlanningConfig) -> List[Dict[str, Any]]:
    transformer = _transformer(_payload_crs(payload, config.display_crs), config.metric_crs)
    output: List[Dict[str, Any]] = []
    for feature in sorted(
        payload.get("features", []),
        key=lambda item: str((item.get("properties") or {}).get("demand_id") or item.get("id") or ""),
    ):
        copied = {"properties": dict(feature.get("properties") or {}), "geometry": None}
        if feature.get("geometry"):
            geometry = shape(feature["geometry"])
            if geometry.geom_type == "Point" and not geometry.is_empty:
                copied["geometry"] = _transform(geometry, transformer)
        output.append(copied)
    return output


def _demand_accessibility(
    demands: Sequence[Dict[str, Any]],
    nodes: gpd.GeoDataFrame,
    graph: nx.Graph,
    node_component: Mapping[str, str],
) -> Tuple[Dict[str, Any], List[Point]]:
    located: List[Dict[str, Any]] = []
    for demand in demands:
        point = demand["geometry"]
        if point is None:
            continue
        node_id, _, connector_distance = _nearest_node(point, nodes)
        located.append(
            {
                **demand,
                "node_id": node_id,
                "component_id": node_component[node_id],
                "connector_distance_m": connector_distance,
            }
        )
    facilities = [item for item in located if item["properties"].get("demand_type") in FACILITY_TYPES]
    settlements = [item for item in located if item["properties"].get("demand_type") == "settlement"]
    records: List[Dict[str, Any]] = []
    detours: List[float] = []
    for settlement in settlements:
        alternatives: List[Tuple[float, float, str, Dict[str, Any]]] = []
        for facility in facilities:
            if settlement["component_id"] != facility["component_id"]:
                continue
            path_length = float(
                nx.shortest_path_length(
                    graph, settlement["node_id"], facility["node_id"], weight="length_m"
                )
            )
            travel_time = float(
                nx.shortest_path_length(
                    graph, settlement["node_id"], facility["node_id"], weight="travel_time_s"
                )
            )
            full_length = path_length + settlement["connector_distance_m"] + facility["connector_distance_m"]
            direct = float(settlement["geometry"].distance(facility["geometry"]))
            detour = full_length / direct if direct > 1e-6 else 1.0
            alternatives.append((travel_time, full_length, str(facility["properties"].get("demand_id")), {"facility": facility, "detour": detour}))
        properties = settlement["properties"]
        if not alternatives:
            records.append(
                {
                    "settlement_demand_id": properties.get("demand_id"),
                    "settlement_name": properties.get("name"),
                    "status": "unreachable_or_no_located_facility",
                    "nearest_facility_demand_id": None,
                    "shortest_path_length_m": None,
                    "shortest_travel_time_min": None,
                    "detour_ratio": None,
                }
            )
            continue
        travel_time, full_length, _, chosen = min(alternatives, key=lambda item: item[:3])
        facility = chosen["facility"]
        detours.append(float(chosen["detour"]))
        records.append(
            {
                "settlement_demand_id": properties.get("demand_id"),
                "settlement_name": properties.get("name"),
                "status": "reachable",
                "nearest_facility_demand_id": facility["properties"].get("demand_id"),
                "nearest_facility_name": facility["properties"].get("name"),
                "shortest_path_length_m": round(full_length, 3),
                "shortest_travel_time_min": round(travel_time / 60.0, 3),
                "detour_ratio": round(float(chosen["detour"]), 6),
            }
        )
    resolved = [item for item in demands if item["geometry"] is not None]
    connected = [item for item in resolved if item["properties"].get("network_status") == "connected"]
    isolated_settlements = [
        item["properties"].get("demand_id")
        for item in demands
        if item["properties"].get("demand_type") == "settlement"
        and item["properties"].get("network_status") in {"isolated", "unresolved"}
    ]
    report = {
        "demand_count": len(demands),
        "located_demand_count": len(resolved),
        "connected_located_demand_count": len(connected),
        "confirmed_location_service_coverage_ratio": round(len(connected) / len(resolved), 6) if resolved else None,
        "known_connected_share_of_all_demands": round(len(connected) / len(demands), 6) if demands else None,
        "coverage_denominator_warning": "Coverage among confirmed locations is unavailable until Stage 2.5 is completed." if not resolved else None,
        "located_settlement_count": len(settlements),
        "located_public_facility_count": len(facilities),
        "isolated_or_unresolved_settlement_ids": sorted(str(item) for item in isolated_settlements),
        "reachable_settlement_count": sum(item["status"] == "reachable" for item in records),
        "mean_detour_ratio": round(statistics.mean(detours), 6) if detours else None,
        "median_detour_ratio": round(statistics.median(detours), 6) if detours else None,
        "records": records,
    }
    return report, [item["geometry"] for item in resolved]


def _request(
    request_id: str,
    source_type: str,
    source_id: str,
    start: Point,
    end: Point,
    *,
    start_requires_network: bool,
    end_requires_network: bool,
    priority: str = "medium",
    requested_action: str = "new",
    planned_width_m: Optional[float] = None,
    access_point_count: int = 1,
    grouped_source_ids: Optional[Sequence[str]] = None,
    target_ids: Optional[Sequence[str]] = None,
    access_distance_m: Optional[float] = None,
) -> Dict[str, Any]:
    stable_target_ids = sorted({str(item) for item in (target_ids or []) if str(item)})
    request = {
        "request_id": request_id,
        "source_type": source_type,
        "source_id": source_id,
        "priority": priority,
        "start": start,
        "end": end,
        "start_requires_network": start_requires_network,
        "end_requires_network": end_requires_network,
        "requested_action": requested_action,
        "planned_width_m": planned_width_m,
        "access_point_count": access_point_count,
        "grouped_source_ids": list(grouped_source_ids or [source_id]),
        "target_ids": stable_target_ids,
        "access_distance_m": access_distance_m,
    }
    if len(stable_target_ids) == 1:
        request["target_id"] = stable_target_ids[0]
    return request


def _priority_rank(value: Any) -> int:
    return {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(str(value or "medium").lower(), 2)


def _access_cluster_requests(
    access_points: Sequence[Dict[str, Any]],
    edges: gpd.GeoDataFrame,
    config: RoadPlanningConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not access_points:
        return [], []
    grouped: Dict[Tuple[str, Optional[float]], List[Dict[str, Any]]] = {}
    for item in access_points:
        width = item.get("planned_width_m")
        width_key = round(float(width), 3) if isinstance(width, (int, float)) else None
        grouped.setdefault((str(item.get("requested_action") or "new"), width_key), []).append(item)

    requests: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    cluster_index = 0
    for (action, _), items in sorted(grouped.items(), key=lambda entry: (entry[0][0], entry[0][1] or 0.0)):
        graph = nx.Graph()
        graph.add_nodes_from(range(len(items)))
        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                if items[left]["point"].distance(items[right]["point"]) <= config.access_cluster_distance_m:
                    graph.add_edge(left, right)
        components = sorted(
            (sorted(component) for component in nx.connected_components(graph)),
            key=lambda members: (min(str(items[index]["source_id"]) for index in members), len(members)),
        )
        for members in components:
            cluster_items = [items[index] for index in members]
            cluster_items.sort(key=lambda item: (_priority_rank(item.get("priority")), str(item.get("source_id"))))
            primary = cluster_items[0]
            points = [item["point"] for item in cluster_items]
            origin = points[0] if len(points) == 1 else MultiPoint(points).centroid
            target, access_distance = _nearest_road_point(origin, edges)
            source_ids = sorted(str(item["source_id"]) for item in cluster_items)
            target_ids = sorted({
                str(target_id)
                for item in cluster_items
                for target_id in item.get("target_ids") or []
                if str(target_id)
            })
            source_label = "+".join(source_ids[:4]) + (f"+{len(source_ids) - 4}more" if len(source_ids) > 4 else "")
            if access_distance < config.min_access_connector_length_m:
                blocked.append(
                    {
                        "source_type": "access_cluster" if len(cluster_items) > 1 else primary["source_type"],
                        "source_id": source_label,
                        "reason": "already_within_min_access_connector_length",
                        "nearest_distance_m": round(float(access_distance), 3),
                        "access_point_count": len(cluster_items),
                    }
                )
                continue
            cluster_index += 1
            source_type = str(primary["source_type"]) if len(cluster_items) == 1 else "access_cluster"
            source_id = str(primary["source_id"]) if len(cluster_items) == 1 else f"AC{cluster_index:04d}"
            requests.append(
                _request(
                    "",
                    source_type,
                    source_id,
                    origin,
                    target,
                    start_requires_network=False,
                    end_requires_network=True,
                    priority=str(primary.get("priority") or "medium"),
                    requested_action=action,
                    planned_width_m=primary.get("planned_width_m"),
                    access_point_count=len(cluster_items),
                    grouped_source_ids=source_ids,
                    target_ids=target_ids,
                    access_distance_m=round(float(access_distance), 3),
                )
            )
    requests.sort(
        key=lambda item: (
            _priority_rank(item.get("priority")),
            -int(item.get("access_point_count") or 1),
            item["source_type"],
            item["source_id"],
        )
    )
    return requests[: config.max_access_cluster_requests], blocked


def _candidate_requests(
    nodes: gpd.GeoDataFrame,
    edges: gpd.GeoDataFrame,
    graph: nx.Graph,
    node_component: Mapping[str, str],
    main_component: str,
    demands: Sequence[Dict[str, Any]],
    project_payload: Mapping[str, Any],
    project_endpoint_payload: Optional[Mapping[str, Any]],
    config: RoadPlanningConfig,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    node_points = {str(row["node_id"]): row.geometry for _, row in nodes.iterrows()}
    requests: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    access_points: List[Dict[str, Any]] = []

    deadend_options: List[Tuple[float, str, str]] = []
    for node_id in sorted(node for node, degree in graph.degree() if degree == 1):
        excluded = {node_id, *graph.neighbors(node_id)}
        choices = [
            (node_points[node_id].distance(point), other)
            for other, point in node_points.items()
            if other not in excluded
        ]
        if not choices:
            continue
        distance, target = min(choices, key=lambda item: (item[0], item[1]))
        if distance <= config.deadend_search_radius_m:
            deadend_options.append((float(distance), node_id, target))
        else:
            blocked.append({"source_type": "dead_end", "source_id": node_id, "reason": "no_other_road_within_search_radius", "nearest_distance_m": round(float(distance), 3)})
    for distance, node_id, target in sorted(deadend_options)[: config.max_deadend_requests]:
        requests.append(_request("", "dead_end", node_id, node_points[node_id], node_points[target], start_requires_network=True, end_requires_network=True))

    main_nodes = sorted(node for node, component in node_component.items() if component == main_component)
    component_options: List[Tuple[float, str, str, str]] = []
    for component in sorted(set(node_component.values()) - {main_component}):
        members = sorted(node for node, value in node_component.items() if value == component)
        distance, left, right = min(
            (node_points[left].distance(node_points[right]), left, right)
            for left in members
            for right in main_nodes
        )
        if distance <= config.component_search_radius_m:
            component_options.append((float(distance), component, left, right))
        else:
            blocked.append({"source_type": "component_connection", "source_id": component, "reason": "main_component_beyond_search_radius", "nearest_distance_m": round(float(distance), 3)})
    for _, component, left, right in sorted(component_options)[: config.max_component_requests]:
        requests.append(_request("", "component_connection", component, node_points[left], node_points[right], start_requires_network=True, end_requires_network=True, priority="high"))

    for demand in demands:
        props, point = demand["properties"], demand["geometry"]
        demand_id = str(props.get("demand_id") or "")
        status = props.get("network_status")
        if point is None:
            blocked.append({"source_type": "demand_connection", "source_id": demand_id, "reason": "unresolved_location"})
        elif status in {"near_network", "isolated"}:
            access_points.append(
                {
                    "source_type": "isolated_demand" if status == "isolated" else "near_network_demand",
                    "source_id": demand_id,
                    "point": point,
                    "priority": str(props.get("priority") or "medium"),
                    "requested_action": "new",
                    "planned_width_m": None,
                }
            )

    endpoint_index: Dict[Tuple[str, str], Point] = {}
    if project_endpoint_payload:
        source_crs = _payload_crs(project_endpoint_payload, config.display_crs)
        transformer = _transformer(source_crs, config.metric_crs)
        for feature in project_endpoint_payload.get("features", []):
            props = feature.get("properties") or {}
            if feature.get("geometry"):
                endpoint_index[(str(props.get("project_id")), str(props.get("endpoint")))] = _transform(shape(feature["geometry"]), transformer)
    for project in sorted(project_payload.get("projects", []), key=lambda item: str(item.get("project_id") or "")):
        project_id = str(project.get("project_id") or "")
        project_target_ids = sorted({
            str(item)
            for item in (project.get("target_ids") or [project.get("target_id")])
            if str(item or "")
        })
        start = endpoint_index.get((project_id, "start"))
        end = endpoint_index.get((project_id, "end"))
        if project.get("action") == "new":
            if start is not None and end is not None:
                requests.append(_request("", "text_new_road", project_id, start, end, start_requires_network=False, end_requires_network=False, priority=str(project.get("priority") or "medium"), requested_action="new", planned_width_m=project.get("min_width_m"), target_ids=project_target_ids))
            else:
                blocked.append({"source_type": "text_new_road", "source_id": project_id, "reason": "unresolved_start_or_end"})
        for side, point in (("start", start), ("end", end)):
            binding = project.get(f"{side}_network_binding") or {}
            if point is not None and binding.get("network_status") in {"near_network", "isolated"}:
                access_points.append(
                    {
                        "source_type": "project_point",
                        "source_id": f"{project_id}:{side}",
                        "point": point,
                        "priority": str(project.get("priority") or "medium"),
                        "requested_action": str(project.get("action") or "new"),
                        "planned_width_m": project.get("min_width_m"),
                        "target_ids": project_target_ids,
                    }
                )

    access_requests, access_blocked = _access_cluster_requests(access_points, edges, config)
    requests.extend(access_requests)
    blocked.extend(access_blocked)

    unique: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for item in requests:
        key = (
            item["source_type"], item["source_id"], item.get("requested_action"),
            round(item["start"].x, 3), round(item["start"].y, 3),
            round(item["end"].x, 3), round(item["end"].y, 3),
        )
        unique.setdefault(key, item)
    ordered = sorted(unique.values(), key=lambda item: (item["source_type"], item["source_id"], item["start"].x, item["start"].y))
    for index, item in enumerate(ordered, 1):
        item["request_id"] = f"RQ{index:04d}"
    blocked.sort(key=lambda item: (item["source_type"], item["source_id"], item["reason"]))
    return ordered, blocked


def _route_family(start: Point, end: Point, config: RoadPlanningConfig) -> List[LineString]:
    dx, dy = end.x - start.x, end.y - start.y
    distance = math.hypot(dx, dy)
    if distance <= 1e-6:
        return []
    nx_offset, ny_offset = -dy / distance, dx / distance
    offset = min(config.alternative_offset_cap_m, distance * config.alternative_offset_ratio)
    mid_x, mid_y = (start.x + end.x) / 2.0, (start.y + end.y) / 2.0
    routes = [LineString([start, end])]
    for factor in (1.0, -1.0, 0.5, -0.5):
        waypoint = (mid_x + nx_offset * offset * factor, mid_y + ny_offset * offset * factor)
        routes.append(LineString([start, waypoint, end]))
    for factor in (1.0, -1.0):
        first = (start.x + dx / 3.0 + nx_offset * offset * factor, start.y + dy / 3.0 + ny_offset * offset * factor)
        second = (start.x + dx * 2.0 / 3.0 + nx_offset * offset * factor, start.y + dy * 2.0 / 3.0 + ny_offset * offset * factor)
        routes.append(LineString([start, first, second, end]))
    return routes


def _land_weight(value: Any, code: Any = None) -> float:
    code_text = str(code or "")
    if code_text == "2126" or code_text.startswith("22"):
        return 0.5
    if code_text.startswith("31"):
        return 50.0
    if code_text in {"2121", "2122", "2124", "2125"}:
        return 10.0
    if code_text.startswith(("11", "12")):
        return 6.0
    if code_text.startswith("13"):
        return 3.0
    if code_text.startswith("14"):
        return 2.5
    text = str(value or "")
    if "道路" in text or "交通" in text:
        return 0.5
    if "水域" in text:
        return 50.0
    if any(token in text for token in ("宅基地", "住宅", "商业", "工矿", "工业", "公共管理")):
        return 10.0
    if any(token in text for token in ("耕地", "园地")):
        return 6.0
    if any(token in text for token in ("林地", "草地")):
        return 3.0
    return 2.0


def _line_land_cost(line: LineString, landuse: gpd.GeoDataFrame) -> float:
    total = 0.0
    for index in landuse.sindex.query(line, predicate="intersects"):
        row = landuse.iloc[int(index)]
        length = float(line.intersection(row.geometry).length)
        total += length * _land_weight(
            row.get("DLMC") or row.get("SDDLMC"),
            row.get("DLBM") or row.get("SDDLBM"),
        )
    return total


def _intersection_length(line: LineString, geometry: Any) -> float:
    return 0.0 if geometry is None or geometry.is_empty else float(line.intersection(geometry).length)


def _minimum_turn_angle(line: LineString) -> float:
    coordinates = list(line.coords)
    if len(coordinates) < 3:
        return 180.0
    values: List[float] = []
    for index in range(1, len(coordinates) - 1):
        previous, current, following = coordinates[index - 1], coordinates[index], coordinates[index + 1]
        left = (previous[0] - current[0], previous[1] - current[1])
        right = (following[0] - current[0], following[1] - current[1])
        denominator = math.hypot(*left) * math.hypot(*right)
        if denominator <= 1e-9:
            continue
        cosine = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / denominator))
        values.append(math.degrees(math.acos(cosine)))
    return min(values, default=180.0)


def _constraint_context(config: RoadPlanningConfig) -> Dict[str, Any]:
    boundary = gpd.read_file(config.boundary_path).to_crs(config.metric_crs)
    landuse = gpd.read_file(config.landuse_path).to_crs(config.metric_crs)
    invalid_boundary_count = int((~boundary.geometry.is_valid).sum())
    invalid_landuse_count = int((~landuse.geometry.is_valid).sum())
    if invalid_boundary_count:
        boundary["geometry"] = boundary.geometry.map(
            lambda geometry: make_valid(geometry) if geometry is not None and not geometry.is_valid else geometry
        )
    if invalid_landuse_count:
        landuse["geometry"] = landuse.geometry.map(
            lambda geometry: make_valid(geometry) if geometry is not None and not geometry.is_valid else geometry
        )
    constraints_payload = _read_json(config.stage3_dir / "spatial_constraints.geojson")
    transformer = _transformer(_payload_crs(constraints_payload, config.display_crs), config.metric_crs)
    by_target: Dict[str, List[Any]] = {}
    for feature in constraints_payload.get("features", []):
        target = str((feature.get("properties") or {}).get("target_layer") or "")
        if feature.get("geometry"):
            by_target.setdefault(target, []).append(_transform(shape(feature["geometry"]), transformer))
    constraint_unions = {target: unary_union(geometries) for target, geometries in by_target.items()}
    building_mask = None
    name_field = "DLMC" if "DLMC" in landuse.columns else ("SDDLMC" if "SDDLMC" in landuse.columns else None)
    if name_field:
        mask = landuse[name_field].astype(str).str.contains("宅基地|住宅|商业|工矿|工业|公共管理", regex=True, na=False)
        if mask.any():
            building_mask = unary_union(list(landuse.loc[mask].geometry))
    code_field = "DLBM" if "DLBM" in landuse.columns else ("SDDLBM" if "SDDLBM" in landuse.columns else None)
    if code_field:
        codes = landuse[code_field].fillna("").astype(str)
        # Coarse construction parcels are a high-cost conflict layer, not
        # surveyed building footprints.  Keep access into settlements possible.
        construction_mask = codes.isin({"2121", "2122", "2124", "2125"})
        building_mask = (
            unary_union(list(landuse.loc[construction_mask].geometry))
            if construction_mask.any()
            else None
        )
    building_footprints_are_hard = False
    if config.building_footprints_path is not None:
        footprint_frame = gpd.read_file(config.building_footprints_path).to_crs(config.metric_crs)
        footprints = footprint_frame.geometry[
            footprint_frame.geometry.notna() & ~footprint_frame.geometry.is_empty
        ]
        building_mask = unary_union(list(footprints)) if len(footprints) else None
        building_footprints_are_hard = True
    hazards = None
    if config.hazard_points_path is not None:
        hazard_frame = gpd.read_file(config.hazard_points_path).to_crs(config.metric_crs)
        valid = hazard_frame.geometry[hazard_frame.geometry.notna() & ~hazard_frame.geometry.is_empty]
        if len(valid):
            hazards = unary_union(list(valid))
    return {
        "boundary": unary_union(list(boundary.geometry)),
        "landuse": landuse,
        "constraints": constraint_unions,
        "buildings": building_mask,
        "building_footprints_are_hard": building_footprints_are_hard,
        "hazards": hazards,
        "geometry_repairs": {
            "boundary_invalid_repaired": invalid_boundary_count,
            "landuse_invalid_repaired": invalid_landuse_count,
        },
    }


def _environment_score(line: LineString, context: Mapping[str, Any], config: RoadPlanningConfig) -> float:
    weights = {"water": 10000.0, "ecological_protection": 10000.0, "farmland_protection": 5000.0, "historical_protection": 8000.0}
    score = sum(_intersection_length(line, context["constraints"].get(target)) * weight for target, weight in weights.items())
    hazards = context.get("hazards")
    if hazards is not None and not hazards.is_empty:
        distance = float(line.distance(hazards))
        score += max(0.0, config.hazard_screening_distance_m - distance) * 100.0
    return score


def _screen_candidate(
    line: LineString,
    request: Mapping[str, Any],
    roads_union: Any,
    service_union: Any,
    context: Mapping[str, Any],
    config: RoadPlanningConfig,
    impact_geometry: Any = None,
    engineering: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    checked_geometry = impact_geometry if impact_geometry is not None else line
    checks: Dict[str, Any] = {}
    hard_violations: List[str] = []
    warnings: List[str] = []
    for target, check_name in HARD_CONSTRAINT_TARGETS.items():
        length = _intersection_length(checked_geometry, context["constraints"].get(target))
        value = length > 0.01
        checks[check_name] = value
        checks[f"{check_name}_length_m"] = round(length, 3)
        if value:
            hard_violations.append(check_name)
    building_length = _intersection_length(checked_geometry, context.get("buildings"))
    checks["crosses_existing_building_land"] = building_length > 0.01
    checks["existing_building_land_intersection_m"] = round(building_length, 3)
    if checks["crosses_existing_building_land"]:
        if context.get("building_footprints_are_hard"):
            hard_violations.append("crosses_building_footprint")
        else:
            warnings.append("crosses_mapped_construction_land_no_building_footprints")
    boundary = context["boundary"]
    outside_length = float(checked_geometry.difference(boundary).length) if not boundary.covers(checked_geometry) else 0.0
    checks["outside_village_boundary"] = outside_length > 0.01
    checks["outside_boundary_length_m"] = round(outside_length, 3)
    if checks["outside_village_boundary"]:
        hard_violations.append("outside_village_boundary")
    start_distance = float(Point(line.coords[0]).distance(roads_union))
    end_distance = float(Point(line.coords[-1]).distance(roads_union))
    start_ok = start_distance <= config.network_connection_tolerance_m
    end_ok = end_distance <= config.network_connection_tolerance_m
    required_ok = (start_ok or not request["start_requires_network"]) and (end_ok or not request["end_requires_network"])
    at_least_one = start_ok or end_ok
    checks.update({
        "start_distance_to_current_road_m": round(start_distance, 3),
        "end_distance_to_current_road_m": round(end_distance, 3),
        "current_network_connection_count": int(start_ok) + int(end_ok),
        "network_connection_valid": required_ok and at_least_one,
    })
    if not checks["network_connection_valid"]:
        hard_violations.append("invalid_current_network_connection")
    minimum_angle = _minimum_turn_angle(line)
    checks["minimum_turn_angle_deg"] = round(minimum_angle, 3)
    checks["has_unreasonable_sharp_turn"] = minimum_angle < config.sharp_turn_angle_deg
    if checks["has_unreasonable_sharp_turn"]:
        warnings.append("unreasonable_sharp_turn")
    hazards = context.get("hazards")
    hazard_distance = float(checked_geometry.distance(hazards)) if hazards is not None and not hazards.is_empty and not checked_geometry.is_empty else None
    checks["distance_to_nearest_hazard_m"] = round(hazard_distance, 3) if hazard_distance is not None else None
    checks["near_geological_hazard"] = hazard_distance is not None and hazard_distance < config.hazard_screening_distance_m
    if checks["near_geological_hazard"]:
        warnings.append("near_geological_hazard")
    if engineering:
        checks.update(
            {
                "maximum_grade_percent": engineering.get("maximum_grade_percent"),
                "maximum_cross_slope_deg": engineering.get("maximum_cross_slope_deg"),
                "minimum_curve_radius_m": engineering.get("minimum_curve_radius_m"),
            }
        )
        if not bool(engineering.get("terrain_data_complete", True)):
            hard_violations.append("terrain_data_incomplete")
        if float(engineering.get("maximum_grade_percent") or 0.0) > config.terrain_max_grade_percent:
            hard_violations.append("maximum_grade_exceeded")
        radius = engineering.get("minimum_curve_radius_m")
        if radius is not None and float(radius) < config.minimum_curve_radius_m:
            hard_violations.append("minimum_curve_radius_not_met")
    if service_union is None or service_union.is_empty:
        checks["long_unserved_check_status"] = "unavailable_no_confirmed_service_points"
        checks["maximum_unserved_segment_m"] = None
    else:
        uncovered = line.difference(service_union.buffer(config.service_buffer_m))
        pieces = list(uncovered.geoms) if hasattr(uncovered, "geoms") else [uncovered]
        maximum = max((float(item.length) for item in pieces if not item.is_empty), default=0.0)
        checks["long_unserved_check_status"] = "checked"
        checks["maximum_unserved_segment_m"] = round(maximum, 3)
        if maximum > config.long_unserved_threshold_m:
            warnings.append("long_unserved_segment")
    status = "rejected_hard_constraint" if hard_violations else ("feasible_with_warnings" if warnings else "feasible")
    return {"screening_status": status, "hard_violations": sorted(set(hard_violations)), "warnings": sorted(set(warnings)), "checks": checks}


def _generate_candidates(
    requests: Sequence[Dict[str, Any]],
    edges: gpd.GeoDataFrame,
    service_points: Sequence[Point],
    context: Mapping[str, Any],
    config: RoadPlanningConfig,
    terrain: Optional[TerrainContext] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    roads_union = unary_union(list(edges.geometry))
    service_union = unary_union(list(service_points)) if service_points else None
    to_display = _transformer(config.metric_crs, config.display_crs)
    features: List[Dict[str, Any]] = []
    evaluations: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []
    candidate_index = 0
    for request in requests:
        if terrain is not None:
            terrain_routes = generate_least_cost_routes(
                request["start"],
                request["end"],
                terrain,
                preferred_slope_deg=config.terrain_preferred_slope_deg,
                hazard_distance_m=config.hazard_screening_distance_m,
                maximum_grade_percent=config.terrain_max_grade_percent,
            )
            selections = []
            for index, route in enumerate(terrain_routes):
                line = route["line"]
                selections.append(
                    (
                        route["strategy"],
                        {
                            "family_index": index,
                            "line": line,
                            "length": float(line.length),
                            "land_cost": _line_land_cost(line, context["landuse"]),
                            "environment": _environment_score(line, context, config),
                            "terrain": route,
                        },
                    )
                )
        else:
            routes = _route_family(request["start"], request["end"], config)
            scored = []
            for index, line in enumerate(routes):
                scored.append({
                    "family_index": index,
                    "line": line,
                    "length": float(line.length),
                    "land_cost": _line_land_cost(line, context["landuse"]),
                    "environment": _environment_score(line, context, config),
                    "terrain": None,
                })
            selections = []
            used: set[int] = set()
            for strategy, sort_key in (
                ("shortest_distance", lambda item: (item["length"], item["family_index"])),
                ("lowest_land_cost", lambda item: (item["land_cost"], item["length"], item["family_index"])),
                ("minimum_environmental_impact", lambda item: (item["environment"], item["land_cost"], item["length"], item["family_index"])),
            ):
                remaining = [item for item in scored if item["family_index"] not in used]
                if not remaining:
                    break
                chosen = min(remaining, key=sort_key)
                used.add(chosen["family_index"])
                selections.append((strategy, chosen))
        for strategy, chosen in selections:
            candidate_index += 1
            candidate_id = f"CR{candidate_index:05d}"
            planned_width = float(request.get("planned_width_m") or config.default_planned_road_width_m)
            impact = route_impact_metrics(
                chosen["line"],
                roads_union,
                requested_action=str(request.get("requested_action") or "new"),
                planned_width_m=planned_width,
                existing_width_m=config.assumed_existing_road_width_m,
                road_buffer_m=config.existing_road_buffer_m,
            )
            terrain_route = chosen.get("terrain") or {}
            engineering = terrain_route.get("engineering")
            screening = _screen_candidate(
                chosen["line"], request, roads_union, service_union, context, config,
                impact_geometry=impact["new_geometry"], engineering=engineering,
            )
            properties = {
                "candidate_id": candidate_id,
                "request_id": request["request_id"],
                "source_type": request["source_type"],
                "source_id": request["source_id"],
                "priority": request["priority"],
                "strategy": strategy,
                "length_m": round(chosen["length"], 3),
                "land_cost_score": round(chosen["land_cost"], 3),
                "environmental_impact_score": round(chosen["environment"], 3),
                "screening_status": screening["screening_status"],
                "hard_violation_count": len(screening["hard_violations"]),
                "warning_count": len(screening["warnings"]),
                "hard_violations": screening["hard_violations"],
                "warnings": screening["warnings"],
                "is_construction_design": False,
                "routing_method": "raster_least_cost_path" if terrain is not None else "geometric_corridor_family",
                "requested_action": str(request.get("requested_action") or "new"),
                "access_point_count": int(request.get("access_point_count") or 1),
                "grouped_source_ids": request.get("grouped_source_ids") or [request["source_id"]],
                "target_ids": request.get("target_ids") or [],
                "access_distance_m": request.get("access_distance_m"),
                **{key: value for key, value in impact.items() if not key.endswith("_geometry")},
            }
            if request.get("target_id"):
                properties["target_id"] = request["target_id"]
            if terrain_route:
                properties.update(
                    {
                        "least_cost_value": terrain_route["least_cost_value"],
                        "raw_grid_length_m": terrain_route["raw_grid_length_m"],
                        "smoothing_applied": terrain_route["smoothing_applied"],
                        "slope_cost": engineering.get("mean_cross_slope_deg"),
                        "start_cell_adjustment_m": terrain_route.get("start_cell_adjustment_m"),
                        "end_cell_adjustment_m": terrain_route.get("end_cell_adjustment_m"),
                        **engineering,
                    }
                )
            features.append({"type": "Feature", "id": candidate_id, "geometry": mapping(_transform(chosen["line"], to_display)), "properties": properties})
            evaluations.append({**properties, "checks": screening["checks"]})
            segment_index = 0
            action = str(request.get("requested_action") or "new").lower()
            existing_action = action if action in {"widen", "harden"} else "reuse_existing"
            for geometry, construction_action in (
                (impact["new_geometry"], "new"),
                (impact["existing_geometry"], existing_action),
            ):
                for part in line_parts(geometry):
                    if part.length <= 0.01:
                        continue
                    segment_index += 1
                    segments.append(
                        {
                            "type": "Feature",
                            "id": f"{candidate_id}-S{segment_index:03d}",
                            "geometry": mapping(_transform(part, to_display)),
                            "properties": {
                                "segment_id": f"{candidate_id}-S{segment_index:03d}",
                                "candidate_id": candidate_id,
                                "request_id": request["request_id"],
                                "strategy": strategy,
                                "construction_action": construction_action,
                                "length_m": round(float(part.length), 3),
                                "planned_width_m": planned_width,
                                "access_point_count": int(request.get("access_point_count") or 1),
                                "target_ids": request.get("target_ids") or [],
                                **({"target_id": request["target_id"]} if request.get("target_id") else {}),
                            },
                        }
                    )
    return features, evaluations, segments


def run_stage4_road_planning(config: RoadPlanningConfig) -> RoadPlanningResult:
    """Run deterministic Stage-4 analysis, generation, and constraint screening."""

    config.validate()
    nodes, edges, graph = _load_network(config)
    network, diagnostics, node_component, main_component = _network_analysis(nodes, edges, graph, config)
    demand_payload = _read_json(config.stage3_dir / "demand_network_binding.geojson")
    stage3_report_path = config.stage3_dir / "stage3_report.json"
    stage3_report = _read_json(stage3_report_path) if stage3_report_path.exists() else {}
    data_mode = stage3_report.get("data_mode", demand_payload.get("data_mode", "production"))
    stage3_gate = stage3_report.get("planning_gate")
    stage3_gate_available = isinstance(stage3_gate, Mapping) and "automatic_route_generation_allowed" in stage3_gate
    automatic_route_generation_allowed = (
        bool(stage3_gate.get("automatic_route_generation_allowed"))
        if stage3_gate_available
        else True
    )
    stage3_gate_reason = (
        str(stage3_gate.get("reason") or "Stage 3 planning gate blocked automatic route generation.")
        if stage3_gate_available and not automatic_route_generation_allowed
        else None
    )
    demands = _metric_demand_features(demand_payload, config)
    accessibility, service_points = _demand_accessibility(demands, nodes, graph, node_component)
    projects = _read_json(config.stage3_dir / "road_project_spatial_binding.json")
    endpoint_path = config.stage3_dir / "road_project_endpoints.geojson"
    endpoint_payload = _read_json(endpoint_path) if endpoint_path.exists() else None
    requests, blocked = _candidate_requests(nodes, edges, graph, node_component, main_component, demands, projects, endpoint_payload, config)
    pre_gate_candidate_request_count = len(requests)
    if not automatic_route_generation_allowed:
        blocked.extend(
            {
                "source_type": request["source_type"],
                "source_id": request["source_id"],
                "request_id": request["request_id"],
                "reason": "stage3_planning_gate_blocked",
                "planning_gate_reason": stage3_gate_reason,
            }
            for request in requests
        )
        requests = []
    blocked.sort(
        key=lambda item: (
            str(item.get("source_type") or ""),
            str(item.get("source_id") or ""),
            str(item.get("reason") or ""),
        )
    )
    context = _constraint_context(config)
    roads_union = unary_union(list(edges.geometry))
    terrain = None
    if config.dem_grid_path is not None:
        terrain = load_terrain_context(
            config.dem_grid_path,
            constraints=context["constraints"],
            buildings=context.get("buildings"),
            hazards=context.get("hazards"),
            roads_union=roads_union,
            max_slope_deg=config.terrain_max_slope_deg,
            existing_road_buffer_m=config.existing_road_buffer_m,
            hazard_screening_distance_m=config.hazard_screening_distance_m,
            block_buildings=context.get("building_footprints_are_hard", False),
        )
    candidates, evaluations, segments = _generate_candidates(
        requests, edges, service_points, context, config, terrain
    )
    for feature in candidates:
        feature["properties"]["data_mode"] = data_mode
    for evaluation in evaluations:
        evaluation["data_mode"] = data_mode
    for segment in segments:
        segment["properties"]["data_mode"] = data_mode

    status_counts = Counter(item["screening_status"] for item in evaluations)
    source_counts = Counter(item["source_type"] for item in evaluations)
    strategy_counts = Counter(item["strategy"] for item in evaluations)
    report = {
        "schema_version": SCHEMA_VERSION,
        "data_mode": data_mode,
        "stage": "stage4_corridor_planning",
        "network_analysis": network,
        "accessibility_summary": {key: value for key, value in accessibility.items() if key != "records"},
        "stage3_planning_gate": {
            "available": stage3_gate_available,
            "automatic_route_generation_allowed": automatic_route_generation_allowed,
            "reason": stage3_gate_reason,
            "fallback": "allowed_for_legacy_stage3_output_without_gate"
            if not stage3_gate_available
            else None,
        },
        "pre_gate_candidate_request_count": pre_gate_candidate_request_count,
        "gate_blocked_candidate_request_count": (
            pre_gate_candidate_request_count if not automatic_route_generation_allowed else 0
        ),
        "candidate_request_count": len(requests),
        "blocked_request_count": len(blocked),
        "candidate_count": len(candidates),
        "candidate_status_counts": dict(sorted(status_counts.items())),
        "candidate_source_counts": dict(sorted(source_counts.items())),
        "candidate_strategy_counts": dict(sorted(strategy_counts.items())),
        "parameters": {
            "metric_crs": config.metric_crs,
            "display_crs": config.display_crs,
            "default_speed_kmh": config.default_speed_kmh,
            "deadend_search_radius_m": config.deadend_search_radius_m,
            "component_search_radius_m": config.component_search_radius_m,
            "access_cluster_distance_m": config.access_cluster_distance_m,
            "min_access_connector_length_m": config.min_access_connector_length_m,
            "hazard_screening_distance_m": config.hazard_screening_distance_m,
            "sharp_turn_angle_deg": config.sharp_turn_angle_deg,
            "service_buffer_m": config.service_buffer_m,
            "long_unserved_threshold_m": config.long_unserved_threshold_m,
            "routing_method": "raster_least_cost_path" if terrain is not None else "geometric_corridor_family",
            "terrain_max_slope_deg": config.terrain_max_slope_deg if terrain is not None else None,
            "terrain_preferred_slope_deg": config.terrain_preferred_slope_deg if terrain is not None else None,
            "terrain_max_grade_percent": config.terrain_max_grade_percent if terrain is not None else None,
            "minimum_curve_radius_m": config.minimum_curve_radius_m if terrain is not None else None,
            "existing_road_buffer_m": config.existing_road_buffer_m,
            "assumed_existing_road_width_m": config.assumed_existing_road_width_m,
        },
        "geometry_repairs": context["geometry_repairs"],
        "input_roles": {
            "road_nodes": _relative(config.road_nodes_path),
            "road_edges": _relative(config.road_edges_path),
            "stage3": _relative(config.stage3_dir),
            "boundary": _relative(config.boundary_path),
            "landuse": _relative(config.landuse_path),
            "hazard_points": _relative(config.hazard_points_path) if config.hazard_points_path else None,
            "dem_grid": _relative(config.dem_grid_path) if config.dem_grid_path else None,
            "building_footprints": _relative(config.building_footprints_path) if config.building_footprints_path else None,
        },
        "stage2_5_gate": {
            "located_demand_count": accessibility["located_demand_count"],
            "unresolved_demand_count": accessibility["demand_count"] - accessibility["located_demand_count"],
            "message": "Stage 4 only generates candidate geometries when the Stage 3 planning gate allows it.",
        },
        "leakage_guard": {
            "planned_road_read": False,
            "planned_landuse_read": False,
            "rule": "Stage 4 accepts Stage-1 current roads and Stage-3 constraints, never the held-out manual planned road.",
        },
        "limitations": [
            "Terrain-aware routes are planning-level alignments, not construction drawings.",
            "SRTM resolution and proxy locations support software testing, not survey, earthwork, drainage, bridge, or approval design.",
            "Curve-radius and grade checks are grid-derived screening indicators and require engineering survey verification.",
        ] if terrain is not None else [
            "No DEM grid was supplied; outputs are geometric corridor concepts rather than terrain-aware alignments.",
            "Land cost is a planning score rather than construction cost.",
        ],
        "reproducibility": {
            "deterministic": True,
            "timestamps_in_outputs": False,
            "candidate_id_rule": "requests and strategies sorted deterministically",
        },
    }

    output = config.output_dir
    output.mkdir(parents=True, exist_ok=True)
    network_path = output / "current_network_analysis.json"
    diagnostics_path = output / "network_diagnostics.geojson"
    accessibility_path = output / "demand_facility_accessibility.json"
    candidates_path = output / "candidate_roads.geojson"
    segments_path = output / "candidate_route_segments.geojson"
    evaluations_path = output / "candidate_evaluations.json"
    blocked_path = output / "blocked_candidate_requests.json"
    preview_path = output / "stage4_preview.geojson"
    report_path = output / "stage4_report.json"
    _write_json(network_path, {"schema_version": SCHEMA_VERSION, **network})
    _write_json(diagnostics_path, _feature_collection("network_diagnostics", config.display_crs, diagnostics))
    _write_json(accessibility_path, {"schema_version": SCHEMA_VERSION, **accessibility})
    _write_json(candidates_path, _feature_collection("candidate_roads", config.display_crs, candidates))
    _write_json(segments_path, _feature_collection("candidate_route_segments", config.display_crs, segments))
    _write_json(evaluations_path, {"schema_version": SCHEMA_VERSION, "evaluations": evaluations})
    _write_json(blocked_path, {"schema_version": SCHEMA_VERSION, "blocked_requests": blocked})
    preview = []
    for feature in diagnostics:
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["preview_role"] = "network_diagnostic"
        preview.append(copied)
    for feature in candidates:
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["preview_role"] = "candidate_road"
        preview.append(copied)
    _write_json(preview_path, _feature_collection("stage4_preview", config.display_crs, preview))
    _write_json(report_path, report)
    return RoadPlanningResult(
        output_dir=output,
        network_analysis_path=network_path,
        diagnostics_path=diagnostics_path,
        accessibility_path=accessibility_path,
        candidates_path=candidates_path,
        segments_path=segments_path,
        evaluations_path=evaluations_path,
        blocked_requests_path=blocked_path,
        preview_path=preview_path,
        report_path=report_path,
        report=report,
    )


class RoadPlanner:
    """Small object-oriented wrapper for API callers."""

    def __init__(self, config: RoadPlanningConfig) -> None:
        self.config = config

    def plan(self) -> RoadPlanningResult:
        return run_stage4_road_planning(self.config)


__all__ = ["RoadPlanner", "run_stage4_road_planning"]
