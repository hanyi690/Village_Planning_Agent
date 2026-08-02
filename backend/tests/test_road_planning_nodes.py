from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.modules.gis.road import (
    PlanningNodeBuildConfig,
    build_planning_nodes,
    build_planning_nodes_with_kg_retry_adapter,
    build_planning_nodes_with_kg_retry_response,
    normalise_kg_retry_response,
)


CRS = {"type": "name", "properties": {"name": "EPSG:4527"}}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": features}


def _feature(geometry: dict | None, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _base_stage2(root: Path, demands: list[dict], projects: list[dict]) -> tuple[Path, Path, Path]:
    stage2 = root / "stage2"
    _write(stage2 / "demand_points.geojson", _collection(demands))
    _write(stage2 / "road_projects.json", {"projects": projects})
    _write(stage2 / "road_constraints.json", {"constraints": []})
    roads = root / "road_edges.geojson"
    _write(
        roads,
        _collection(
            [
                _feature(
                    {"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
                    {"edge_id": "E000001", "component_id": "C0001"},
                )
            ]
        ),
    )
    boundary = root / "boundary.geojson"
    _write(
        boundary,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[-100, -100], [500, -100], [500, 500], [-100, 500], [-100, -100]]],
                    },
                    {"name": "boundary"},
                )
            ]
        ),
    )
    return stage2, roads, boundary


def test_stage2_6_clusters_entities_and_keeps_near_road_nodes_from_new_requests(tmp_path: Path) -> None:
    demands = [
        _feature(
            {"type": "Point", "coordinates": [200, 200]},
            {"demand_id": "D001", "name": "产业点A", "demand_type": "industry", "priority": "high"},
        ),
        _feature(
            {"type": "Point", "coordinates": [208, 205]},
            {"demand_id": "D002", "name": "产业点B", "demand_type": "industry", "priority": "high"},
        ),
        _feature(
            {"type": "Point", "coordinates": [20, 5]},
            {"demand_id": "D003", "name": "近路设施", "demand_type": "public_service", "priority": "medium"},
        ),
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
            cluster_distance_m=50,
            near_network_threshold_m=100,
        )
    )
    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    by_action = {}
    for node in nodes:
        by_action.setdefault(node["properties"]["recommended_action"], []).append(node)
    assert len(by_action["new"]) == 1
    assert len(by_action["new"][0]["properties"]["source_entity_ids"]) == 2
    assert by_action["none"][0]["properties"]["road_service_status"] == "connected"

    requests = json.loads(result.road_planning_requests_path.read_text(encoding="utf-8"))["requests"]
    assert [request["request_type"] for request in requests] == ["new_connection"]

    gates = json.loads(result.quality_gates_path.read_text(encoding="utf-8"))
    assert gates["summary"]["status_counts"]["pass"] == 1
    assert gates["summary"]["status_counts"]["not_needed"] == 1
    assert gates["automatic_route_generation_allowed"] is True


def test_stage2_6_extracts_intents_and_marks_multiple_location_candidates(tmp_path: Path) -> None:
    projects = [
        {
            "project_id": "RP001",
            "action": "new",
            "start_place": "服务中心",
            "end_place": "产业点",
            "evidence": {"chunk_id": "C001", "text": "规划连通服务中心与产业点道路。"},
            "confidence": 0.82,
        }
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, [], projects)
    points = tmp_path / "points.geojson"
    _write(
        points,
        _collection(
            [
                _feature({"type": "Point", "coordinates": [40, 40]}, {"name": "服务中心"}),
                _feature({"type": "Point", "coordinates": [42, 42]}, {"name": "服务中心"}),
                _feature({"type": "Point", "coordinates": [250, 250]}, {"name": "产业点"}),
            ]
        ),
    )
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            point_sources=(points,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )
    intents = json.loads(result.road_intents_path.read_text(encoding="utf-8"))["intents"]
    assert intents[0]["source_chunk_id"] == "C001"
    assert intents[0]["action"] == "new"

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    service = next(feature for feature in located if feature["properties"]["name"] == "服务中心")
    industry = next(feature for feature in located if feature["properties"]["name"] == "产业点")
    assert service["properties"]["location_status"] == "candidate"
    assert service["properties"]["candidate_count"] == 2
    assert service["properties"]["requires_human_confirmation"] is True
    assert industry["properties"]["location_status"] == "confirmed"
    assert result.report["human_review_count"] > 0

    gates = json.loads(result.quality_gates_path.read_text(encoding="utf-8"))
    review_actions = {
        node["next_action"]
        for node in gates["nodes"]
        if node["gate_status"] in {"needs_review", "needs_kg_retry"}
    }
    assert "ready_for_stage3_stage4" not in review_actions


