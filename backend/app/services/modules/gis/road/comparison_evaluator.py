"""Stage 6: held-out comparison of algorithm and manual road plans.

The manual road layer is read only here.  It is never an input to candidate
generation or scoring, which prevents reference-answer leakage.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import geopandas as gpd
import networkx as nx
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, mapping
from shapely.ops import transform as transform_geometry, unary_union

from .schemas import PlanComparisonConfig, PlanComparisonResult


SCHEMA_VERSION = "1.0"
FACILITY_TYPES = {"education", "healthcare", "eldercare", "public_service", "emergency"}


def _round(value: Optional[float], digits: int = 3) -> Optional[float]:
    return None if value is None or not math.isfinite(value) else round(float(value), digits)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _lines(geometry: Any) -> List[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 1e-8 else []
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        output: List[LineString] = []
        for part in geometry.geoms:
            output.extend(_lines(part))
        return output
    return []


def _load_lines(path: Path, crs: str) -> List[LineString]:
    frame = gpd.read_file(path).to_crs(crs)
    output: List[LineString] = []
    for geometry in frame.geometry:
        output.extend(_lines(geometry))
    return output


def _union(lines: Sequence[LineString]) -> Any:
    return unary_union(list(lines)) if lines else MultiLineString([])


def _incremental(raw: Any, current: Any, tolerance_m: float) -> Tuple[List[LineString], float]:
    if raw.is_empty:
        return [], 0.0
    inside = float(raw.intersection(current.buffer(tolerance_m)).length)
    return _lines(raw.difference(current.buffer(tolerance_m))), inside


def _transformer(source: str, target: str) -> Optional[Transformer]:
    return None if source.upper() == target.upper() else Transformer.from_crs(source, target, always_xy=True)


def _geojson(
    name: str,
    crs: str,
    features: Sequence[Tuple[Any, Mapping[str, Any]]],
    transformer: Optional[Transformer],
) -> Dict[str, Any]:
    payload = []
    for geometry, properties in features:
        display = geometry if transformer is None else transform_geometry(transformer.transform, geometry)
        payload.append(
            {
                "type": "Feature",
                "geometry": mapping(display),
                "properties": dict(properties),
            }
        )
    return {
        "type": "FeatureCollection",
        "name": name,
        "crs": {"type": "name", "properties": {"name": crs}},
        "features": payload,
    }


def _write_lines(
    path: Path,
    name: str,
    lines: Sequence[LineString],
    role: str,
    config: PlanComparisonConfig,
) -> None:
    transformer = _transformer(config.metric_crs, config.display_crs)
    features = [
        (
            line,
            {
                "id": f"{role.upper()}_{index:05d}",
                "plan_role": role,
                "data_mode": config.data_mode,
                "length_m": _round(line.length),
            },
        )
        for index, line in enumerate(lines, 1)
    ]
    _write_json(path, _geojson(name, config.display_crs, features, transformer))


def _sample_points(lines: Sequence[LineString], interval_m: float = 20.0) -> List[Point]:
    points: List[Point] = []
    for line in lines:
        count = max(1, int(math.ceil(line.length / interval_m)))
        points.extend(line.interpolate(min(line.length, index * line.length / count)) for index in range(count + 1))
    return points


def _mean_nearest_distance(source: Sequence[LineString], target: Any) -> Optional[float]:
    samples = _sample_points(source)
    return mean(point.distance(target) for point in samples) if samples and not target.is_empty else None


def _endpoints(lines: Sequence[LineString]) -> List[Point]:
    output: List[Point] = []
    for line in lines:
        output.extend((Point(line.coords[0]), Point(line.coords[-1])))
    return output


def _endpoint_rate(source: Sequence[LineString], target: Sequence[LineString], tolerance: float) -> Optional[float]:
    source_points, target_points = _endpoints(source), _endpoints(target)
    if not source_points or not target_points:
        return None
    target_union = unary_union(target_points)
    return sum(point.distance(target_union) <= tolerance for point in source_points) / len(source_points)


def _orientation(line: LineString) -> float:
    left, right = line.coords[0], line.coords[-1]
    return math.degrees(math.atan2(right[1] - left[1], right[0] - left[0])) % 180.0


def _direction_similarity(source: Sequence[LineString], target: Sequence[LineString]) -> Optional[float]:
    if not source or not target:
        return None
    weighted, total = 0.0, 0.0
    for line in source:
        nearest = min(target, key=line.distance)
        difference = abs(_orientation(line) - _orientation(nearest))
        difference = min(difference, 180.0 - difference)
        weighted += max(0.0, 1.0 - difference / 90.0) * line.length
        total += line.length
    return weighted / total if total else None


def _jaccard(left: set[str], right: set[str]) -> Optional[float]:
    union = left | right
    return len(left & right) / len(union) if union else None


def _geometry_metrics(
    algorithm: Sequence[LineString], manual: Sequence[LineString], config: PlanComparisonConfig
) -> Dict[str, Any]:
    algorithm_union, manual_union = _union(algorithm), _union(manual)
    left_distance = _mean_nearest_distance(algorithm, manual_union)
    right_distance = _mean_nearest_distance(manual, algorithm_union)
    symmetric = mean([value for value in (left_distance, right_distance) if value is not None]) if any(
        value is not None for value in (left_distance, right_distance)
    ) else None
    left_buffer = algorithm_union.buffer(config.similarity_buffer_m)
    right_buffer = manual_union.buffer(config.similarity_buffer_m)
    union_area = left_buffer.union(right_buffer).area
    intersection_area = left_buffer.intersection(right_buffer).area
    algorithm_length, manual_length = float(algorithm_union.length), float(manual_union.length)
    return {
        "average_symmetric_distance_m": _round(symmetric),
        "algorithm_to_manual_mean_distance_m": _round(left_distance),
        "manual_to_algorithm_mean_distance_m": _round(right_distance),
        "buffer_m": config.similarity_buffer_m,
        "buffer_overlap_jaccard": _round(intersection_area / union_area if union_area else None, 6),
        "algorithm_endpoint_match_rate": _round(_endpoint_rate(algorithm, manual, config.endpoint_match_m), 6),
        "manual_endpoint_match_rate": _round(_endpoint_rate(manual, algorithm, config.endpoint_match_m), 6),
        "endpoint_match_tolerance_m": config.endpoint_match_m,
        "direction_similarity": _round(_direction_similarity(algorithm, manual), 6),
        "algorithm_new_length_m": _round(algorithm_length),
        "manual_new_length_m": _round(manual_length),
        "new_length_absolute_difference_m": _round(abs(algorithm_length - manual_length)),
        "new_length_difference_rate": _round(
            abs(algorithm_length - manual_length) / manual_length if manual_length else None, 6
        ),
    }


def _load_demands(path: Path, crs: str) -> List[Dict[str, Any]]:
    frame = gpd.read_file(path).to_crs(crs)
    output = []
    for _, row in frame.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty or geometry.geom_type != "Point":
            continue
        properties = {key: row[key] for key in frame.columns if key != "geometry"}
        output.append({"geometry": geometry, "properties": properties})
    return output


def _served_ids(demands: Sequence[Dict[str, Any]], roads: Any, types: set[str], distance: float) -> set[str]:
    return {
        str(item["properties"].get("demand_id"))
        for item in demands
        if str(item["properties"].get("demand_type")) in types
        and item["geometry"].distance(roads) <= distance
    }


def _base_graph(config: PlanComparisonConfig) -> Tuple[gpd.GeoDataFrame, nx.Graph]:
    nodes = gpd.read_file(config.road_nodes_path).to_crs(config.metric_crs).sort_values("node_id", kind="stable")
    edges = gpd.read_file(config.road_edges_path).to_crs(config.metric_crs).sort_values("edge_id", kind="stable")
    graph = nx.Graph()
    for _, row in nodes.iterrows():
        graph.add_node(str(row["node_id"]))
    for _, row in edges.iterrows():
        left, right, length = str(row["from_node"]), str(row["to_node"]), float(row.geometry.length)
        if graph.has_edge(left, right):
            graph[left][right]["length_m"] = min(graph[left][right]["length_m"], length)
        else:
            graph.add_edge(left, right, length_m=length)
    return nodes.reset_index(drop=True), graph


def _nearest_node(point: Point, nodes: gpd.GeoDataFrame) -> Tuple[str, float]:
    distances = nodes.geometry.distance(point)
    minimum = float(distances.min())
    matches = nodes.loc[(distances - minimum).abs() <= max(1e-8, minimum * 1e-12)]
    row = matches.sort_values("node_id", kind="stable").iloc[0]
    return str(row["node_id"]), minimum


def _augment_graph(base: nx.Graph, nodes: gpd.GeoDataFrame, lines: Sequence[LineString]) -> nx.Graph:
    graph = base.copy()
    for line in lines:
        left, left_gap = _nearest_node(Point(line.coords[0]), nodes)
        right, right_gap = _nearest_node(Point(line.coords[-1]), nodes)
        if left == right:
            continue
        weight = float(line.length + left_gap + right_gap)
        if graph.has_edge(left, right):
            graph[left][right]["length_m"] = min(graph[left][right]["length_m"], weight)
        else:
            graph.add_edge(left, right, length_m=weight)
    return graph


def _average_access_time(
    demands: Sequence[Dict[str, Any]], nodes: gpd.GeoDataFrame, graph: nx.Graph,
    config: PlanComparisonConfig, facility_types: set[str]
) -> Optional[float]:
    settlements = [item for item in demands if item["properties"].get("demand_type") == "settlement"]
    facilities = [item for item in demands if item["properties"].get("demand_type") in facility_types]
    if not settlements or not facilities:
        return None
    facility_nodes = [(_nearest_node(item["geometry"], nodes), item) for item in facilities]
    minutes: List[float] = []
    metres_per_minute = config.assumed_speed_kmh * 1000.0 / 60.0
    for settlement in settlements:
        (source, source_gap) = _nearest_node(settlement["geometry"], nodes)
        lengths = nx.single_source_dijkstra_path_length(graph, source, weight="length_m")
        choices = []
        for (target, target_gap), _ in facility_nodes:
            if target in lengths:
                choices.append((source_gap + lengths[target] + target_gap) / metres_per_minute)
        minutes.append(min(choices) if choices else config.unreachable_time_penalty_min)
    return mean(minutes)


def _deadends(nodes: gpd.GeoDataFrame, graph: nx.Graph, plan: Any, tolerance: float) -> set[str]:
    return {
        str(row["node_id"])
        for _, row in nodes.iterrows()
        if graph.degree[str(row["node_id"])] == 1 and row.geometry.distance(plan) <= tolerance
    }


def _functional_metrics(
    current: Any,
    algorithm: Sequence[LineString],
    manual: Sequence[LineString],
    demands: Sequence[Dict[str, Any]],
    nodes: gpd.GeoDataFrame,
    base_graph: nx.Graph,
    config: PlanComparisonConfig,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    algorithm_union, manual_union = _union(algorithm), _union(manual)
    network_algorithm = current.union(algorithm_union)
    network_manual = current.union(manual_union)
    settlement = {"settlement"}
    current_settlements = _served_ids(demands, current, settlement, config.service_buffer_m)
    algorithm_settlements = _served_ids(demands, network_algorithm, settlement, config.service_buffer_m)
    manual_settlements = _served_ids(demands, network_manual, settlement, config.service_buffer_m)
    current_facilities = _served_ids(demands, current, FACILITY_TYPES, config.service_buffer_m)
    algorithm_facilities = _served_ids(demands, network_algorithm, FACILITY_TYPES, config.service_buffer_m)
    manual_facilities = _served_ids(demands, network_manual, FACILITY_TYPES, config.service_buffer_m)
    algorithm_graph = _augment_graph(base_graph, nodes, algorithm)
    manual_graph = _augment_graph(base_graph, nodes, manual)
    base_time = _average_access_time(demands, nodes, base_graph, config, FACILITY_TYPES)
    algorithm_time = _average_access_time(demands, nodes, algorithm_graph, config, FACILITY_TYPES)
    manual_time = _average_access_time(demands, nodes, manual_graph, config, FACILITY_TYPES)
    base_health = _average_access_time(demands, nodes, base_graph, config, {"healthcare"})
    algorithm_health = _average_access_time(demands, nodes, algorithm_graph, config, {"healthcare"})
    manual_health = _average_access_time(demands, nodes, manual_graph, config, {"healthcare"})
    algorithm_deadends = _deadends(nodes, base_graph, algorithm_union, config.current_match_buffer_m)
    manual_deadends = _deadends(nodes, base_graph, manual_union, config.current_match_buffer_m)
    base_components = nx.number_connected_components(base_graph)
    algorithm_components = nx.number_connected_components(algorithm_graph)
    manual_components = nx.number_connected_components(manual_graph)
    function = {
        "located_demand_count": len(demands),
        "same_settlements_jaccard": _round(_jaccard(algorithm_settlements, manual_settlements), 6),
        "same_newly_served_settlements_jaccard": _round(
            _jaccard(algorithm_settlements - current_settlements, manual_settlements - current_settlements), 6
        ),
        "same_facilities_jaccard": _round(_jaccard(algorithm_facilities, manual_facilities), 6),
        "same_resolved_deadends_jaccard": _round(_jaccard(algorithm_deadends, manual_deadends), 6),
        "algorithm_resolved_deadend_count": len(algorithm_deadends),
        "manual_resolved_deadend_count": len(manual_deadends),
        "baseline_component_count": base_components,
        "algorithm_component_count": algorithm_components,
        "manual_component_count": manual_components,
        "algorithm_connectivity_improvement": base_components - algorithm_components,
        "manual_connectivity_improvement": base_components - manual_components,
        "baseline_public_facility_average_time_min": _round(base_time),
        "algorithm_public_facility_average_time_min": _round(algorithm_time),
        "manual_public_facility_average_time_min": _round(manual_time),
        "algorithm_accessibility_improvement_min": _round(base_time - algorithm_time) if base_time is not None and algorithm_time is not None else None,
        "manual_accessibility_improvement_min": _round(base_time - manual_time) if base_time is not None and manual_time is not None else None,
        "baseline_healthcare_average_time_min": _round(base_health),
        "algorithm_healthcare_average_time_min": _round(algorithm_health),
        "manual_healthcare_average_time_min": _round(manual_health),
    }
    state = {
        "current_settlements": current_settlements,
        "algorithm_settlements": algorithm_settlements,
        "manual_settlements": manual_settlements,
        "current_facilities": current_facilities,
        "algorithm_facilities": algorithm_facilities,
        "manual_facilities": manual_facilities,
        "base_components": base_components,
        "algorithm_components": algorithm_components,
        "manual_components": manual_components,
        "base_time": base_time,
        "algorithm_time": algorithm_time,
        "manual_time": manual_time,
        "base_health": base_health,
        "algorithm_health": algorithm_health,
        "manual_health": manual_health,
    }
    return function, state


def _polygon_union(path: Path, crs: str) -> Any:
    frame = gpd.read_file(path).to_crs(crs)
    return unary_union([geometry for geometry in frame.geometry if geometry is not None and not geometry.is_empty])


def _landuse_unions(path: Path, crs: str) -> Tuple[Any, Any]:
    frame = gpd.read_file(path).to_crs(crs)
    codes = frame["DLBM"].fillna("").astype(str) if "DLBM" in frame.columns else pd.Series("", index=frame.index)
    water = frame.loc[codes.str.startswith("31")]
    construction = frame.loc[codes.str.startswith(("21", "22"))]
    return (
        unary_union(list(water.geometry)) if len(water) else None,
        unary_union(list(construction.geometry)) if len(construction) else None,
    )


def _reasonableness(
    lines: Sequence[LineString], ecology: Any, farmland: Any, water: Any,
    construction: Any, hazards: Any, demands: Sequence[Dict[str, Any]],
    network: Any, config: PlanComparisonConfig,
) -> Dict[str, Any]:
    road_union = _union(lines)
    corridor = road_union.buffer(config.assumed_road_width_m / 2.0, cap_style=2)
    hazard_zone = hazards.buffer(config.hazard_buffer_m) if hazards is not None and not hazards.is_empty else None
    populations: Dict[str, float] = {}
    for item in demands:
        value = item["properties"].get("population_served")
        if (
            item["properties"].get("demand_type") == "settlement"
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and item["geometry"].distance(network) <= config.service_buffer_m
        ):
            populations[str(item["properties"].get("demand_id"))] = float(value)
    length = float(road_union.length)
    return {
        "ecological_redline_conflict_count": sum(line.intersects(ecology) for line in lines) if ecology is not None else 0,
        "ecological_redline_crossing_length_m": _round(road_union.intersection(ecology).length) if ecology is not None else 0.0,
        "basic_farmland_occupation_m2": _round(corridor.intersection(farmland).area) if farmland is not None else 0.0,
        "water_occupation_m2": _round(corridor.intersection(water).area) if water is not None else 0.0,
        "construction_land_conflict_m2": _round(corridor.intersection(construction).area) if construction is not None else 0.0,
        "hazard_exposure_length_m": _round(road_union.intersection(hazard_zone).length) if hazard_zone is not None else 0.0,
        "new_road_length_m": _round(length),
        "estimated_construction_cost_yuan": _round(length * config.assumed_unit_cost_yuan_per_m, 2),
        "covered_population": _round(sum(populations.values()), 1),
        "covered_population_demand_count": len(populations),
    }


def _table(
    current_length: float, current: Dict[str, Any], algorithm: Dict[str, Any], manual: Dict[str, Any],
    state: Dict[str, Any], function: Dict[str, Any], located_settlement_count: int,
    config: PlanComparisonConfig,
) -> List[Dict[str, Any]]:
    rows = [
        ("road_network_total_length", "路网总长度", "m", current_length, current_length + algorithm["new_road_length_m"], current_length + manual["new_road_length_m"], "按去重后的道路中心线长度计算"),
        ("new_road_length", "新建道路长度", "m", 0.0, algorithm["new_road_length_m"], manual["new_road_length_m"], f"剔除现状道路{config.current_match_buffer_m:g}米缓冲区内重合段"),
        ("connected_component_count", "连通片区数量", "count", state["base_components"], state["algorithm_components"], state["manual_components"], "越少表示路网整体连通性越好"),
        ("unconnected_settlement_count", "未连接居民点", "count", located_settlement_count - len(state["current_settlements"]), located_settlement_count - len(state["algorithm_settlements"]), located_settlement_count - len(state["manual_settlements"]), f"距道路超过{config.service_buffer_m:g}米视为未服务"),
        ("healthcare_average_time", "到卫生设施平均时间", "min", function["baseline_healthcare_average_time_min"], function["algorithm_healthcare_average_time_min"], function["manual_healthcare_average_time_min"], "没有已定位的healthcare需求点时为空"),
        ("public_facility_average_time", "到公共设施平均时间", "min", function["baseline_public_facility_average_time_min"], function["algorithm_public_facility_average_time_min"], function["manual_public_facility_average_time_min"], f"按{config.assumed_speed_kmh:g}km/h及不可达{config.unreachable_time_penalty_min:g}分钟惩罚估算"),
        ("basic_farmland_occupation", "基本农田占用", "m2", 0.0, algorithm["basic_farmland_occupation_m2"], manual["basic_farmland_occupation_m2"], f"按{config.assumed_road_width_m:g}米走廊宽度估算"),
        ("ecological_redline_conflicts", "生态红线冲突", "count", 0, algorithm["ecological_redline_conflict_count"], manual["ecological_redline_conflict_count"], "按新增道路分段统计"),
        ("water_occupation", "水域占用", "m2", 0.0, algorithm["water_occupation_m2"], manual["water_occupation_m2"], f"按{config.assumed_road_width_m:g}米走廊宽度估算"),
        ("hazard_exposure", "地灾风险暴露", "m", 0.0, algorithm["hazard_exposure_length_m"], manual["hazard_exposure_length_m"], f"地灾点{config.hazard_buffer_m:g}米影响范围内道路长度"),
        ("estimated_cost", "估算建设成本", "yuan", 0.0, algorithm["estimated_construction_cost_yuan"], manual["estimated_construction_cost_yuan"], f"暂按{config.assumed_unit_cost_yuan_per_m:g}元/米，仅用于方案比较"),
        ("covered_population", "覆盖人口", "person", current["covered_population"], algorithm["covered_population"], manual["covered_population"], "仅统计已有坐标且有人口字段的需求点"),
        ("facility_time_improvement", "设施通达时间改善", "min", 0.0, function["algorithm_accessibility_improvement_min"], function["manual_accessibility_improvement_min"], "相对现状的平均改善"),
    ]
    return [
        {"metric_id": key, "metric": label, "unit": unit, "current": current, "algorithm": alg, "manual": man, "notes": notes}
        for key, label, unit, current, alg, man, notes in rows
    ]


def compare_road_plans(config: PlanComparisonConfig) -> PlanComparisonResult:
    """Run deterministic Stage-6 evaluation and write QGIS/JSON/CSV outputs."""
    config.validate()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    current_lines = _load_lines(config.road_edges_path, config.metric_crs)
    algorithm_raw_lines = _load_lines(config.algorithm_roads_path, config.metric_crs)
    manual_raw_lines = _load_lines(config.manual_planned_roads_path, config.metric_crs)
    current_union, algorithm_raw, manual_raw = _union(current_lines), _union(algorithm_raw_lines), _union(manual_raw_lines)
    algorithm_lines, algorithm_inside = _incremental(algorithm_raw, current_union, config.current_match_buffer_m)
    manual_lines, manual_inside = _incremental(manual_raw, current_union, config.current_match_buffer_m)
    manual_overlap_ratio = manual_inside / manual_raw.length if manual_raw.length else 0.0
    manual_layer_role = "complete_planned_network" if manual_overlap_ratio >= 0.3 else "new_roads_only"

    geometry = _geometry_metrics(algorithm_lines, manual_lines, config)
    demands = _load_demands(config.demand_points_path, config.metric_crs)
    nodes, base_graph = _base_graph(config)
    function, state = _functional_metrics(
        current_union, algorithm_lines, manual_lines, demands, nodes, base_graph, config
    )
    ecology = _polygon_union(config.ecological_protection_path, config.metric_crs)
    farmland = _polygon_union(config.farmland_protection_path, config.metric_crs)
    hazards = _polygon_union(config.hazard_points_path, config.metric_crs)
    water, construction = _landuse_unions(config.landuse_path, config.metric_crs)
    current_reason = _reasonableness(
        [], ecology, farmland, water, construction, hazards, demands, current_union, config
    )
    algorithm_reason = _reasonableness(
        algorithm_lines, ecology, farmland, water, construction, hazards, demands,
        current_union.union(_union(algorithm_lines)), config,
    )
    manual_reason = _reasonableness(
        manual_lines, ecology, farmland, water, construction, hazards, demands,
        current_union.union(_union(manual_lines)), config,
    )
    settlement_count = sum(item["properties"].get("demand_type") == "settlement" for item in demands)
    table = _table(float(current_union.length), current_reason, algorithm_reason, manual_reason, state, function, settlement_count, config)

    algorithm_path = config.output_dir / "algorithm_evaluated_roads.geojson"
    manual_path = config.output_dir / "manual_incremental_roads.geojson"
    preview_path = config.output_dir / "stage6_preview.geojson"
    metrics_path = config.output_dir / "stage6_metrics.json"
    table_path = config.output_dir / "stage6_comparison.csv"
    report_path = config.output_dir / "stage6_report.json"
    _write_lines(algorithm_path, "stage6_algorithm_roads", algorithm_lines, "algorithm", config)
    _write_lines(manual_path, "stage6_manual_new_roads", manual_lines, "manual", config)
    transformer = _transformer(config.metric_crs, config.display_crs)
    preview_features: List[Tuple[Any, Mapping[str, Any]]] = []
    preview_features.extend((line, {"plan_role": "current", "data_mode": config.data_mode}) for line in current_lines)
    preview_features.extend((line, {"plan_role": "algorithm", "data_mode": config.data_mode}) for line in algorithm_lines)
    preview_features.extend((line, {"plan_role": "manual", "data_mode": config.data_mode}) for line in manual_lines)
    _write_json(preview_path, _geojson("stage6_preview", config.display_crs, preview_features, transformer))
    with table_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("metric_id", "metric", "unit", "current", "algorithm", "manual", "notes"))
        writer.writeheader()
        writer.writerows(table)
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "data_mode": config.data_mode,
        "geometry_similarity": geometry,
        "functional_consistency": function,
        "planning_reasonableness": {"current": current_reason, "algorithm": algorithm_reason, "manual": manual_reason},
        "comparison_table": table,
    }
    _write_json(metrics_path, metrics)
    warnings = [
        "Stage 6 reads the manual planned road only as held-out evaluation data; it is not used to generate or score algorithm candidates.",
        "Manual incremental roads are inferred by removing portions within the current-road buffer because the source has no new/existing status field.",
        "Cost, road width, travel speed, service distance, and hazard distance are configurable comparison assumptions, not engineering estimates.",
        "No DEM is used; slope, longitudinal grade, earthwork, drainage, bridge/culvert, and construction-design feasibility are outside this evaluation.",
    ]
    if not demands:
        warnings.append("No located demand points are available; functional and population indicators are unavailable in production mode.")
    if function["baseline_healthcare_average_time_min"] is None:
        warnings.append("No located demand with demand_type=healthcare is available; healthcare travel-time cells are null.")
    report = {
        "schema_version": SCHEMA_VERSION,
        "stage": 6,
        "status": "complete",
        "data_mode": config.data_mode,
        "evaluation_design": {
            "planned_road_read": True,
            "planned_road_role": "held_out_evaluation_only",
            "answer_leakage_prevented": True,
            "manual_layer_detected_role": manual_layer_role,
            "manual_raw_length_m": _round(manual_raw.length),
            "manual_length_matching_current_m": _round(manual_inside),
            "manual_current_overlap_ratio": _round(manual_overlap_ratio, 6),
            "algorithm_raw_length_m": _round(algorithm_raw.length),
            "algorithm_length_matching_current_m": _round(algorithm_inside),
        },
        "geometry_similarity": geometry,
        "functional_consistency": function,
        "planning_reasonableness": {"current": current_reason, "algorithm": algorithm_reason, "manual": manual_reason},
        "comparison_table": table,
        "assumptions": {
            "current_match_buffer_m": config.current_match_buffer_m,
            "similarity_buffer_m": config.similarity_buffer_m,
            "endpoint_match_m": config.endpoint_match_m,
            "service_buffer_m": config.service_buffer_m,
            "hazard_buffer_m": config.hazard_buffer_m,
            "road_width_m": config.assumed_road_width_m,
            "speed_kmh": config.assumed_speed_kmh,
            "unit_cost_yuan_per_m": config.assumed_unit_cost_yuan_per_m,
            "unreachable_time_penalty_min": config.unreachable_time_penalty_min,
        },
        "inputs": {
            "current_edges": _relative(config.road_edges_path),
            "algorithm_roads": _relative(config.algorithm_roads_path),
            "manual_planned_roads": _relative(config.manual_planned_roads_path),
            "demand_points": _relative(config.demand_points_path),
        },
        "outputs": {
            "algorithm_evaluated_roads": _relative(algorithm_path),
            "manual_incremental_roads": _relative(manual_path),
            "preview": _relative(preview_path),
            "metrics": _relative(metrics_path),
            "comparison_csv": _relative(table_path),
        },
        "warnings": warnings,
    }
    _write_json(report_path, report)
    return PlanComparisonResult(
        output_dir=config.output_dir,
        algorithm_roads_path=algorithm_path,
        manual_new_roads_path=manual_path,
        preview_path=preview_path,
        comparison_table_path=table_path,
        metrics_path=metrics_path,
        report_path=report_path,
        report=report,
    )


__all__ = ["compare_road_plans"]
