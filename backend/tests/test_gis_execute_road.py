from __future__ import annotations

from rdflib import Graph, Literal, RDF, URIRef

from app.agent.gis.execute.road.generator import execute_road_planning_from_agent_state
from app.agent.gis.execute.state import ExecuteAgentState
from app.modules.kg.ontology import PLN


CRS = {"type": "name", "properties": {"name": "EPSG:4326"}}


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "crs": CRS, "features": features}


def _feature(geometry: dict, properties: dict | None = None) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties or {}}


def test_execute_road_consumes_parse_road_targets_and_produces_stage2_6_layers() -> None:
    state = ExecuteAgentState(
        session_id="test-road-execute",
        village_name="test-village",
        intent={
            "road_targets": [
                {
                    "road_level": "village_road",
                    "width_m": 4.5,
                    "connects": ["服务中心", "产业点"],
                    "start_anchor": [116.0000, 24.8000],
                    "end_anchor": [116.0040, 24.8040],
                    "semantic": {"raw_text": "规划连通服务中心与产业点道路。"},
                }
            ]
        },
        gis_data={
            "road_geojson": _fc(
                [
                    _feature(
                        {"type": "LineString", "coordinates": [[116.0, 24.8], [116.002, 24.8]]},
                        {"name": "现状村道"},
                    )
                ]
            ),
            "boundary_geojson": _fc(
                [
                    _feature(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [115.99, 24.79],
                                    [116.02, 24.79],
                                    [116.02, 24.82],
                                    [115.99, 24.82],
                                    [115.99, 24.79],
                                ]
                            ],
                        },
                        {"name": "村界"},
                    )
                ]
            ),
        },
    )

    result = execute_road_planning_from_agent_state(state)

    assert result["ran"] is True
    assert result["road_target_count"] == 1
    assert result["stage2_6_report"]["road_intent_count"] == 1
    assert result["stage2_6_report"]["planning_node_count"] >= 1
    assert result["stage2_6_trace"]["pipeline"][0] == "parse_road_intents"
    assert "retry_queue" in result["stage2_6_iteration_records"]
    assert result["stage2_6_quality_gates"]["type"] == "RoadSpatialQualityGateCollection"
    assert result["stage2_6_human_confirmation_template"]["type"] == "RoadHumanConfirmationTemplate"
    assert result["stage2_6_kg_retry_requests"]["type"] == "RoadKnowledgeGraphRetryRequestCollection"
    assert result["stage3_report"]["input_mode"] == "stage2_6_planning_nodes"
    assert result["artifacts"]["iteration_records"].endswith("iteration_records.json")
    assert result["artifacts"]["kg_retry_requests"].endswith("kg_retry_requests.json")
    assert result["artifacts"]["spatial_quality_gates"].endswith("spatial_quality_gates.json")
    assert result["artifacts"]["human_confirmation_template"].endswith(
        "human_confirmation_template.json"
    )
    assert result["artifacts"]["spatial_preprocessing_trace"].endswith("spatial_preprocessing_trace.json")
    assert {layer["layerType"] for layer in result["layout_layers"]} >= {
        "road_spatial_candidates",
        "road_planning_entities",
        "road_planning_nodes",
    }


def test_execute_road_accepts_kg_retry_response_payload() -> None:
    state = ExecuteAgentState(
        session_id="test-road-execute-kg-response",
        village_name="test-village",
        intent={
            "road_targets": [
                {
                    "road_level": "village_road",
                    "connects": ["kg retried parcel", "existing road"],
                    "semantic": {"raw_text": "Connect kg retried parcel to existing road."},
                }
            ]
        },
        gis_data={
            "road_geojson": _fc(
                [
                    _feature(
                        {"type": "LineString", "coordinates": [[116.0, 24.8], [116.002, 24.8]]},
                        {"name": "existing road", "BSM": "ROAD-001"},
                    )
                ]
            ),
            "boundary_geojson": _fc(
                [
                    _feature(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [115.99, 24.79],
                                    [116.02, 24.79],
                                    [116.02, 24.82],
                                    [115.99, 24.82],
                                    [115.99, 24.79],
                                ]
                            ],
                        },
                        {"name": "boundary"},
                    )
                ]
            ),
            "landuse_current_geojson": _fc(
                [
                    _feature(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [116.003, 24.803],
                                    [116.004, 24.803],
                                    [116.004, 24.804],
                                    [116.003, 24.804],
                                    [116.003, 24.803],
                                ]
                            ],
                        },
                        {"BSM": "BSM-KG-001"},
                    )
                ]
            ),
            "road_kg_retry_response": {
                "responses": [
                    {
                        "target_id": "ENT-R-RI-P0001-start",
                        "confirmation_status": "confirmed",
                        "name": "kg retried parcel",
                        "bsm_list": ["BSM-KG-001"],
                        "confidence": 0.95,
                    }
                ]
            },
        },
    )

    result = execute_road_planning_from_agent_state(state)

    assert result["ran"] is True
    assert result["artifacts"]["kg_retry_response_path"].endswith("road_kg_retry_response.json")
    assert result["artifacts"]["manual_confirmation_path"].endswith(
        "kg_retry_confirmations.normalized.json"
    )
    assert result["artifacts"]["kg_retry_loop_report"].endswith("kg_retry_loop_report.json")
    assert result["stage2_6_report"]["manual_confirmation_count"] == 1