def test_stage2_6_marks_stage2_project_without_text_provenance_for_review(tmp_path: Path) -> None:
    projects = [
        {
            "project_id": "RP-NO-PROVENANCE",
            "action": "new",
            "start_place": "north service node",
            "end_place": "south industry node",
            "confidence": 0.95,
        }
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, [], projects)

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    intent = json.loads(result.road_intents_path.read_text(encoding="utf-8"))["intents"][0]
    assert intent["requires_human_confirmation"] is True
    assert intent["confidence"] == 0.6
    assert result.report["planning_gate"]["automatic_route_generation_allowed"] is False


def test_stage2_6_uses_stage2_evidence_source_text_and_id_as_provenance(tmp_path: Path) -> None:
    projects = [
        {
            "project_id": "RP-EVIDENCE",
            "action": "harden",
            "start_place": "north village road",
            "confidence": 0.91,
            "evidence": {
                "evidence_id": "EV-STAGE2-001",
                "source_text": "Harden the north village road.",
                "source_document": "planning.md",
                "source_line": 42,
            },
        }
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, [], projects)

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    intent = json.loads(result.road_intents_path.read_text(encoding="utf-8"))["intents"][0]
    assert intent["evidence_text"] == "Harden the north village road."
    assert intent["source_chunk_id"] == "EV-STAGE2-001"
    assert intent["requires_human_confirmation"] is False


