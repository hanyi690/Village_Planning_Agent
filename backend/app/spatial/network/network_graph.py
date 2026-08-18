"""Immutable, deterministic road-network snapshots for planning relations.

The planning workflow must never infer service from a straight-line distance to
an existing facility.  This module turns authoritative road features into a
small in-memory graph and exposes the same graph for service, access and
connectivity measurements.  It intentionally keeps the graph independent of
the delivery/workflow layers so that an evaluator can be replayed from its
fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform

NetworkImpedance = Literal["distance_m", "travel_time_min"]


def _geometry(value: Any):
    raw = getattr(value, "geometry", None)
    if raw is None:
        raw = getattr(value, "geometry_wkt", None)
    if raw is None and isinstance(value, Mapping):
        raw = value.get("geometry", value)
    if raw is None and hasattr(value, "geom_type"):
        raw = value
    if isinstance(raw, str):
        from shapely import wkt

        return wkt.loads(raw)
    return shape(raw) if isinstance(raw, Mapping) else raw


def _crs(value: Any, default: str) -> str:
    candidate = getattr(value, "crs", None)
    if candidate:
        return str(candidate)
    if isinstance(value, Mapping):
        candidate = value.get("crs") or (value.get("properties") or {}).get("crs")
        if isinstance(candidate, Mapping):
            candidate = (candidate.get("properties") or {}).get("name")
        if candidate:
            return str(candidate)
    return default


def _as_lines(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return [item for item in geometry.geoms if not item.is_empty]
    return []


@dataclass(frozen=True)
class NetworkNode:
    node_id: str
    x: float
    y: float
    component_id: str


@dataclass(frozen=True)
class NetworkEdge:
    edge_id: str
    from_node: str
    to_node: str
    length_m: float
    travel_time_min: float


@dataclass(frozen=True)
class NetworkRoute:
    reachable: bool
    distance_m: float | None = None
    travel_time_min: float | None = None
    component_ids: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class NetworkGraphSnapshot:
    """Frozen metadata plus a private graph used for deterministic routing."""

    network_ref: str
    impedance: NetworkImpedance
    crs: str
    metric_crs: str
    snap_tolerance_m: float
    default_speed_kmh: float
    nodes: tuple[NetworkNode, ...]
    edges: tuple[NetworkEdge, ...]
    fingerprint: str
    _graph: Any = field(repr=False, compare=False, default=None)
    _node_points: Mapping[str, Point] = field(repr=False, compare=False, default_factory=dict)

    def nearest_node(self, point: Any) -> tuple[str, float] | None:
        """Return the nearest graph node and connector distance in metres."""

        metric_point = self._metric_point(point)
        if metric_point is None or not self.nodes:
            return None
        node = min(
            self.nodes,
            key=lambda item: (metric_point.distance(self._node_points[item.node_id]), item.node_id),
        )
        return node.node_id, float(metric_point.distance(self._node_points[node.node_id]))

    def route(self, start: Any, end: Any) -> NetworkRoute:
        """Route two feature geometries through the graph.

        A point is connected to its nearest node.  A connector may be longer
        than the configured snap tolerance, but it is included in the metric;
        disconnected graph components remain unreachable even when their
        Euclidean distance is small.
        """

        if self._graph is None:
            return NetworkRoute(False, diagnostics=("network_graph_unavailable",))
        left = self.nearest_node(start)
        right = self.nearest_node(end)
        if left is None or right is None:
            return NetworkRoute(False, diagnostics=("network_endpoint_unresolved",))
        left_id, left_connector = left
        right_id, right_connector = right
        if not nx.has_path(self._graph, left_id, right_id):
            return NetworkRoute(
                False,
                diagnostics=("network_components_disconnected",),
                component_ids=(
                    self._graph.nodes[left_id].get("component_id", ""),
                    self._graph.nodes[right_id].get("component_id", ""),
                ),
            )
        distance = float(nx.shortest_path_length(self._graph, left_id, right_id, weight="length_m"))
        travel = float(nx.shortest_path_length(self._graph, left_id, right_id, weight="travel_time_min"))
        distance += left_connector + right_connector
        speed = self.default_speed_kmh * 1000.0 / 60.0
        travel += (left_connector + right_connector) / speed if speed > 0 else 0.0
        return NetworkRoute(
            True,
            distance_m=distance,
            travel_time_min=travel,
            component_ids=(self._graph.nodes[left_id].get("component_id", ""),),
        )

    def _metric_point(self, value: Any) -> Point | None:
        geometry = _geometry(value)
        if geometry is None or geometry.is_empty:
            return None
        if geometry.geom_type != "Point":
            geometry = geometry.representative_point()
        source = _crs(value, self.crs)
        try:
            if source.upper() == self.metric_crs.upper():
                return geometry
            converter = Transformer.from_crs(source, self.metric_crs, always_xy=True)
            return transform(converter.transform, geometry)
        except Exception:
            return None

    def evaluate_relation(self, key: str, subject: Any, object_: Any, factor: Any = None) -> Any:
        route = self.route(subject, object_)
        if key in {"connect", "connect_network"}:
            return {"value": route.reachable, "route": route}
        if key in {"access_via", "provide_access"}:
            return {"value": route.travel_time_min if route.reachable else None, "route": route}
        return None


def build_network_graph(
    road_features: Sequence[Any],
    *,
    impedance: NetworkImpedance,
    network_ref: str = "network:road:default",
    source_crs: str = "EPSG:4326",
    metric_crs: str = "EPSG:3857",
    snap_tolerance_m: float = 5.0,
    default_speed_kmh: float = 30.0,
) -> NetworkGraphSnapshot:
    """Build a reproducible graph from line features.

    Endpoint snapping is deterministic and only joins endpoints within the
    explicit tolerance.  Every feature without usable line geometry is
    ignored; an empty graph is still returned with a stable fingerprint so the
    caller can report a missing-network diagnostic.
    """

    if snap_tolerance_m <= 0:
        raise ValueError("snap_tolerance_m must be > 0")
    if default_speed_kmh <= 0:
        raise ValueError("default_speed_kmh must be > 0")
    if impedance not in {"distance_m", "travel_time_min"}:
        raise ValueError(f"unsupported impedance: {impedance}")
    converter_cache: dict[str, Any] = {}
    metric_lines: list[tuple[str, LineString]] = []
    for index, feature in enumerate(road_features):
        geometry = _geometry(feature)
        source = _crs(feature, source_crs)
        if geometry is None:
            continue
        if source.upper() != metric_crs.upper():
            try:
                converter = converter_cache.setdefault(
                    source,
                    Transformer.from_crs(source, metric_crs, always_xy=True),
                )
                geometry = transform(converter.transform, geometry)
            except Exception:
                continue
        for part_index, line in enumerate(_as_lines(geometry)):
            if line.length <= 0:
                continue
            metric_lines.append((f"road:{index}:{part_index}", line))

    raw_points: list[Point] = []
    for _, line in metric_lines:
        raw_points.extend([Point(line.coords[0]), Point(line.coords[-1])])
    groups: list[list[int]] = []
    for index, point in enumerate(raw_points):
        group = next((item for item in groups if point.distance(raw_points[item[0]]) <= snap_tolerance_m), None)
        if group is None:
            groups.append([index])
        else:
            group.append(index)
    point_to_node: dict[int, str] = {}
    node_points: dict[str, Point] = {}
    for group_index, group in enumerate(groups):
        centroid = Point(
            sum(raw_points[item].x for item in group) / len(group),
            sum(raw_points[item].y for item in group) / len(group),
        )
        node_id = f"node:{group_index:05d}"
        node_points[node_id] = centroid
        for item in group:
            point_to_node[item] = node_id

    graph = nx.Graph()
    for node_id, point in node_points.items():
        graph.add_node(node_id, x=point.x, y=point.y)
    edges: list[NetworkEdge] = []
    point_index = 0
    speed_m_per_min = default_speed_kmh * 1000.0 / 60.0
    for edge_index, (source_id, line) in enumerate(metric_lines):
        left = point_to_node[point_index]
        right = point_to_node[point_index + 1]
        point_index += 2
        if left == right:
            continue
        length = float(line.length)
        edge = NetworkEdge(
            edge_id=f"edge:{edge_index:05d}:{source_id}",
            from_node=left,
            to_node=right,
            length_m=length,
            travel_time_min=length / speed_m_per_min,
        )
        edges.append(edge)
        graph.add_edge(
            left,
            right,
            edge_id=edge.edge_id,
            length_m=edge.length_m,
            travel_time_min=edge.travel_time_min,
        )

    components = sorted(nx.connected_components(graph), key=lambda members: min(members) if members else "")
    component_by_node = {
        node_id: f"component:{index:05d}"
        for index, members in enumerate(components)
        for node_id in members
    }
    nodes = tuple(
        NetworkNode(node_id, point.x, point.y, component_by_node.get(node_id, ""))
        for node_id, point in sorted(node_points.items())
    )
    for node_id, component_id in component_by_node.items():
        graph.nodes[node_id]["component_id"] = component_id
    payload = {
        "network_ref": network_ref,
        "impedance": impedance,
        "metric_crs": metric_crs,
        "snap_tolerance_m": snap_tolerance_m,
        "default_speed_kmh": default_speed_kmh,
        "nodes": [node.__dict__ for node in nodes],
        "edges": [edge.__dict__ for edge in edges],
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return NetworkGraphSnapshot(
        network_ref=network_ref,
        impedance=impedance,
        crs=source_crs,
        metric_crs=metric_crs,
        snap_tolerance_m=snap_tolerance_m,
        default_speed_kmh=default_speed_kmh,
        nodes=nodes,
        edges=tuple(edges),
        fingerprint=fingerprint,
        _graph=graph,
        _node_points=node_points,
    )


__all__ = [
    "NetworkEdge",
    "NetworkGraphSnapshot",
    "NetworkImpedance",
    "NetworkNode",
    "NetworkRoute",
    "build_network_graph",
]
