"""Stage 5 unified candidate-road indicators, filtering, scoring, and ranking."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import geopandas as gpd
import networkx as nx
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform as transform_geometry, unary_union

from .schemas import CandidateScoringConfig, CandidateScoringResult


SCHEMA_VERSION = "1.0"
COST_INDICATORS = ("length", "slope", "farmland", "ecology", "demolition", "detour")
BENEFIT_INDICATORS = ("population_benefit", "accessibility_benefit")
FACILITY_TYPES = {"education", "healthcare", "eldercare", "public_service", "emergency"}


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


def _sum_property(features: Sequence[Mapping[str, Any]], field: str) -> float:
    total = 0.0
    for feature in features:
        value = (feature.get("properties") or {}).get(field)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            total += float(value)
    return round(total, 3)


def _payload_crs(payload: Mapping[str, Any], default: str) -> str:
    return str(((payload.get("crs") or {}).get("properties") or {}).get("name") or default)


def _transformer(source: str, target: str) -> Optional[Transformer]:
    if source.upper() == target.upper():
        return None
    return Transformer.from_crs(source, target, always_xy=True)


def _transform(geometry: Any, transformer: Optional[Transformer]) -> Any:
    return geometry if transformer is None else transform_geometry(transformer.transform, geometry)


def _constraint_unions(config: CandidateScoringConfig) -> Dict[str, Any]:
    payload = _read_json(config.stage3_dir / "spatial_constraints.geojson")
    transformer = _transformer(_payload_crs(payload, config.display_crs), config.metric_crs)
    grouped: Dict[str, List[Any]] = defaultdict(list)
    for feature in payload.get("features", []):
        if not feature.get("geometry"):
            continue
        target = str((feature.get("properties") or {}).get("target_layer") or "")
        grouped[target].append(_transform(shape(feature["geometry"]), transformer))
    return {target: unary_union(geometries) for target, geometries in grouped.items()}


def _landuse_context(config: CandidateScoringConfig) -> Tuple[Any, int]:
    landuse = gpd.read_file(config.landuse_path).to_crs(config.metric_crs)
    invalid_count = int((~landuse.geometry.is_valid).sum())
    if invalid_count:
        landuse["geometry"] = landuse.geometry.map(
            lambda geometry: make_valid(geometry) if geometry is not None and not geometry.is_valid else geometry
        )
    name_field = "DLMC" if "DLMC" in landuse.columns else ("SDDLMC" if "SDDLMC" in landuse.columns else None)
    if name_field is None:
        return None, invalid_count
    mask = landuse[name_field].astype(str).str.contains("耕地", regex=False, na=False)
    return (unary_union(list(landuse.loc[mask].geometry)) if mask.any() else None), invalid_count


def _metric_demands(config: CandidateScoringConfig) -> List[Dict[str, Any]]:
    payload = _read_json(config.stage3_dir / "demand_network_binding.geojson")
    transformer = _transformer(_payload_crs(payload, config.display_crs), config.metric_crs)
    output: List[Dict[str, Any]] = []
    for feature in payload.get("features", []):
        geometry = None
        if feature.get("geometry"):
            candidate = _transform(shape(feature["geometry"]), transformer)
            if candidate.geom_type == "Point" and not candidate.is_empty:
                geometry = candidate
        output.append({"properties": dict(feature.get("properties") or {}), "geometry": geometry})
    return output


def _load_graph(config: CandidateScoringConfig) -> Tuple[gpd.GeoDataFrame, nx.Graph]:
    nodes = gpd.read_file(config.road_nodes_path).to_crs(config.metric_crs)
    edges = gpd.read_file(config.road_edges_path).to_crs(config.metric_crs)
    nodes = nodes.sort_values("node_id", kind="stable").reset_index(drop=True)
    graph = nx.Graph()
    for _, row in nodes.iterrows():
        graph.add_node(str(row["node_id"]))
    for _, row in edges.sort_values("edge_id", kind="stable").iterrows():
        left, right = str(row["from_node"]), str(row["to_node"])
        length = float(row.geometry.length)
        if graph.has_edge(left, right):
            graph[left][right]["length_m"] = min(length, graph[left][right]["length_m"])
        else:
            graph.add_edge(left, right, length_m=length)
    return nodes, graph


def _nearest_node(point: Point, nodes: gpd.GeoDataFrame) -> Tuple[str, float]:
    distances = nodes.geometry.distance(point)
    minimum = float(distances.min())
    row = nodes.loc[(distances - minimum).abs() <= max(1e-8, minimum * 1e-12)].sort_values("node_id", kind="stable").iloc[0]
    return str(row["node_id"]), minimum


def _accessibility_context(
    demands: Sequence[Dict[str, Any]], nodes: gpd.GeoDataFrame, graph: nx.Graph
) -> Dict[str, Any]:
    located: List[Dict[str, Any]] = []
    for demand in demands:
        if demand["geometry"] is None:
            continue
        node_id, connector = _nearest_node(demand["geometry"], nodes)
        located.append({**demand, "node_id": node_id, "connector_m": connector})
    settlements = [item for item in located if item["properties"].get("demand_type") == "settlement"]
    facilities = [item for item in located if item["properties"].get("demand_type") in FACILITY_TYPES]
    pairs: List[Dict[str, Any]] = []
    baseline_by_source: Dict[str, Dict[str, float]] = {}
    for settlement in settlements:
        source = settlement["node_id"]
        if source not in baseline_by_source:
            baseline_by_source[source] = nx.single_source_dijkstra_path_length(graph, source, weight="length_m")
        lengths = baseline_by_source[source]
        for facility in facilities:
            baseline = lengths.get(facility["node_id"])
            if baseline is not None:
                baseline += settlement["connector_m"] + facility["connector_m"]
            pairs.append({"source_node": source, "target_node": facility["node_id"], "baseline_m": baseline, "source_connector_m": settlement["connector_m"], "target_connector_m": facility["connector_m"]})
    return {
        "pairs": pairs,
        "pair_count": len(pairs),
        "population_available": any(
            item["geometry"] is not None and isinstance(item["properties"].get("population_served"), (int, float))
            for item in demands
        ),
    }


def _candidate_accessibility_benefit(
    line: LineString,
    nodes: gpd.GeoDataFrame,
    graph: nx.Graph,
    context: Mapping[str, Any],
    config: CandidateScoringConfig,
) -> Optional[float]:
    pairs = context["pairs"]
    if not pairs:
        return None
    left, left_connector = _nearest_node(Point(line.coords[0]), nodes)
    right, right_connector = _nearest_node(Point(line.coords[-1]), nodes)
    candidate_weight = float(line.length) + left_connector + right_connector
    augmented = graph.copy()
    if left != right:
        if augmented.has_edge(left, right):
            candidate_weight = min(candidate_weight, float(augmented[left][right]["length_m"]))
        augmented.add_edge(left, right, length_m=candidate_weight)
    lengths_by_source: Dict[str, Dict[str, float]] = {}
    benefit = 0.0
    for pair in pairs:
        source = pair["source_node"]
        if source not in lengths_by_source:
            lengths_by_source[source] = nx.single_source_dijkstra_path_length(augmented, source, weight="length_m")
        after = lengths_by_source[source].get(pair["target_node"])
        if after is None:
            continue
        after += pair["source_connector_m"] + pair["target_connector_m"]
        before = pair["baseline_m"]
        if before is None:
            benefit += config.unreachable_connection_benefit_m
        else:
            benefit += max(0.0, float(before) - float(after))
    return benefit


def _intersection_length(line: LineString, geometry: Any) -> float:
    return 0.0 if geometry is None or geometry.is_empty else float(line.intersection(geometry).length)


def _population_benefit(
    line: LineString, demands: Sequence[Dict[str, Any]], available: bool, buffer_m: float
) -> Optional[float]:
    if not available:
        return None
    corridor = line.buffer(buffer_m)
    total = 0.0
    for demand in demands:
        population = demand["properties"].get("population_served")
        if demand["geometry"] is not None and isinstance(population, (int, float)) and corridor.covers(demand["geometry"]):
            total += float(population)
    return total


def _minimum_resident_distance(line: LineString, demands: Sequence[Dict[str, Any]]) -> Optional[float]:
    settlements = [
        demand["geometry"]
        for demand in demands
        if demand["geometry"] is not None and demand["properties"].get("demand_type") == "settlement"
    ]
    return min((float(line.distance(point)) for point in settlements), default=None)


def _raw_metrics(
    feature: Mapping[str, Any],
    line: LineString,
    evaluation: Mapping[str, Any],
    demands: Sequence[Dict[str, Any]],
    nodes: gpd.GeoDataFrame,
    graph: nx.Graph,
    access_context: Mapping[str, Any],
    constraints: Mapping[str, Any],
    general_farmland: Any,
    current_roads: Any,
    existing_road_buffer_m: float,
    config: CandidateScoringConfig,
) -> Dict[str, Any]:
    properties = feature.get("properties") or {}
    checks = evaluation.get("checks") or {}
    route_length = float(line.length)
    construction_length = properties.get("construction_length_m")
    length = float(construction_length) if isinstance(construction_length, (int, float)) else route_length
    direct = float(Point(line.coords[0]).distance(Point(line.coords[-1]))) if len(line.coords) >= 2 else 0.0
    protected_farmland = float(checks.get("occupies_basic_farmland_length_m") or 0.0)
    net_new_line = line.difference(current_roads.buffer(existing_road_buffer_m))
    general_farmland_length = _intersection_length(net_new_line, general_farmland)
    ecological_crossing = float(checks.get("crosses_ecological_protection_length_m") or 0.0)
    ecology_geometry = constraints.get("ecological_protection")
    ecology_distance = float(line.distance(ecology_geometry)) if ecology_geometry is not None and not ecology_geometry.is_empty else None
    ecology_proximity_penalty = max(0.0, config.ecology_proximity_m - ecology_distance) if ecology_distance is not None else 0.0
    slope = properties.get("slope_cost")
    if not isinstance(slope, (int, float)):
        slope = None
    raw = {
        "length": length,
        "slope": float(slope) if slope is not None else None,
        "farmland": general_farmland_length + protected_farmland,
        "ecology": ecological_crossing + ecology_proximity_penalty,
        "demolition": float(checks.get("existing_building_land_intersection_m") or 0.0),
        "detour": route_length / direct if direct > 1e-6 else math.inf,
        "population_benefit": _population_benefit(line, demands, bool(access_context["population_available"]), config.service_buffer_m),
        "accessibility_benefit": _candidate_accessibility_benefit(line, nodes, graph, access_context, config),
    }
    raw.update({
        "general_farmland_length_m": general_farmland_length,
        "protected_farmland_length_m": protected_farmland,
        "ecology_crossing_length_m": ecological_crossing,
        "ecology_distance_m": ecology_distance,
        "resident_distance_m": _minimum_resident_distance(line, demands),
        "hazard_distance_m": checks.get("distance_to_nearest_hazard_m"),
        "turn_count": max(0, len(line.coords) - 2),
    })
    return raw


def _hard_and_soft_constraints(
    line: LineString,
    evaluation: Mapping[str, Any],
    raw: Mapping[str, Any],
    config: CandidateScoringConfig,
) -> Tuple[List[str], List[str]]:
    checks = evaluation.get("checks") or {}
    hard: List[str] = []
    soft: List[str] = []
    hard.extend(str(value) for value in (evaluation.get("hard_violations") or []))
    if line.is_empty or not line.is_valid or line.geom_type != "LineString" or line.length <= 0:
        hard.append("invalid_geometry")
    if not bool(checks.get("network_connection_valid", False)):
        hard.append("invalid_network_topology_connection")
    if float(checks.get("crosses_ecological_protection_length_m") or 0.0) > 0.01:
        hard.append("ecological_redline_crossing")
    if float(checks.get("crosses_water_length_m") or 0.0) > 0.01:
        hard.append("prohibited_water_crossing")
    if float(checks.get("outside_boundary_length_m") or 0.0) > 0.01:
        hard.append("outside_village_boundary")
    hazard_distance = raw.get("hazard_distance_m")
    if isinstance(hazard_distance, (int, float)):
        if hazard_distance <= config.hazard_hard_distance_m:
            hard.append("high_geological_hazard_zone")
        elif hazard_distance < config.hazard_soft_distance_m:
            soft.append("near_geological_hazard")
    if config.protected_farmland_is_hard and raw["protected_farmland_length_m"] > 0.01:
        hard.append("permanent_basic_farmland_occupation")
    if raw["general_farmland_length_m"] > 0.01:
        soft.append("general_farmland_occupation")
    if raw["demolition"] > 0.01:
        soft.append("building_or_construction_land_conflict")
    resident_distance = raw.get("resident_distance_m")
    if isinstance(resident_distance, (int, float)) and resident_distance < config.resident_proximity_m:
        soft.append("too_close_to_settlement")
    if raw["length"] > 0:
        soft.append("construction_length_cost")
    if raw["slope"] is not None and raw["slope"] > 0:
        soft.append("slope_cost")
    if raw["turn_count"] > 0:
        soft.append("turning_cost")
    if math.isfinite(raw["detour"]) and raw["detour"] > 1.05:
        soft.append("route_detour")
    return sorted(set(hard)), sorted(set(soft))


def _normalise(records: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Optional[float]]]:
    output: Dict[str, Dict[str, Optional[float]]] = {record["candidate_id"]: {} for record in records}
    for indicator in (*COST_INDICATORS, *BENEFIT_INDICATORS):
        finite = [
            float(record["raw_metrics"][indicator])
            for record in records
            if isinstance(record["raw_metrics"].get(indicator), (int, float))
            and math.isfinite(float(record["raw_metrics"][indicator]))
        ]
        minimum, maximum = (min(finite), max(finite)) if finite else (None, None)
        for record in records:
            value = record["raw_metrics"].get(indicator)
            if minimum is None or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                normalised = None
            elif maximum == minimum:
                normalised = 0.0
            else:
                normalised = (float(value) - minimum) / (maximum - minimum)
            output[record["candidate_id"]][indicator] = normalised
    return output


def score_road_candidates(config: CandidateScoringConfig) -> CandidateScoringResult:
    """Calculate unified indicators, filter hard violations, and rank candidates."""

    config.validate()
    candidate_payload = _read_json(config.stage4_dir / "candidate_roads.geojson")
    stage4_report_path = config.stage4_dir / "stage4_report.json"
    stage4_report = _read_json(stage4_report_path) if stage4_report_path.exists() else {}
    data_mode = stage4_report.get("data_mode", "production")
    evaluation_payload = _read_json(config.stage4_dir / "candidate_evaluations.json")
    evaluation_index = {str(item["candidate_id"]): item for item in evaluation_payload.get("evaluations", [])}
    candidate_to_metric = _transformer(_payload_crs(candidate_payload, config.display_crs), config.metric_crs)
    metric_to_display = _transformer(config.metric_crs, config.display_crs)
    demands = _metric_demands(config)
    constraints = _constraint_unions(config)
    general_farmland, landuse_repairs = _landuse_context(config)
    nodes, graph = _load_graph(config)
    current_edges = gpd.read_file(config.road_edges_path).to_crs(config.metric_crs)
    current_roads = unary_union(list(current_edges.geometry))
    stage4_report_path = config.stage4_dir / "stage4_report.json"
    stage4_report = _read_json(stage4_report_path) if stage4_report_path.exists() else {}
    existing_road_buffer_m = float(
        (stage4_report.get("parameters") or {}).get("existing_road_buffer_m") or 4.0
    )
    access_context = _accessibility_context(demands, nodes, graph)

    records: List[Dict[str, Any]] = []
    feature_index: Dict[str, Dict[str, Any]] = {}
    for feature in sorted(candidate_payload.get("features", []), key=lambda item: str((item.get("properties") or {}).get("candidate_id") or item.get("id") or "")):
        properties = dict(feature.get("properties") or {})
        candidate_id = str(properties.get("candidate_id") or feature.get("id") or "")
        if candidate_id not in evaluation_index:
            raise ValueError(f"candidate has no Stage-4 evaluation: {candidate_id}")
        geometry = shape(feature["geometry"]) if feature.get("geometry") else LineString()
        line = _transform(geometry, candidate_to_metric)
        evaluation = evaluation_index[candidate_id]
        raw = _raw_metrics(
            feature,
            line,
            evaluation,
            demands,
            nodes,
            graph,
            access_context,
            constraints,
            general_farmland,
            current_roads,
            existing_road_buffer_m,
            config,
        )
        hard, soft = _hard_and_soft_constraints(line, evaluation, raw, config)
        records.append({
            "candidate_id": candidate_id,
            "request_id": str(properties.get("request_id") or ""),
            "source_type": properties.get("source_type"),
            "source_id": properties.get("source_id"),
            "strategy": properties.get("strategy"),
            "line": line,
            "raw_metrics": raw,
            "hard_violations": hard,
            "soft_constraints": soft,
            "eligible": not hard,
        })
        feature_index[candidate_id] = feature

    normalised = _normalise(records)
    for record in records:
        candidate_id = record["candidate_id"]
        values = normalised[candidate_id]
        contributions: Dict[str, Optional[float]] = {}
        score = 0.0
        active_weight = 0.0
        for indicator in COST_INDICATORS:
            value = values[indicator]
            if value is None:
                contributions[indicator] = None
                continue
            contribution = float(config.weights[indicator]) * value
            contributions[indicator] = contribution
            score += contribution
            active_weight += float(config.weights[indicator])
        for indicator in BENEFIT_INDICATORS:
            value = values[indicator]
            if value is None:
                contributions[indicator] = None
                continue
            contribution = -float(config.weights[indicator]) * value
            contributions[indicator] = contribution
            score += contribution
            active_weight += float(config.weights[indicator])
        record["normalised_metrics"] = values
        record["score_contributions"] = contributions
        record["score"] = round(score, 9)
        record["active_weight_sum"] = round(active_weight, 6)
        record["rank_within_request"] = None
        record["global_eligible_rank"] = None

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["eligible"]:
            grouped[record["request_id"]].append(record)
    recommended_ids: set[str] = set()
    for request_id, items in sorted(grouped.items()):
        ranked = sorted(items, key=lambda item: (item["score"], item["raw_metrics"]["length"], item["candidate_id"]))
        for rank, item in enumerate(ranked, 1):
            item["rank_within_request"] = rank
        if ranked:
            recommended_ids.add(ranked[0]["candidate_id"])
    eligible_global = sorted((record for record in records if record["eligible"]), key=lambda item: (item["score"], item["candidate_id"]))
    for rank, item in enumerate(eligible_global, 1):
        item["global_eligible_rank"] = rank

    scored_features: List[Dict[str, Any]] = []
    detail_records: List[Dict[str, Any]] = []
    for record in records:
        source = feature_index[record["candidate_id"]]
        properties = dict(source.get("properties") or {})
        properties.update({
            "score": record["score"],
            "eligible": record["eligible"],
            "selection_status": "recommended" if record["candidate_id"] in recommended_ids else ("eligible_alternative" if record["eligible"] else "rejected_hard_constraint"),
            "rank_within_request": record["rank_within_request"],
            "global_eligible_rank": record["global_eligible_rank"],
            "hard_violation_count": len(record["hard_violations"]),
            "soft_constraint_count": len(record["soft_constraints"]),
            "hard_violations": record["hard_violations"],
            "soft_constraints": record["soft_constraints"],
        })
        for indicator in (*COST_INDICATORS, *BENEFIT_INDICATORS):
            properties[f"raw_{indicator}"] = record["raw_metrics"][indicator]
            properties[f"norm_{indicator}"] = record["normalised_metrics"][indicator]
        scored_features.append({
            "type": "Feature",
            "id": record["candidate_id"],
            "geometry": mapping(_transform(record["line"], metric_to_display)),
            "properties": properties,
        })
        detail_records.append({key: value for key, value in record.items() if key != "line"})

    recommended = [feature for feature in scored_features if feature["properties"]["selection_status"] == "recommended"]
    recommended_id_set = {
        str(feature["properties"]["candidate_id"]) for feature in recommended
    }
    segment_source = config.stage4_dir / "candidate_route_segments.geojson"
    recommended_segments: List[Dict[str, Any]] = []
    if segment_source.exists():
        segment_payload = _read_json(segment_source)
        for feature in segment_payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            if str(properties.get("candidate_id") or "") not in recommended_id_set:
                continue
            properties["selection_status"] = "recommended_plan_segment"
            recommended_segments.append(
                {"type": "Feature", "id": feature.get("id"), "geometry": feature.get("geometry"), "properties": properties}
            )
    action_counts = Counter(
        str((feature.get("properties") or {}).get("construction_action") or "unknown")
        for feature in recommended_segments
    )
    action_lengths: Dict[str, float] = defaultdict(float)
    for feature in recommended_segments:
        properties = feature.get("properties") or {}
        action = str(properties.get("construction_action") or "unknown")
        value = properties.get("length_m")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            action_lengths[action] += float(value)
    rejected = [feature for feature in scored_features if not feature["properties"]["eligible"]]
    available_indicators = {
        indicator: any(record["normalised_metrics"][indicator] is not None for record in records)
        for indicator in (*COST_INDICATORS, *BENEFIT_INDICATORS)
    }
    hard_counts = Counter(reason for record in records for reason in record["hard_violations"])
    soft_counts = Counter(reason for record in records for reason in record["soft_constraints"])
    report = {
        "schema_version": SCHEMA_VERSION,
        "data_mode": data_mode,
        "stage": "stage5_candidate_scoring",
        "score_direction": "lower_is_better",
        "formula": "w1*L + w2*S + w3*F + w4*E + w5*D + w6*R - w7*P - w8*A",
        "normalisation": "min-max across the current candidate set; constant indicators contribute zero differentiation",
        "weights": {key: float(value) for key, value in sorted(config.weights.items())},
        "indicator_availability": available_indicators,
        "candidate_count": len(records),
        "eligible_candidate_count": sum(record["eligible"] for record in records),
        "rejected_candidate_count": sum(not record["eligible"] for record in records),
        "request_with_recommendation_count": len(recommended_ids),
        "recommended_plan_summary": {
            "recommended_route_count": len(recommended),
            "recommended_segment_count": len(recommended_segments),
            "action_segment_counts": dict(sorted(action_counts.items())),
            "action_length_m": {
                key: round(value, 3) for key, value in sorted(action_lengths.items())
            },
            "total_route_length_m": _sum_property(recommended, "length_m"),
            "net_new_length_m": _sum_property(recommended, "new_length_m"),
            "reuse_existing_length_m": _sum_property(recommended, "reuse_existing_length_m"),
            "widen_length_m": _sum_property(recommended, "widen_length_m"),
            "harden_length_m": _sum_property(recommended, "harden_length_m"),
            "net_new_footprint_m2": _sum_property(recommended, "net_new_footprint_m2"),
        },
        "hard_violation_counts": dict(sorted(hard_counts.items())),
        "soft_constraint_counts": dict(sorted(soft_counts.items())),
        "thresholds": {
            "service_buffer_m": config.service_buffer_m,
            "resident_proximity_m": config.resident_proximity_m,
            "ecology_proximity_m": config.ecology_proximity_m,
            "hazard_hard_distance_m": config.hazard_hard_distance_m,
            "hazard_soft_distance_m": config.hazard_soft_distance_m,
            "protected_farmland_is_hard": config.protected_farmland_is_hard,
            "existing_road_buffer_m": existing_road_buffer_m,
        },
        "data_quality": {
            "landuse_invalid_geometry_repaired": landuse_repairs,
            "located_demand_count": sum(demand["geometry"] is not None for demand in demands),
            "population_data_available": access_context["population_available"],
            "settlement_facility_pair_count": access_context["pair_count"],
        },
        "hard_constraint_policy": [
            "ecological_redline_crossing",
            "prohibited_water_crossing",
            "outside_village_boundary",
            "high_geological_hazard_zone",
            "invalid_geometry",
            "invalid_network_topology_connection",
            "permanent_basic_farmland_occupation" if config.protected_farmland_is_hard else None,
        ],
        "leakage_guard": {
            "planned_road_read": False,
            "rule": "Stage 5 scores generated candidates without reading the held-out manual planned road.",
        },
        "limitations": [
            "当前没有DEM或坡度成果，S指标标记为不可用且不参与本轮评分。",
            "当前没有已确认的人口和设施位置时，P、A指标标记为不可用，不使用猜测值。",
            "评分结果用于方案筛选和专家复核，不替代工程勘察、设计或法定审批。",
        ],
        "reproducibility": {
            "deterministic": True,
            "timestamps_in_outputs": False,
            "tie_break_rule": "score, length, candidate_id",
        },
    }
    report["limitations"] = [
        "Slope is unavailable when Stage 4 is run without a DEM; unavailable indicators do not enter scoring.",
        "Unverified population or facility locations remain unavailable rather than being guessed in production mode.",
        "Scores support corridor comparison and expert review; they do not replace survey, design, or statutory approval.",
    ]
    report["hard_constraint_policy"] = [item for item in report["hard_constraint_policy"] if item]

    output = config.output_dir
    output.mkdir(parents=True, exist_ok=True)
    scored_path = output / "candidate_scores.geojson"
    details_path = output / "candidate_score_details.json"
    recommended_path = output / "recommended_candidates.geojson"
    recommended_segments_path = output / "recommended_plan_segments.geojson"
    final_plan_preview_path = output / "final_plan_preview.geojson"
    rejected_path = output / "rejected_candidates.geojson"
    preview_path = output / "stage5_preview.geojson"
    report_path = output / "stage5_report.json"
    _write_json(scored_path, _feature_collection("candidate_scores", config.display_crs, scored_features))
    _write_json(details_path, {"schema_version": SCHEMA_VERSION, "weights": report["weights"], "candidates": detail_records})
    _write_json(recommended_path, _feature_collection("recommended_candidates", config.display_crs, recommended))
    _write_json(recommended_segments_path, _feature_collection("recommended_plan_segments", config.display_crs, recommended_segments))
    current_edges = gpd.read_file(config.road_edges_path).to_crs(config.display_crs)
    final_preview: List[Dict[str, Any]] = []
    for _, row in current_edges.sort_values("edge_id", kind="stable").iterrows():
        final_preview.append(
            {
                "type": "Feature",
                "geometry": mapping(row.geometry),
                "properties": {"plan_role": "current", "construction_action": "existing", "data_mode": data_mode},
            }
        )
    for feature in recommended_segments:
        copied = json.loads(json.dumps(feature, ensure_ascii=False))
        copied["properties"]["plan_role"] = "recommended"
        final_preview.append(copied)
    _write_json(final_plan_preview_path, _feature_collection("final_plan_preview", config.display_crs, final_preview))
    _write_json(rejected_path, _feature_collection("rejected_candidates", config.display_crs, rejected))
    _write_json(preview_path, _feature_collection("stage5_preview", config.display_crs, scored_features))
    _write_json(report_path, report)
    return CandidateScoringResult(
        output_dir=output,
        scored_candidates_path=scored_path,
        details_path=details_path,
        recommended_path=recommended_path,
        recommended_segments_path=recommended_segments_path,
        final_plan_preview_path=final_plan_preview_path,
        rejected_path=rejected_path,
        preview_path=preview_path,
        report_path=report_path,
        report=report,
    )


class RoadPlanEvaluator:
    """Object-oriented wrapper for Stage-5 scoring without reference leakage."""

    def __init__(self, config: CandidateScoringConfig) -> None:
        self.config = config

    def evaluate(self) -> CandidateScoringResult:
        return score_road_candidates(self.config)


__all__ = ["RoadPlanEvaluator", "score_road_candidates"]