def test_stage2_6_extracts_normal_chinese_road_intents_from_text_chunks(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path, [], [])
    _write(
        stage2 / "text_chunks.json",
        {
            "chunks": [
                {
                    "chunk_id": "C-ROAD-001",
                    "section_title": "道路交通规划",
                    "source_page": 12,
                    "text": "规划连通服务中心与产业点道路；拓宽北侧村道；推进南部机耕路硬化。",
                }
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    intents = json.loads(result.road_intents_path.read_text(encoding="utf-8"))["intents"]
    by_action = {intent["action"]: intent for intent in intents}
    assert by_action["new"]["start_place"] == "服务中心"
    assert by_action["new"]["end_place"] == "产业点"
    assert by_action["new"]["source_chunk_id"] == "C-ROAD-001"
    assert by_action["new"]["section_title"] == "道路交通规划"
    assert by_action["new"]["source_page"] == 12
    assert by_action["widen"]["start_place"] == "北侧"
    assert by_action["harden"]["start_place"] == "南部"
    assert all(intent["extraction_method"] == "rule_chunk" for intent in intents)


def test_stage2_6_turns_text_chunks_and_kg_bsms_into_planning_request(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path, [], [])
    _write(
        stage2 / "text_chunks.json",
        {
            "chunks": [
                {
                    "chunk_id": "C-KG-001",
                    "section_title": "\u9053\u8def\u4ea4\u901a\u89c4\u5212",
                    "source_page": 8,
                    "text": "\u89c4\u5212\u8fde\u901a\u670d\u52a1\u4e2d\u5fc3\u4e0e\u4ea7\u4e1a\u56ed\u9053\u8def\u3002",
                }
            ]
        },
    )
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[200, 200], [240, 200], [240, 240], [200, 240], [200, 200]]],
                    },
                    {"BSM": "BSM-SERVICE-001", "landuse": "public_service"},
                ),
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[360, 360], [400, 360], [400, 400], [360, 400], [360, 360]]],
                    },
                    {"BSM": "BSM-INDUSTRY-001", "landuse": "industry"},
                ),
            ]
        ),
    )
    kg = tmp_path / "kg_spatial_response.json"
    _write(
        kg,
        {
            "entities": [
                {
                    "entity_id": "kg:facility:service-center",
                    "name": "\u670d\u52a1\u4e2d\u5fc3",
                    "bsm_list": ["BSM-SERVICE-001"],
                    "confidence": 0.96,
                    "spatial_context": {
                        "entity_type": "facility",
                        "planning_zone": "village_construction",
                        "construction_permission": "allow_construction",
                    },
                },
                {
                    "entity_id": "kg:parcel:industry-park",
                    "name": "\u4ea7\u4e1a\u56ed",
                    "bsm_list": ["BSM-INDUSTRY-001"],
                    "confidence": 0.95,
                    "spatial_context": {
                        "entity_type": "parcel",
                        "planning_zone": "village_construction",
                        "construction_permission": "allow_construction",
                    },
                },
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
            cluster_distance_m=50,
        )
    )

    intents = json.loads(result.road_intents_path.read_text(encoding="utf-8"))["intents"]
    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    requests = json.loads(result.road_planning_requests_path.read_text(encoding="utf-8"))["requests"]
    assert len(intents) == 1
    assert intents[0]["source_chunk_id"] == "C-KG-001"
    assert intents[0]["extraction_method"] == "rule_chunk"
    assert len(nodes) == 2
    assert all(node["properties"]["confidence"] >= 0.95 for node in nodes)
    assert all(node["properties"]["road_service_status"] == "isolated" for node in nodes)
    assert len(requests) == 1
    assert requests[0]["request_type"] == "new_connection"
    assert requests[0]["related_intent_ids"] == [intents[0]["intent_id"]]
    assert sorted(requests[0]["source_bsm_list"]) == ["BSM-INDUSTRY-001", "BSM-SERVICE-001"]
    assert result.report["planning_gate"]["automatic_route_generation_allowed"] is True


def test_stage2_6_accepts_generic_kg_location_adapter_output(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "产业服务点",
                "place_name": "产业服务点",
                "demand_type": "industry",
                "priority": "high",
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    kg = tmp_path / "kg_locations.json"
    _write(
        kg,
        {
            "type": "PlanningKnowledgeGraphLocationCandidates",
            "schema_version": "test-v1",
            "entities": [
                {
                    "entity_id": "ENT-D-D001",
                    "kg_entity_id": "kg:industry:service",
                    "name": "产业服务点",
                    "aliases": ["产业节点", "D001"],
                    "lon": 200,
                    "lat": 200,
                    "confidence": 0.93,
                    "source": "gazetteer",
                }
            ],
        },
    )
    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )
    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    assert located[0]["properties"]["location_status"] == "confirmed"
    assert located[0]["properties"]["location_resolver_source"] == "knowledge_graph"
    assert result.report["knowledge_graph_location_key_count"] > 0


def test_stage2_6_resolves_kg_bsm_candidates_through_bundle_geometry(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "north industry parcel",
                "place_name": "north industry parcel",
                "demand_type": "industry",
                "priority": "high",
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[200, 200], [260, 200], [260, 260], [200, 260], [200, 200]]],
                    },
                    {"BSM": "BSM-001", "landuse": "industry"},
                )
            ]
        ),
    )
    kg = tmp_path / "kg_spatial.json"
    _write(
        kg,
        {
            "entities": [
                {
                    "entity_id": "kg-industry-001",
                    "name": "north industry parcel",
                    "aliases": ["D001"],
                    "bsm_list": ["BSM-001"],
                    "confidence": 0.91,
                    "spatial_context": {"planning_zone": "village_construction"},
                }
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
            cluster_distance_m=50,
        )
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    props = located[0]["properties"]
    assert props["location_status"] == "confirmed"
    assert props["spatial_reference_type"] == "bsm_list"
    assert props["candidate_bsm_list"] == ["BSM-001"]
    assert props["source_geometry_type"] == "Polygon"

    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    assert nodes[0]["properties"]["source_bsm_list"] == ["BSM-001"]
    assert nodes[0]["properties"]["access_point_generation_method"] == "nearest_road_side_or_representative_point"

    spatial_candidates = json.loads(result.spatial_candidates_path.read_text(encoding="utf-8"))["features"]
    assert spatial_candidates[0]["properties"]["bundle_geometry_summaries"][0]["resolved"] is True
    assert result.report["bundle_geometry_bsm_count"] == 1
    assert result.report["spatial_candidate_count"] == 1
    trace = json.loads(result.execute_trace_path.read_text(encoding="utf-8"))
    assert trace["pipeline"] == [
        "parse_road_intents",
        "resolve_kg_spatial_candidates",
        "lookup_bundle_geometry_by_bsm",
        "evaluate_spatial_reliability",
        "build_planning_nodes",
        "build_road_planning_requests",
    ]
    records = json.loads(result.iteration_records_path.read_text(encoding="utf-8"))
    assert records["iterations"][2]["worker"] == "bundle_geometry_lookup"


def test_stage2_6_builds_intent_pair_request_from_start_and_end_bsm_nodes(tmp_path: Path) -> None:
    projects = [
        {
            "project_id": "RP001",
            "action": "new",
            "start_place": "north service node",
            "end_place": "south industry node",
            "evidence": {
                "chunk_id": "C001",
                "text": "Connect north service node and south industry node with a village road.",
            },
            "confidence": 0.9,
        }
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, [], projects)
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[200, 200], [240, 200], [240, 240], [200, 240], [200, 200]]],
                    },
                    {"BSM": "BSM-START-001", "landuse": "public_service"},
                ),
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[340, 340], [380, 340], [380, 380], [340, 380], [340, 340]]],
                    },
                    {"BSM": "BSM-END-001", "landuse": "industry"},
                ),
            ]
        ),
    )
    kg = tmp_path / "kg_pair.json"
    _write(
        kg,
        {
            "entities": [
                {
                    "entity_id": "kg-start-001",
                    "name": "north service node",
                    "bsm_list": ["BSM-START-001"],
                    "confidence": 0.94,
                    "spatial_context": {
                        "entity_type": "facility",
                        "planning_zone": "village_construction",
                        "construction_permission": "allow_construction",
                    },
                },
                {
                    "entity_id": "kg-end-001",
                    "name": "south industry node",
                    "bsm_list": ["BSM-END-001"],
                    "confidence": 0.93,
                    "spatial_context": {
                        "entity_type": "parcel",
                        "planning_zone": "village_construction",
                        "construction_permission": "allow_construction",
                    },
                },
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
            cluster_distance_m=50,
        )
    )

    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    assert len(nodes) == 2
    role_sets = [
        {(role["intent_id"], role["role"]) for role in node["properties"]["source_intent_roles"]}
        for node in nodes
    ]
    assert ("RI-P0001", "start") in role_sets[0] | role_sets[1]
    assert ("RI-P0001", "end") in role_sets[0] | role_sets[1]

    requests = json.loads(result.road_planning_requests_path.read_text(encoding="utf-8"))["requests"]
    assert len(requests) == 1
    assert requests[0]["request_type"] == "new_connection"
    assert requests[0]["related_intent_ids"] == ["RI-P0001"]
    assert sorted(requests[0]["source_bsm_list"]) == ["BSM-END-001", "BSM-START-001"]
    assert requests[0]["end_node_id"].startswith("PN-")
    assert "nearest_road:" not in str(requests[0]["end_node_id"])

    compatibility_projects = json.loads((result.output_dir / "road_projects.json").read_text(encoding="utf-8"))
    project = compatibility_projects["projects"][0]
    assert project["start_demand_id"] == requests[0]["start_node_id"]
    assert project["end_demand_id"] == requests[0]["end_node_id"]


def test_stage2_6_keeps_bbox_candidates_in_review_instead_of_auto_nodes(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "north service area",
                "place_name": "north service area",
                "demand_type": "public_service",
                "priority": "high",
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    kg = tmp_path / "kg_bbox.json"
    _write(
        kg,
        {
            "entities": [
                {
                    "entity_id": "kg-area-001",
                    "name": "north service area",
                    "candidate_bbox": [200, 200, 260, 260],
                    "confidence": 0.88,
                }
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    assert located[0]["properties"]["location_status"] == "candidate"
    assert located[0]["properties"]["spatial_reference_type"] == "bbox"
    assert located[0]["properties"]["requires_human_confirmation"] is True

    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    assert nodes[0]["properties"]["node_type"] == "unresolved_node"
    assert nodes[0]["properties"]["recommended_action"] == "manual_review"

    requests = json.loads(result.road_planning_requests_path.read_text(encoding="utf-8"))["requests"]
    assert requests[0]["request_type"] == "verify_existing"
    assert requests[0]["requires_human_confirmation"] is True
    records = json.loads(result.iteration_records_path.read_text(encoding="utf-8"))
    assert records["retry_queue"][0]["next_action"] == "refine_bbox_to_bsm_candidates"
    trace = json.loads(result.execute_trace_path.read_text(encoding="utf-8"))
    assert trace["retry_queue_count"] == 1
    retry_requests = json.loads(result.kg_retry_requests_path.read_text(encoding="utf-8"))
    assert retry_requests["request_count"] == 1
    assert retry_requests["requests"][0]["preferred_resolution"] == "bsm_list_within_bbox"
    assert retry_requests["requests"][0]["expected_response_schema"]["bsm_list"].startswith("preferred")


def test_stage2_6_does_not_turn_existing_road_kg_geometry_into_new_connection(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "existing farm road",
                "place_name": "existing farm road",
                "demand_type": "road_access",
                "priority": "high",
            },
        )
    ]
    projects = [
        {
            "project_id": "RP001",
            "action": "new",
            "start_place": "existing farm road",
            "end_place": "existing road",
            "evidence": {"chunk_id": "C001", "text": "Connect existing farm road to existing road."},
            "confidence": 0.86,
        }
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, projects)
    kg = tmp_path / "kg_existing_road.json"
    _write(
        kg,
        {
            "entities": [
                {
                    "entity_id": "kg-road-001",
                    "name": "existing farm road",
                    "geometry": {"type": "LineString", "coordinates": [[180, 180], [260, 260]]},
                    "confidence": 0.92,
                    "spatial_context": {
                        "entity_type": "road",
                        "road_relation": "road_segment",
                    },
                }
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    props = located[0]["properties"]
    assert props["entity_type"] == "road"
    assert props["source_geometry_type"] == "LineString"

    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    node_props = nodes[0]["properties"]
    assert node_props["existing_road_reference"] is True
    assert node_props["recommended_action"] == "manual_review"

    requests = json.loads(result.road_planning_requests_path.read_text(encoding="utf-8"))["requests"]
    assert requests[0]["request_type"] == "verify_existing"
    assert "existing road reference" in requests[0]["reason"]


def test_stage2_6_does_not_turn_restricted_kg_parcel_into_new_connection(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "protected farmland parcel",
                "place_name": "protected farmland parcel",
                "demand_type": "road_access",
                "priority": "high",
            },
        )
    ]
    projects = [
        {
            "project_id": "RP001",
            "action": "new",
            "start_place": "protected farmland parcel",
            "end_place": "current village road",
            "evidence": {"chunk_id": "C001", "text": "Create access to protected farmland parcel."},
            "confidence": 0.9,
        }
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, projects)
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[220, 220], [280, 220], [280, 280], [220, 280], [220, 220]]],
                    },
                    {"BSM": "BSM-FARM-001", "landuse": "farmland"},
                )
            ]
        ),
    )
    kg = tmp_path / "kg_restricted_parcel.json"
    _write(
        kg,
        {
            "entities": [
                {
                    "entity_id": "kg-farm-001",
                    "name": "protected farmland parcel",
                    "bsm_list": ["BSM-FARM-001"],
                    "confidence": 0.94,
                    "spatial_context": {
                        "entity_type": "farmland",
                        "planning_zone": "farmland_protection",
                        "construction_permission": "forbid_construction",
                    },
                }
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    assert located[0]["properties"]["entity_type"] == "farmland"
    assert located[0]["properties"]["candidate_bsm_list"] == ["BSM-FARM-001"]

    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    node_props = nodes[0]["properties"]
    assert node_props["node_type"] == "unresolved_node"
    assert node_props["restricted_spatial_reference"] is True
    assert node_props["recommended_action"] == "manual_review"
    assert node_props["service_weight"] == 0.0
    assert "forbid_construction" in node_props["restricted_reference_reasons"]

    requests = json.loads(result.road_planning_requests_path.read_text(encoding="utf-8"))["requests"]
    assert requests[0]["request_type"] == "verify_existing"
    assert requests[0]["requires_human_confirmation"] is True
    assert "protected" in requests[0]["reason"]
    assert "new_connection" not in [request["request_type"] for request in requests]

    gates = json.loads(result.quality_gates_path.read_text(encoding="utf-8"))
    assert gates["summary"]["status_counts"]["blocked_constraint"] == 1
    assert gates["nodes"][0]["next_action"] == "confirm_constraint_or_replace_with_service_entity"
    assert "restricted_spatial_reference" in gates["nodes"][0]["blocking_reasons"]

    constraints = json.loads((result.output_dir / "road_constraints.json").read_text(encoding="utf-8"))
    derived = [
        item
        for item in constraints["constraints"]
        if item.get("derived_from") == "stage2_6_restricted_planning_entity"
    ]
    assert len(derived) == 1
    assert derived[0]["target_layer"] == "farmland_protection"
    assert derived[0]["geometry"]["type"] == "Polygon"
    assert result.report["stage2_6_derived_constraint_count"] == 1


def test_stage2_6_uses_bundle_bsm_attributes_as_spatial_context(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "farmland bsm target",
                "place_name": "farmland bsm target",
                "demand_type": "road_access",
                "priority": "high",
            },
        )
    ]
    projects = [
        {
            "project_id": "RP001",
            "action": "new",
            "start_place": "farmland bsm target",
            "end_place": "current village road",
            "evidence": {"chunk_id": "C001", "text": "Create access to farmland bsm target."},
            "confidence": 0.9,
        }
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, projects)
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[220, 220], [280, 220], [280, 280], [220, 280], [220, 220]]],
                    },
                    {
                        "BSM": "BSM-BUNDLE-FARM-001",
                        "landuse": "farmland",
                        "planning_zone": "farmland_protection",
                        "construction_permission": "forbid_construction",
                    },
                )
            ]
        ),
    )
    kg = tmp_path / "kg_bsm_only.json"
    _write(
        kg,
        {
            "entities": [
                {
                    "entity_id": "kg-bsm-only-001",
                    "name": "farmland bsm target",
                    "bsm_list": ["BSM-BUNDLE-FARM-001"],
                    "confidence": 0.94,
                }
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            knowledge_graph_path=kg,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    props = located[0]["properties"]
    assert props["spatial_context"]["construction_permission"] == "forbid_construction"
    assert props["bundle_spatial_context"]["planning_zone"] == "farmland_protection"

    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    node_props = nodes[0]["properties"]
    assert node_props["restricted_spatial_reference"] is True
    assert "restricted_landuse" in node_props["restricted_reference_reasons"]
    assert node_props["recommended_action"] == "manual_review"

    requests = json.loads(result.road_planning_requests_path.read_text(encoding="utf-8"))["requests"]
    assert "new_connection" not in [request["request_type"] for request in requests]


def test_stage2_6_applies_manual_bsm_confirmation_before_other_candidates(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "reviewed access parcel",
                "place_name": "reviewed access parcel",
                "demand_type": "industry",
                "priority": "high",
                "requires_human_confirmation": True,
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[220, 220], [260, 220], [260, 260], [220, 260], [220, 220]]],
                    },
                    {"BSM": "BSM-MANUAL-001", "landuse": "industry"},
                )
            ]
        ),
    )
    manual = tmp_path / "manual_confirmations.json"
    _write(
        manual,
        {
            "confirmations": [
                {
                    "target_id": "ENT-D-D001",
                    "name": "reviewed access parcel",
                    "confirmation_status": "confirmed",
                    "bsm_list": ["BSM-MANUAL-001"],
                    "confidence": 1.0,
                    "confirmed_by": "planner",
                }
            ]
        },
    )

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            bundle_geometry_sources=(bundle,),
            manual_confirmation_path=manual,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    props = located[0]["properties"]
    assert props["location_status"] == "confirmed"
    assert props["location_resolver_source"] == "manual_confirmation"
    assert props["requires_human_confirmation"] is False
    assert props["candidate_bsm_list"] == ["BSM-MANUAL-001"]

    nodes = json.loads(result.planning_nodes_path.read_text(encoding="utf-8"))["features"]
    assert nodes[0]["properties"]["source_bsm_list"] == ["BSM-MANUAL-001"]
    assert nodes[0]["properties"]["recommended_action"] == "new"
    assert result.report["manual_confirmation_count"] == 1
    assert result.report["retry_queue_count"] == 0
    retry_requests = json.loads(result.kg_retry_requests_path.read_text(encoding="utf-8"))
    assert retry_requests["request_count"] == 0


