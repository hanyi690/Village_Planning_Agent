"""Characterization tests for the empty-delivery baseline.

These tests deliberately describe the boundary behavior, not a successful
real-data planning run.  A real run with no planning feature must remain
diagnostic and must never be promoted to complete delivery.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.contracts.artifacts.delivery_manifest_contracts import DeliveryManifest
from app.application.projections.delivery import _effective_delivery_status
from app.domain.delivery.gate import deliver_gate_route, evaluate_deliver_gate, summarize_planning_output


FIXTURE = Path(__file__).parent / "fixtures" / "jintian_minimal_planning_problem.json"


def _current_only_layers():
    polygon = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }
    feature = {"type": "Feature", "properties": {"BSM": "P001"}, "geometry": polygon}
    return [
        {"layerType": "boundary", "data": {"type": "FeatureCollection", "features": [feature]}},
        {"layerType": "current_landuse", "data": {"type": "FeatureCollection", "features": [feature]}},
        {"layerType": "complete_planned_landuse", "data": {"type": "FeatureCollection", "features": [feature]}},
    ]


def test_fixture_is_typed_and_describes_real_geometry_evidence():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert payload["planning_program"]["asset_kind"] == "facility"
    assert payload["planning_program"]["expected_output_kind"] == "point"
    assert payload["planning_program"]["candidate_geometry_wkt"].startswith("POINT")
    assert payload["road_evidence"]["network_ref"]
    assert payload["road_evidence"]["start"] != payload["road_evidence"]["end"]


def test_baseline_only_delivery_is_explicitly_no_planning_output():
    summary = summarize_planning_output(_current_only_layers(), {"change_summary": {}})

    assert summary["status"] == "no_planning_output"
    assert summary["planning_overlay_feature_count"] == 0
    assert summary["non_baseline_feature_count"] == 0
    assert summary["planned_is_current_copy"] is True

    manifest = DeliveryManifest(
        delivery_status="partial",
        diagnostic_summary={"planning_output": summary},
    )
    assert deliver_gate_route(manifest) == "END_DIAGNOSTIC"
    gate = evaluate_deliver_gate(manifest)
    assert gate.passed is False
    assert gate.route_reason == "no_planning_output"
    assert gate.pending_requests[0].request_type == "deliver_no_planning_output"


def test_non_baseline_overlay_is_counted_without_static_planned_input():
    layers = _current_only_layers() + [
        {
            "layerType": "facility_point",
            "data": {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"target_id": "facility-health-001"},
                    "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                }],
            },
        },
    ]

    summary = summarize_planning_output(layers, {"change_summary": {}})

    assert summary["status"] == "ready"
    assert summary["planning_overlay_feature_count"] == 1
    assert summary["non_baseline_feature_count"] == 1


def test_delivery_projection_reads_nested_no_planning_output_status():
    assert _effective_delivery_status({
        "delivery_status": "partial",
        "diagnostic_summary": {
            "planning_output": {"status": "no_planning_output"},
        },
    }) == "no_planning_output"
