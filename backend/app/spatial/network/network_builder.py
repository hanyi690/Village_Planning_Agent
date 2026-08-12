"""Deterministic conversion of current road lines into a routable network.

The builder is deliberately limited to topology construction. It never reads a
manual planned-road reference unless a caller explicitly overrides the leakage
guard, and it does not generate candidate roads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import geopandas as gpd
import networkx as nx
from pyproj import CRS, Transformer
from shapely import normalize, set_precision, to_wkb
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

from .schemas import NetworkBuildConfig, NetworkBuildResult


BUILD_VERSION = "1.0.0"
RoadSource = Union[str, Path, Mapping[str, Any], gpd.GeoDataFrame]
GridKey = Tuple[int, int]


@dataclass
class _PreparedRoads:
    lines: List[LineString]
    source_feature_count: int
    source_crs: str
    stats: Dict[str, int]
    source_fields: List[str]
    source_shape_length_ignored: bool


@dataclass
class _Topology:
    node_features: List[Dict[str, Any]]
    edge_features: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    snap_report: Dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _feature_collection(
    features: Sequence[Dict[str, Any]],
    crs: str,
) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": "road_network",
        "crs": {"type": "name", "properties": {"name": crs}},
        "features": list(features),
    }


def _iter_line_parts(geometry: Any) -> Iterable[LineString]:
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "LineString":
        yield geometry
    elif geometry.geom_type == "MultiLineString":
        yield from geometry.geoms
    elif geometry.geom_type == "GeometryCollection":
        for part in geometry.geoms:
            yield from _iter_line_parts(part)


def _canonical_geometry_key(line: LineString, precision_m: float) -> bytes:
    precise = set_precision(line, grid_size=precision_m)
    return to_wkb(normalize(precise), output_dimension=2)


def _round_grid(value: float, precision_m: float) -> int:
    return int(round(float(value) / precision_m))


def _grid_key(coordinate: Sequence[float], precision_m: float) -> GridKey:
    return (
        _round_grid(coordinate[0], precision_m),
        _round_grid(coordinate[1], precision_m),
    )


def _grid_coordinate(key: GridKey, precision_m: float) -> Tuple[float, float]:
    return (key[0] * precision_m, key[1] * precision_m)


def _line_with_rounded_coordinates(
    line: LineString,
    precision_m: float,
) -> LineString:
    coordinates = [
        _grid_coordinate(_grid_key(coordinate, precision_m), precision_m)
        for coordinate in line.coords
    ]
    deduplicated = [coordinates[0]]
    for coordinate in coordinates[1:]:
        if coordinate != deduplicated[-1]:
            deduplicated.append(coordinate)
    return LineString(deduplicated) if len(deduplicated) >= 2 else LineString()


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left == root_right:
            return
        if self.rank[root_left] < self.rank[root_right]:
            root_left, root_right = root_right, root_left
        self.parent[root_right] = root_left
        if self.rank[root_left] == self.rank[root_right]:
            self.rank[root_left] += 1


def _cluster_endpoints(
    lines: Sequence[LineString],
    tolerance_m: float,
    precision_m: float,
) -> Tuple[Dict[GridKey, GridKey], Dict[str, Any]]:
    endpoint_keys = sorted({
        _grid_key(coordinate, precision_m)
        for line in lines
        for coordinate in (line.coords[0], line.coords[-1])
    })
    coordinates = [_grid_coordinate(key, precision_m) for key in endpoint_keys]
    union_find = _UnionFind(len(endpoint_keys))
    cell_size = tolerance_m
    buckets: Dict[Tuple[int, int], List[int]] = defaultdict(list)

    for index, (x, y) in enumerate(coordinates):
        cell = (math.floor(x / cell_size), math.floor(y / cell_size))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((cell[0] + dx, cell[1] + dy), []):
                    ox, oy = coordinates[other]
                    if math.hypot(x - ox, y - oy) <= tolerance_m + 1e-9:
                        union_find.union(index, other)
        buckets[cell].append(index)

    grouped: Dict[int, List[int]] = defaultdict(list)
    for index in range(len(endpoint_keys)):
        grouped[union_find.find(index)].append(index)

    mapping_by_key: Dict[GridKey, GridKey] = {}
    merged_clusters: List[Dict[str, Any]] = []
    max_displacement = 0.0
    chain_cluster_count = 0

    for indexes in grouped.values():
        members = [coordinates[index] for index in indexes]
        if len(indexes) == 1:
            representative_index = indexes[0]
        else:
            representative_index = min(
                indexes,
                key=lambda candidate: (
                    sum(
                        math.dist(coordinates[candidate], coordinates[other])
                        for other in indexes
                    ),
                    coordinates[candidate],
                ),
            )
        representative_key = endpoint_keys[representative_index]
        representative = coordinates[representative_index]
        diameter = max(
            (
                math.dist(members[left], members[right])
                for left in range(len(members))
                for right in range(left + 1, len(members))
            ),
            default=0.0,
        )
        if diameter > tolerance_m + 1e-9:
            chain_cluster_count += 1
        moved = 0
        for index in indexes:
            source_key = endpoint_keys[index]
            mapping_by_key[source_key] = representative_key
            displacement = math.dist(coordinates[index], representative)
            max_displacement = max(max_displacement, displacement)
            if displacement > precision_m / 2:
                moved += 1
        if len(indexes) > 1:
            merged_clusters.append({
                "representative": [round(representative[0], 3), round(representative[1], 3)],
                "member_count": len(indexes),
                "moved_member_count": moved,
                "diameter_m": round(diameter, 6),
                "members": [
                    [round(member[0], 3), round(member[1], 3)]
                    for member in sorted(members)
                ],
            })

    merged_clusters.sort(
        key=lambda item: (item["representative"][0], item["representative"][1])
    )
    return mapping_by_key, {
        "tolerance_m": tolerance_m,
        "unique_endpoint_count_before": len(endpoint_keys),
        "unique_endpoint_count_after": len(grouped),
        "merged_cluster_count": len(merged_clusters),
        "moved_unique_endpoint_count": sum(
            item["moved_member_count"] for item in merged_clusters
        ),
        "max_snap_displacement_m": round(max_displacement, 6),
        "chain_cluster_count": chain_cluster_count,
        "clusters": merged_clusters,
    }


def _apply_endpoint_snap(
    lines: Sequence[LineString],
    endpoint_mapping: Mapping[GridKey, GridKey],
    precision_m: float,
) -> Tuple[List[LineString], int]:
    snapped: List[LineString] = []
    collapsed_count = 0
    for line in lines:
        coordinates = list(line.coords)
        start_key = _grid_key(coordinates[0], precision_m)
        end_key = _grid_key(coordinates[-1], precision_m)
        coordinates[0] = _grid_coordinate(
            endpoint_mapping.get(start_key, start_key), precision_m
        )
        coordinates[-1] = _grid_coordinate(
            endpoint_mapping.get(end_key, end_key), precision_m
        )
        candidate = LineString(coordinates)
        if candidate.is_empty or candidate.length <= 0:
            collapsed_count += 1
            continue
        snapped.append(candidate)
    return snapped, collapsed_count


class RoadNetworkBuilder:
    """Build normalized nodes, edges, graph metrics, and a WGS84 preview."""

    def __init__(self, config: Optional[NetworkBuildConfig] = None) -> None:
        self.config = config or NetworkBuildConfig()
        self.config.validate()
        metric = CRS.from_user_input(self.config.metric_crs)
        if not metric.is_projected:
            raise ValueError("metric_crs must be a projected CRS with metre units")
        axis_units = {axis.unit_name.lower() for axis in metric.axis_info if axis.unit_name}
        if not any(unit in {"metre", "meter"} for unit in axis_units):
            raise ValueError("metric_crs axes must use metres")

    def build(self, source: RoadSource, output_dir: Union[str, Path]) -> NetworkBuildResult:
        """Build and write the Stage-1 road-network artifact set."""
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        source_gdf, source_label = self._load_source(source)
        prepared = self._prepare(source_gdf)

        tolerances = sorted(set(
            (*self.config.tolerance_scenarios_m, self.config.snap_tolerance_m)
        ))
        topologies = {
            tolerance: self._build_topology(prepared.lines, tolerance)
            for tolerance in tolerances
        }
        selected = topologies[self.config.snap_tolerance_m]

        nodes_path = output_path / "road_nodes.geojson"
        edges_path = output_path / "road_edges.geojson"
        report_path = output_path / "road_network_report.json"
        preview_path = output_path / "road_network_preview.geojson"

        nodes_geojson = _feature_collection(
            selected.node_features, self.config.metric_crs
        )
        edges_geojson = _feature_collection(
            selected.edge_features, self.config.metric_crs
        )
        preview_geojson = self._make_preview(
            selected.node_features, selected.edge_features
        )
        _write_json(nodes_path, nodes_geojson)
        _write_json(edges_path, edges_geojson)
        _write_json(preview_path, preview_geojson)

        report = self._make_report(
            source_label=source_label,
            prepared=prepared,
            selected=selected,
            topologies=topologies,
        )
        report["outputs"] = {
            nodes_path.name: {
                "crs": self.config.metric_crs,
                "feature_count": len(selected.node_features),
                "sha256": _sha256_file(nodes_path),
            },
            edges_path.name: {
                "crs": self.config.metric_crs,
                "feature_count": len(selected.edge_features),
                "sha256": _sha256_file(edges_path),
            },
            preview_path.name: {
                "crs": self.config.display_crs,
                "feature_count": len(preview_geojson["features"]),
                "sha256": _sha256_file(preview_path),
            },
        }
        _write_json(report_path, report)

        return NetworkBuildResult(
            output_dir=output_path,
            nodes_path=nodes_path,
            edges_path=edges_path,
            report_path=report_path,
            preview_path=preview_path,
            report=report,
        )

    def _load_source(self, source: RoadSource) -> Tuple[gpd.GeoDataFrame, str]:
        if isinstance(source, gpd.GeoDataFrame):
            return source.copy(), "GeoDataFrame"
        if isinstance(source, Mapping):
            features = source.get("features", [])
            rows: List[Dict[str, Any]] = []
            for feature in features:
                row = dict(feature.get("properties") or {})
                geometry = feature.get("geometry")
                row["geometry"] = shape(geometry) if geometry else None
                rows.append(row)
            crs = self.config.source_crs_override or "EPSG:4326"
            return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs), "GeoJSON mapping"

        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        lowered_parts = {part.lower() for part in source_path.parts}
        if (
            not self.config.allow_evaluation_input
            and "planned" in lowered_parts
            and source_path.name.lower() == "road.geojson"
        ):
            raise ValueError(
                "planned/road.geojson is evaluation-only and cannot be used by "
                "RoadNetworkBuilder unless allow_evaluation_input=True"
            )
        return gpd.read_file(source_path), str(source_path)

    def _prepare(self, source: gpd.GeoDataFrame) -> _PreparedRoads:
        source_feature_count = len(source)
        if source.crs is None:
            if not self.config.source_crs_override:
                raise ValueError("input road layer has no CRS")
            source = source.set_crs(self.config.source_crs_override)
        elif self.config.source_crs_override:
            source = source.set_crs(self.config.source_crs_override, allow_override=True)
        source_crs = source.crs.to_string()
        source_fields = sorted(str(column) for column in source.columns if column != "geometry")

        stats = {
            "empty_geometry_removed": 0,
            "invalid_geometry_removed": 0,
            "non_line_geometry_removed": 0,
            "exploded_part_count": 0,
            "duplicate_removed": 0,
            "short_source_removed": 0,
        }
        valid_source_geometries: List[Any] = []
        for geometry in source.geometry:
            if geometry is None or geometry.is_empty:
                stats["empty_geometry_removed"] += 1
                continue
            if not geometry.is_valid:
                stats["invalid_geometry_removed"] += 1
                continue
            parts = list(_iter_line_parts(geometry))
            if not parts:
                stats["non_line_geometry_removed"] += 1
                continue
            valid_source_geometries.extend(parts)

        if not valid_source_geometries:
            raise ValueError("input contains no valid line geometry")
        metric_series = gpd.GeoSeries(valid_source_geometries, crs=source.crs).to_crs(
            self.config.metric_crs
        )
        stats["exploded_part_count"] = len(metric_series)

        clean_lines: List[LineString] = []
        seen = set()
        for geometry in metric_series:
            for line in _iter_line_parts(geometry):
                if line.is_empty or not line.is_valid:
                    stats["invalid_geometry_removed"] += 1
                    continue
                if line.length < self.config.min_source_length_m:
                    stats["short_source_removed"] += 1
                    continue
                key = _canonical_geometry_key(
                    line, self.config.duplicate_precision_m
                )
                if key in seen:
                    stats["duplicate_removed"] += 1
                    continue
                seen.add(key)
                clean_lines.append(line)

        clean_lines.sort(
            key=lambda line: _canonical_geometry_key(
                line, self.config.duplicate_precision_m
            )
        )
        if not clean_lines:
            raise ValueError("all road lines were removed during cleaning")
        return _PreparedRoads(
            lines=clean_lines,
            source_feature_count=source_feature_count,
            source_crs=source_crs,
            stats=stats,
            source_fields=source_fields,
            source_shape_length_ignored="Shape_Length" in source_fields,
        )

    def _build_topology(
        self,
        clean_lines: Sequence[LineString],
        tolerance_m: float,
    ) -> _Topology:
        first_noded = list(_iter_line_parts(unary_union(list(clean_lines))))
        endpoint_mapping, snap_report = _cluster_endpoints(
            first_noded,
            tolerance_m,
            self.config.coordinate_precision_m,
        )
        snapped_lines, snap_collapsed_count = _apply_endpoint_snap(
            first_noded,
            endpoint_mapping,
            self.config.coordinate_precision_m,
        )
        second_noded = list(_iter_line_parts(unary_union(snapped_lines)))

        final_lines: List[LineString] = []
        seen = set()
        final_short_removed = 0
        final_invalid_removed = 0
        final_duplicate_removed = 0
        for line in second_noded:
            rounded = _line_with_rounded_coordinates(
                line, self.config.coordinate_precision_m
            )
            if rounded.is_empty or not rounded.is_valid:
                final_invalid_removed += 1
                continue
            if rounded.length < self.config.min_edge_length_m:
                final_short_removed += 1
                continue
            key = _canonical_geometry_key(
                rounded, self.config.duplicate_precision_m
            )
            if key in seen:
                final_duplicate_removed += 1
                continue
            seen.add(key)
            final_lines.append(rounded)

        topology = self._records_and_metrics(final_lines)
        topology.snap_report.update({
            **snap_report,
            "intersection_noded_part_count_before_snap": len(first_noded),
            "intersection_noded_part_count_after_snap": len(second_noded),
            "snap_collapsed_edge_count": snap_collapsed_count,
            "final_short_edge_removed": final_short_removed,
            "final_invalid_geometry_removed": final_invalid_removed,
            "final_duplicate_removed": final_duplicate_removed,
        })
        topology.metrics.update({
            "intersection_noded_part_count": len(first_noded),
            "short_edge_removed": final_short_removed,
            "snap_collapsed_edge_count": snap_collapsed_count,
            "duplicate_remaining": 0,
            "invalid_geometry_remaining": 0,
        })
        return topology

    def _records_and_metrics(self, lines: Sequence[LineString]) -> _Topology:
        precision = self.config.coordinate_precision_m
        candidates: List[Tuple[GridKey, GridKey, Tuple[Tuple[float, float], ...], LineString]] = []
        node_keys = set()
        for line in lines:
            coordinates = tuple((float(x), float(y)) for x, y, *_ in line.coords)
            start_key = _grid_key(coordinates[0], precision)
            end_key = _grid_key(coordinates[-1], precision)
            if start_key == end_key:
                continue
            if end_key < start_key:
                start_key, end_key = end_key, start_key
                coordinates = tuple(reversed(coordinates))
            oriented = LineString(coordinates)
            candidates.append((start_key, end_key, coordinates, oriented))
            node_keys.update((start_key, end_key))

        sorted_nodes = sorted(node_keys)
        node_ids = {key: f"N{index:06d}" for index, key in enumerate(sorted_nodes, 1)}
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))

        graph = nx.MultiGraph()
        graph.add_nodes_from(node_ids.values())
        edge_rows: List[Dict[str, Any]] = []
        for index, (start_key, end_key, _coordinates, geometry) in enumerate(candidates, 1):
            edge_id = f"E{index:06d}"
            from_node = node_ids[start_key]
            to_node = node_ids[end_key]
            length_m = float(geometry.length)
            graph.add_edge(
                from_node,
                to_node,
                key=edge_id,
                edge_id=edge_id,
                length_m=length_m,
            )
            edge_rows.append({
                "edge_id": edge_id,
                "from_node": from_node,
                "to_node": to_node,
                "length_m": length_m,
                "geometry": geometry,
            })

        components = list(nx.connected_components(graph))

        def component_values(nodes: set[str]) -> Tuple[int, int, float, str]:
            subgraph = graph.subgraph(nodes)
            length = sum(
                float(data["length_m"])
                for *_edge, data in subgraph.edges(keys=True, data=True)
            )
            return len(nodes), subgraph.number_of_edges(), length, min(nodes)

        components.sort(
            key=lambda nodes: (
                -component_values(nodes)[0],
                -component_values(nodes)[1],
                -component_values(nodes)[2],
                component_values(nodes)[3],
            )
        )
        component_ids: Dict[str, str] = {}
        component_summaries: List[Dict[str, Any]] = []
        for index, nodes in enumerate(components, 1):
            component_id = f"C{index:04d}"
            node_count, edge_count, length_m, _ = component_values(nodes)
            for node in nodes:
                component_ids[node] = component_id
            component_summaries.append({
                "component_id": component_id,
                "node_count": node_count,
                "edge_count": edge_count,
                "length_m": round(length_m, 3),
                "isolated_single_edge": edge_count == 1,
            })

        node_features: List[Dict[str, Any]] = []
        for key in sorted_nodes:
            node_id = node_ids[key]
            degree = int(graph.degree(node_id))
            node_type = (
                "dangling" if degree == 1
                else "intersection" if degree >= 3
                else "pass_through" if degree == 2
                else "isolated"
            )
            x, y = _grid_coordinate(key, precision)
            node_features.append({
                "type": "Feature",
                "properties": {
                    "node_id": node_id,
                    "degree": degree,
                    "node_type": node_type,
                    "component_id": component_ids.get(node_id, ""),
                },
                "geometry": mapping(Point(x, y)),
            })

        edge_features: List[Dict[str, Any]] = []
        total_length_m = 0.0
        for row in edge_rows:
            component_id = component_ids[row["from_node"]]
            length_m = float(row["geometry"].length)
            total_length_m += length_m
            edge_features.append({
                "type": "Feature",
                "properties": {
                    "edge_id": row["edge_id"],
                    "from_node": row["from_node"],
                    "to_node": row["to_node"],
                    "length_m": round(length_m, 3),
                    "status": "current",
                    "component_id": component_id,
                    "is_isolated_component": next(
                        item["isolated_single_edge"]
                        for item in component_summaries
                        if item["component_id"] == component_id
                    ),
                },
                "geometry": mapping(row["geometry"]),
            })

        node_count = graph.number_of_nodes()
        edge_count = graph.number_of_edges()
        largest_nodes = component_summaries[0]["node_count"] if component_summaries else 0
        largest_length = max(
            (item["length_m"] for item in component_summaries), default=0.0
        )
        reachable_pairs = sum(
            item["node_count"] * (item["node_count"] - 1)
            for item in component_summaries
        )
        possible_pairs = node_count * (node_count - 1)
        metrics = {
            "clean_edge_count": edge_count,
            "node_count": node_count,
            "connected_component_count": len(component_summaries),
            "largest_component_ratio": round(largest_nodes / node_count, 6) if node_count else 0.0,
            "largest_component_length_ratio": round(largest_length / total_length_m, 6) if total_length_m else 0.0,
            "reachable_node_pair_ratio": round(reachable_pairs / possible_pairs, 6) if possible_pairs else 1.0,
            "isolated_edge_count": sum(
                item["edge_count"]
                for item in component_summaries
                if item["isolated_single_edge"]
            ),
            "isolated_component_count": sum(
                1 for item in component_summaries if item["isolated_single_edge"]
            ),
            "dangling_node_count": sum(
                1 for node in graph.nodes if graph.degree(node) == 1
            ),
            "intersection_node_count": sum(
                1 for node in graph.nodes if graph.degree(node) >= 3
            ),
            "total_length_m": round(total_length_m, 3),
            "cycle_rank": edge_count - node_count + len(component_summaries),
            "component_summaries": component_summaries,
        }
        return _Topology(
            node_features=node_features,
            edge_features=edge_features,
            metrics=metrics,
            snap_report={},
        )

    def _make_preview(
        self,
        node_features: Sequence[Dict[str, Any]],
        edge_features: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        transformer = Transformer.from_crs(
            self.config.metric_crs,
            self.config.display_crs,
            always_xy=True,
        )
        preview_features: List[Dict[str, Any]] = []
        for feature in edge_features:
            geometry = shapely_transform(
                transformer.transform, shape(feature["geometry"])
            )
            properties = dict(feature["properties"])
            properties.update({
                "feature_kind": "edge",
                "color": "#2563eb" if not properties["is_isolated_component"] else "#dc2626",
            })
            preview_features.append({
                "type": "Feature",
                "properties": properties,
                "geometry": mapping(geometry),
            })
        for feature in node_features:
            geometry = shapely_transform(
                transformer.transform, shape(feature["geometry"])
            )
            properties = dict(feature["properties"])
            properties.update({
                "feature_kind": "node",
                "color": {
                    "intersection": "#16a34a",
                    "dangling": "#f59e0b",
                    "isolated": "#dc2626",
                }.get(properties["node_type"], "#64748b"),
            })
            preview_features.append({
                "type": "Feature",
                "properties": properties,
                "geometry": mapping(geometry),
            })
        return _feature_collection(preview_features, self.config.display_crs)

    def _make_report(
        self,
        *,
        source_label: str,
        prepared: _PreparedRoads,
        selected: _Topology,
        topologies: Mapping[float, _Topology],
    ) -> Dict[str, Any]:
        metrics = selected.metrics
        warnings: List[str] = []
        if prepared.source_shape_length_ignored:
            warnings.append(
                "原始 Shape_Length 已忽略；所有 edge.length_m 均由 EPSG:4527 几何重新计算。"
            )
        if metrics["connected_component_count"] > 1:
            warnings.append(
                f"现状路网包含 {metrics['connected_component_count']} 个不连通片区。"
            )
        if metrics["dangling_node_count"]:
            warnings.append(
                f"检测到 {metrics['dangling_node_count']} 个悬挂端点，需要结合影像判断是真断头还是制图断裂。"
            )
        if selected.snap_report.get("snap_collapsed_edge_count", 0):
            warnings.append(
                f"端点吸附导致 {selected.snap_report['snap_collapsed_edge_count']} 条微小边折叠；"
                "应在影像上复核对应位置。"
            )
        if prepared.stats["invalid_geometry_removed"]:
            warnings.append(
                f"删除了 {prepared.stats['invalid_geometry_removed']} 个无效道路几何。"
            )
        scenario_report: Dict[str, Any] = {}
        for tolerance, topology in sorted(topologies.items()):
            scenario_report[f"{tolerance:g}m"] = {
                "node_count": topology.metrics["node_count"],
                "clean_edge_count": topology.metrics["clean_edge_count"],
                "connected_component_count": topology.metrics["connected_component_count"],
                "largest_component_ratio": topology.metrics["largest_component_ratio"],
                "isolated_edge_count": topology.metrics["isolated_edge_count"],
                "dangling_node_count": topology.metrics["dangling_node_count"],
                "intersection_node_count": topology.metrics["intersection_node_count"],
                "total_length_m": topology.metrics["total_length_m"],
                "snap": topology.snap_report,
            }

        edge_node_ids = {
            feature["properties"]["node_id"] for feature in selected.node_features
        }
        illegal_references = [
            feature["properties"]["edge_id"]
            for feature in selected.edge_features
            if feature["properties"]["from_node"] not in edge_node_ids
            or feature["properties"]["to_node"] not in edge_node_ids
            or feature["properties"]["from_node"] == feature["properties"]["to_node"]
        ]
        non_positive_lengths = [
            feature["properties"]["edge_id"]
            for feature in selected.edge_features
            if feature["properties"]["length_m"] <= 0
        ]
        validation = {
            "status": "pass" if not illegal_references and not non_positive_lengths else "fail",
            "edge_node_reference_errors": illegal_references,
            "non_positive_length_edges": non_positive_lengths,
            "duplicate_geometry_count": metrics["duplicate_remaining"],
            "invalid_geometry_count": metrics["invalid_geometry_remaining"],
            "length_unit": "metre",
            "intersection_noding_applied": True,
            "endpoint_snapping_applied": True,
            "deterministic_id_rule": "nodes sorted by metric coordinate; edges sorted by endpoint and coordinates",
        }
        return {
            "schema_version": "1.0",
            "builder_version": BUILD_VERSION,
            "stage": "stage1_network_builder",
            "source": source_label,
            "source_feature_count": prepared.source_feature_count,
            "source_crs": prepared.source_crs,
            "crs": self.config.metric_crs,
            "display_crs": self.config.display_crs,
            "source_fields": prepared.source_fields,
            "clean_edge_count": metrics["clean_edge_count"],
            "node_count": metrics["node_count"],
            "duplicate_removed": prepared.stats["duplicate_removed"],
            "short_edge_removed": prepared.stats["short_source_removed"] + metrics["short_edge_removed"],
            "connected_component_count": metrics["connected_component_count"],
            "largest_component_ratio": metrics["largest_component_ratio"],
            "largest_component_length_ratio": metrics["largest_component_length_ratio"],
            "isolated_edge_count": metrics["isolated_edge_count"],
            "dangling_node_count": metrics["dangling_node_count"],
            "intersection_node_count": metrics["intersection_node_count"],
            "total_length_m": metrics["total_length_m"],
            "selected_snap_tolerance_m": self.config.snap_tolerance_m,
            "cleaning": prepared.stats,
            "selected_topology": metrics,
            "tolerance_scenarios": scenario_report,
            "validation": validation,
            "leakage_guard": {
                "planned_road_allowed": self.config.allow_evaluation_input,
                "policy": "planned/road.geojson is rejected by default",
            },
            "warnings": warnings,
        }


def build_road_network(
    source: RoadSource,
    output_dir: Union[str, Path],
    config: Optional[NetworkBuildConfig] = None,
) -> NetworkBuildResult:
    """Convenience entry point for callers that do not need a builder instance."""
    return RoadNetworkBuilder(config).build(source, output_dir)


def _parse_tolerances(value: str) -> Tuple[float, ...]:
    values = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not values:
        raise argparse.ArgumentTypeError("at least one tolerance is required")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="构建标准化道路节点—边网络")
    parser.add_argument("--input", required=True, help="现状道路 GeoJSON")
    parser.add_argument("--output", required=True, help="阶段1输出目录")
    parser.add_argument("--metric-crs", default="EPSG:4527")
    parser.add_argument("--snap-tolerance-m", type=float, default=1.0)
    parser.add_argument("--tolerance-scenarios-m", type=_parse_tolerances, default=(1.0, 3.0, 5.0))
    parser.add_argument("--min-source-length-m", type=float, default=0.5)
    parser.add_argument("--min-edge-length-m", type=float, default=0.05)
    args = parser.parse_args()

    config = NetworkBuildConfig(
        metric_crs=args.metric_crs,
        snap_tolerance_m=args.snap_tolerance_m,
        tolerance_scenarios_m=args.tolerance_scenarios_m,
        min_source_length_m=args.min_source_length_m,
        min_edge_length_m=args.min_edge_length_m,
    )
    result = build_road_network(args.input, args.output, config)
    summary = {
        "success": result.report["validation"]["status"] == "pass",
        "output_dir": str(result.output_dir),
        "source_feature_count": result.report["source_feature_count"],
        "node_count": result.report["node_count"],
        "clean_edge_count": result.report["clean_edge_count"],
        "connected_component_count": result.report["connected_component_count"],
        "selected_snap_tolerance_m": result.report["selected_snap_tolerance_m"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RoadNetworkBuilder", "build_road_network"]