def test_stage2_6_writes_editable_human_confirmation_template(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "template reviewed parcel",
                "place_name": "template reviewed parcel",
                "demand_type": "industry",
                "priority": "high",
                "requires_human_confirmation": True,
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[220, 220], [260, 220], [260, 260], [220, 260], [220, 220]]],
                    },
                    {"BSM": "BSM-TEMPLATE-001", "landuse": "industry"},
                )
            ]
        ),
    )
    first_result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6_first",
            road_edges_path=roads,
            boundary_path=boundary,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    template = json.loads(first_result.human_confirmation_template_path.read_text(encoding="utf-8"))
    assert template["type"] == "RoadHumanConfirmationTemplate"
    assert template["confirmation_count"] >= 1
    entity_confirmation = next(
        item for item in template["confirmations"] if item["target_id"] == "ENT-D-D001"
    )
    assert entity_confirmation["confirmation_status"] == "pending"
    assert "bsm_list" in entity_confirmation

    entity_confirmation["confirmation_status"] = "confirmed"
    entity_confirmation["bsm_list"] = ["BSM-TEMPLATE-001"]
    entity_confirmation["confidence"] = 1.0
    edited_template = tmp_path / "human_confirmation_template.edited.json"
    _write(edited_template, template)

    second_result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6_second",
            road_edges_path=roads,
            boundary_path=boundary,
            bundle_geometry_sources=(bundle,),
            manual_confirmation_path=edited_template,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    located = json.loads(second_result.located_entities_path.read_text(encoding="utf-8"))["features"]
    props = located[0]["properties"]
    assert props["location_resolver_source"] == "manual_confirmation"
    assert props["candidate_bsm_list"] == ["BSM-TEMPLATE-001"]
    assert second_result.report["manual_confirmation_count"] == 1