def test_execute_road_calls_injected_kg_retry_adapter() -> None:
    calls: list[dict] = []

    def adapter(payload: dict) -> dict:
        calls.append(payload)
        return {
            "responses": [
                {
                    "retry_request_id": payload["requests"][0]["retry_request_id"],
                    "confirmation_status": "confirmed",
                    "bsm_list": ["BSM-ADAPTER-001"],
                    "confidence": 0.96,
                }
            ]
        }

    state = ExecuteAgentState(
        session_id="test-road-execute-kg-adapter",
        village_name="test-village",
        intent={
            "road_targets": [
                {
                    "road_level": "village_road",
                    "connects": ["adapter retried parcel", "existing road"],
                    "semantic": {"raw_text": "Connect adapter retried parcel to existing road."},
                }
            ]
        },
        gis_data={
            "road_geojson": _fc(
                [
                    _feature(
                        {"type": "LineString", "coordinates": [[116.0, 24.8], [116.002, 24.8]]},
                        {"name": "existing road", "BSM": "ROAD-001"},
                    )
                ]
            ),
            "boundary_geojson": _fc(
                [
                    _feature(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [115.99, 24.79],
                                    [116.02, 24.79],
                                    [116.02, 24.82],
                                    [115.99, 24.82],
                                    [115.99, 24.79],
                                ]
                            ],
                        },
                        {"name": "boundary"},
                    )
                ]
            ),
            "landuse_current_geojson": _fc(
                [
                    _feature(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [116.003, 24.803],
                                    [116.004, 24.803],
                                    [116.004, 24.804],
                                    [116.003, 24.804],
                                    [116.003, 24.803],
                                ]
                            ],
                        },
                        {"BSM": "BSM-ADAPTER-001"},
                    )
                ]
            ),
            "road_kg_retry_adapter": adapter,
        },
    )

    result = execute_road_planning_from_agent_state(state)

    assert calls and calls[0]["request_count"] >= 1
    assert result["artifacts"]["kg_retry_adapter_used"] is True
    assert result["artifacts"]["kg_retry_loop_report"].endswith("kg_retry_loop_report.json")
    assert result["stage2_6_report"]["manual_confirmation_count"] == 1


def test_execute_road_uses_planning_kg_from_gis_data_as_retry_adapter() -> None:
    graph = Graph()
    parcel = URIRef("http://example.test/kg/auto-parcel")
    graph.add((parcel, RDF.type, PLN.Parcel))
    graph.add((parcel, PLN.name, Literal("auto retried parcel")))
    graph.add((parcel, PLN.bsm, Literal("BSM-AUTO-001")))
    graph.add((parcel, PLN.current_zone_type, Literal("village_construction")))

    state = ExecuteAgentState(
        session_id="test-road-execute-auto-kg",
        village_name="test-village",
        intent={
            "road_targets": [
                {
                    "road_level": "village_road",
                    "connects": ["auto retried parcel", "existing road"],
                    "semantic": {"raw_text": "Connect auto retried parcel to existing road."},
                }
            ]
        },
        gis_data={
            "road_geojson": _fc(
                [
                    _feature(
                        {"type": "LineString", "coordinates": [[116.0, 24.8], [116.002, 24.8]]},
                        {"name": "existing road", "BSM": "ROAD-001"},
                    )
                ]
            ),
            "boundary_geojson": _fc(
                [
                    _feature(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [115.99, 24.79],
                                    [116.02, 24.79],
                                    [116.02, 24.82],
                                    [115.99, 24.82],
                                    [115.99, 24.79],
                                ]
                            ],
                        },
                        {"name": "boundary"},
                    )
                ]
            ),
            "landuse_current_geojson": _fc(
                [
                    _feature(
                        {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [116.003, 24.803],
                                    [116.004, 24.803],
                                    [116.004, 24.804],
                                    [116.003, 24.804],
                                    [116.003, 24.803],
                                ]
                            ],
                        },
                        {"BSM": "BSM-AUTO-001", "planning_zone": "village_construction"},
                    )
                ]
            ),
            "planning_kg": graph,
        },
    )

    result = execute_road_planning_from_agent_state(state)

    assert result["ran"] is True
    assert result["artifacts"]["kg_retry_adapter_used"] is True
    assert result["artifacts"]["kg_retry_adapter_source"] == "gis_data_planning_kg"
    assert result["artifacts"]["kg_retry_loop_report"].endswith("kg_retry_loop_report.json")
