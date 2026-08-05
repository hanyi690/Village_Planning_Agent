from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import Graph, Literal, RDF, URIRef

from app.modules.kg.ontology import PLN
from app.modules.kg.manager import get_kg_manager
from app.agent.execute.road_generator import _default_kg_retry_adapter
from app.modules.spatial_ops.road import RDFLibKGSpatialRetryAdapter, normalise_kg_retry_response


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_normalise_kg_retry_response_writes_stage2_6_confirmations(tmp_path: Path) -> None:
    requests = tmp_path / "kg_retry_requests.json"
    _write(
        requests,
        {
            "requests": [
                {
                    "retry_request_id": "KGR-0001",
                    "target_id": "ENT-D-D001",
                    "name": "north parcel",
                }
            ]
        },
    )
    response = tmp_path / "kg_response.json"
    _write(
        response,
        {
            "responses": [
                {
                    "retry_request_id": "KGR-0001",
                    "confirmation_status": "confirmed",
                    "bsm_list": ["BSM-001"],
                    "confidence": 0.94,
                    "spatial_context": {"planning_zone": "village_construction"},
                }
            ]
        },
    )
    output = tmp_path / "normalised.json"

    payload = normalise_kg_retry_response(response, output, requests)

    assert payload["confirmation_count"] == 1
    confirmation = payload["confirmations"][0]
    assert confirmation["target_id"] == "ENT-D-D001"
    assert confirmation["name"] == "north parcel"
    assert confirmation["bsm_list"] == ["BSM-001"]
    assert confirmation["confirmation_status"] == "confirmed"
    assert json.loads(output.read_text(encoding="utf-8"))["confirmations"][0] == confirmation


def test_normalise_kg_retry_response_downgrades_bbox_only_confirmed_response(tmp_path: Path) -> None:
    response = tmp_path / "kg_response.json"
    _write(
        response,
        {
            "responses": [
                {
                    "target_id": "ENT-D-D001",
                    "confirmation_status": "confirmed",
                    "candidate_bbox": [0, 0, 10, 10],
                    "confidence": 0.7,
                }
            ]
        },
    )
    output = tmp_path / "normalised.json"

    payload = normalise_kg_retry_response(response, output)

    assert payload["confirmations"][0]["confirmation_status"] == "candidate"
    assert payload["warnings"]


def test_normalise_kg_retry_response_rejects_confirmed_without_geometry_or_bsm(tmp_path: Path) -> None:
    response = tmp_path / "kg_response.json"
    _write(
        response,
        {
            "responses": [
                {
                    "target_id": "ENT-D-D001",
                    "confirmation_status": "confirmed",
                    "confidence": 0.9,
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="confirmed response must include"):
        normalise_kg_retry_response(response, tmp_path / "normalised.json")


def test_rdflib_adapter_returns_unique_bsm_with_spatial_cognition(tmp_path: Path) -> None:
    graph = Graph()
    parcel = URIRef("http://example.test/kg/parcel-001")
    graph.add((parcel, RDF.type, PLN.Parcel))
    graph.add((parcel, PLN.name, Literal("北侧产业地块")))
    graph.add((parcel, PLN.bsm, Literal("BSM-001")))
    graph.add((parcel, PLN.current_zone_type, Literal("村庄建设区")))
    graph.add((parcel, PLN.construction_permission, Literal("allow_construction")))
    graph.add((parcel, PLN.connected_via_road, URIRef("http://example.test/kg/road-001")))
    request_payload = {
        "requests": [
            {
                "retry_request_id": "KGR-001",
                "target_id": "ENT-001",
                "query_input": {"name": "北侧产业地块", "candidate_bsm_list": ["BSM-001"]},
            }
        ]
    }

    response = RDFLibKGSpatialRetryAdapter(graph)(request_payload)

    item = response["responses"][0]
    assert item["confirmation_status"] == "confirmed"
    assert item["bsm_list"] == ["BSM-001"]
    assert item["spatial_context"] == {
        "entity_type": "parcel",
        "planning_zone": "村庄建设区",
        "construction_permission": "allow_construction",
        "road_relation": "connected",
    }
    response_path = tmp_path / "rdflib-response.json"
    requests_path = tmp_path / "kg_retry_requests.json"
    _write(response_path, response)
    _write(requests_path, request_payload)
    normalised = normalise_kg_retry_response(response_path, tmp_path / "normalised.json", requests_path)
    assert normalised["confirmations"][0]["target_id"] == "ENT-001"
    assert normalised["confirmations"][0]["bsm_list"] == ["BSM-001"]


def test_rdflib_adapter_keeps_duplicate_name_as_candidate() -> None:
    graph = Graph()
    for index in (1, 2):
        parcel = URIRef(f"http://example.test/kg/parcel-{index}")
        graph.add((parcel, RDF.type, PLN.Parcel))
        graph.add((parcel, PLN.name, Literal("同名地块")))
        graph.add((parcel, PLN.bsm, Literal(f"BSM-00{index}")))

    response = RDFLibKGSpatialRetryAdapter(graph)(
        {"requests": [{"retry_request_id": "KGR-002", "target_id": "ENT-002", "name": "同名地块"}]}
    )

    item = response["responses"][0]
    assert item["confirmation_status"] == "candidate"
    assert item["candidate_bsms"] == ["BSM-001", "BSM-002"]


def test_execute_adapter_resolves_registered_session_planning_kg() -> None:
    session_id = "test-rdflib-kg-retry-session"
    graph = Graph()
    parcel = URIRef("http://example.test/kg/session-parcel")
    graph.add((parcel, RDF.type, PLN.Parcel))
    graph.add((parcel, PLN.name, Literal("会话地块")))
    graph.add((parcel, PLN.bsm, Literal("BSM-SESSION-001")))
    manager = get_kg_manager()
    manager.register_session(session_id, graph)
    try:
        adapter, source = _default_kg_retry_adapter(
            SimpleNamespace(session_id="road-session", kg_session_ref=session_id),
            {},
        )
    finally:
        manager.remove_session(session_id)

    assert source == "kg_session_interface"
    assert isinstance(adapter, RDFLibKGSpatialRetryAdapter)
    response = adapter({"requests": [{"target_id": "ENT-003", "name": "会话地块"}]})
    assert response["responses"][0]["bsm_list"] == ["BSM-SESSION-001"]