def test_stage2_6_accepts_normalised_kg_retry_response_as_confirmation(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "kg retried parcel",
                "place_name": "kg retried parcel",
                "demand_type": "industry",
                "priority": "high",
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[220, 220], [280, 220], [280, 280], [220, 280], [220, 220]]],
                    },
                    {"BSM": "BSM-KG-001"},
                )
            ]
        ),
    )
    retry_requests = tmp_path / "kg_retry_requests.json"
    _write(
        retry_requests,
        {
            "requests": [
                {
                    "retry_request_id": "KGR-0001",
                    "target_id": "ENT-D-D001",
                    "name": "kg retried parcel",
                }
            ]
        },
    )
    kg_response = tmp_path / "kg_response.json"
    _write(
        kg_response,
        {
            "responses": [
                {
                    "retry_request_id": "KGR-0001",
                    "confirmation_status": "confirmed",
                    "bsm_list": ["BSM-KG-001"],
                    "confidence": 0.96,
                }
            ]
        },
    )
    normalised = tmp_path / "kg_retry_confirmations.normalized.json"
    normalise_kg_retry_response(kg_response, normalised, retry_requests)

    result = build_planning_nodes(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            bundle_geometry_sources=(bundle,),
            manual_confirmation_path=normalised,
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        )
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    assert located[0]["properties"]["candidate_bsm_list"] == ["BSM-KG-001"]
    assert located[0]["properties"]["location_resolver_source"] == "manual_confirmation"
    assert result.report["manual_confirmation_count"] == 1
    assert result.report["retry_queue_count"] == 0


def test_stage2_6_retry_wrapper_runs_first_pass_then_final_confirmation(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "wrapper retried parcel",
                "place_name": "wrapper retried parcel",
                "demand_type": "industry",
                "priority": "high",
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[220, 220], [280, 220], [280, 280], [220, 280], [220, 220]]],
                    },
                    {"BSM": "BSM-WRAP-001"},
                )
            ]
        ),
    )
    kg_response = tmp_path / "kg_response.json"
    _write(
        kg_response,
        {
            "responses": [
                {
                    "retry_request_id": "KGR-0001",
                    "confirmation_status": "confirmed",
                    "bsm_list": ["BSM-WRAP-001"],
                    "confidence": 0.96,
                }
            ]
        },
    )

    result = build_planning_nodes_with_kg_retry_response(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        ),
        kg_response,
    )

    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    assert located[0]["properties"]["candidate_bsm_list"] == ["BSM-WRAP-001"]
    assert result.report["retry_queue_count"] == 0
    loop_report = json.loads((tmp_path / "stage2_6" / "kg_retry_loop_report.json").read_text(encoding="utf-8"))
    assert loop_report["round_count"] == 2
    assert loop_report["round1_retry_request_count"] == 1
    assert loop_report["normalised_confirmation_count"] == 1


def test_stage2_6_retry_adapter_receives_requests_and_returns_response(tmp_path: Path) -> None:
    demands = [
        _feature(
            None,
            {
                "demand_id": "D001",
                "name": "adapter retried parcel",
                "place_name": "adapter retried parcel",
                "demand_type": "industry",
                "priority": "high",
            },
        )
    ]
    stage2, roads, boundary = _base_stage2(tmp_path, demands, [])
    bundle = tmp_path / "bundle.geojson"
    _write(
        bundle,
        _collection(
            [
                _feature(
                    {
                        "type": "Polygon",
                        "coordinates": [[[220, 220], [280, 220], [280, 280], [220, 280], [220, 220]]],
                    },
                    {"BSM": "BSM-ADAPTER-001"},
                )
            ]
        ),
    )
    seen_requests: list[dict] = []

    def adapter(payload: dict) -> dict:
        seen_requests.append(payload)
        return {
            "responses": [
                {
                    "retry_request_id": payload["requests"][0]["retry_request_id"],
                    "confirmation_status": "confirmed",
                    "bsm_list": ["BSM-ADAPTER-001"],
                    "confidence": 0.97,
                }
            ]
        }

    result = build_planning_nodes_with_kg_retry_adapter(
        PlanningNodeBuildConfig(
            stage2_dir=stage2,
            output_dir=tmp_path / "stage2_6",
            road_edges_path=roads,
            boundary_path=boundary,
            bundle_geometry_sources=(bundle,),
            metric_crs="EPSG:4527",
            display_crs="EPSG:4527",
        ),
        adapter,
    )

    assert seen_requests and seen_requests[0]["request_count"] == 1
    located = json.loads(result.located_entities_path.read_text(encoding="utf-8"))["features"]
    assert located[0]["properties"]["candidate_bsm_list"] == ["BSM-ADAPTER-001"]
    loop_report = json.loads((tmp_path / "stage2_6" / "kg_retry_loop_report.json").read_text(encoding="utf-8"))
    assert loop_report["adapter_called"] is True


def test_stage2_6_rejects_answer_leakage_point_sources(tmp_path: Path) -> None:
    stage2, roads, boundary = _base_stage2(tmp_path, [], [])
    planned_road = tmp_path / "planned" / "road.geojson"
    _write(planned_road, _collection([]))
    with pytest.raises(ValueError, match="planned/evaluation"):
        build_planning_nodes(
            PlanningNodeBuildConfig(
                stage2_dir=stage2,
                output_dir=tmp_path / "stage2_6",
                road_edges_path=roads,
                boundary_path=boundary,
                point_sources=(planned_road,),
            )
        )
