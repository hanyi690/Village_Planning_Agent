"""Controlled delivery vertical slice from typed planned state to map layers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.application.projections.delivery import _layer_view
from app.application.projections.delivery import DeliveryProjectionService
from app.application.queries.artifacts import ArtifactRead
from app.contracts.spatial.planned_state_contracts import PlannedFacility, PlannedState
from app.domain.delivery.delivery_snapshot_builder import build_spatial_delivery_products


FIXTURE = Path(__file__).parents[1] / "characterization" / "fixtures" / "jintian_minimal_planning_problem.json"


def test_typed_planning_feature_survives_snapshot_and_render_boundary(tmp_path, monkeypatch):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    current = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"BSM": "P001", "DLBM": "0101", "area_sqm": 10000},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            },
        }],
    }
    workspace = SimpleNamespace(to_delivery_inputs=lambda: {
        "landuse_current_geojson": current,
        "boundary_geojson": current,
        "road_geojson": {"type": "FeatureCollection", "features": []},
    })
    planned_state = PlannedState(
        facilities=[PlannedFacility(
            name="卫生室",
            facility_type="health",
            geometry=fixture["planning_program"]["candidate_geometry_wkt"],
            derived_from_target=fixture["planning_program"]["target_id"],
        )],
        source="typed-fixture:planning-program",
    )
    monkeypatch.setattr("app.infrastructure.paths.session_run_dir", lambda _session_id: tmp_path)
    monkeypatch.setattr(
        "app.domain.delivery.delivery_exporter.export_delivery_products",
        lambda *args, **kwargs: {"planned_landuse_geojson": current},
    )

    products = build_spatial_delivery_products(
        session_id="typed-fixture-non-empty",
        village_name=fixture["village_name"],
        workspace=workspace,
        planned_changes=[],
        planned_state=planned_state,
        validation_result={"passed": False},
    )

    assert products.error == ""
    assert products.snapshot is not None
    assert products.render_layers
    facility_layer = next(
        layer for layer in products.render_layers
        if (layer.get("layerType") or layer.get("layer_type")) == "facility_point"
    )
    view = _layer_view(facility_layer)
    assert view.feature_count == 1
    assert view.geojson["features"][0]["properties"]["target_id"] == "facility-health-001"


def test_map_layers_reports_no_planning_output_when_delivery_refs_are_missing(monkeypatch):
    async def fake_state(_session_id):
        return {"session_id": _session_id}

    async def fake_read(_session_id, key):
        if key == "delivery_manifest":
            return ArtifactRead(
                session_id=_session_id,
                artifact_key=key,
                artifact_ref={"digest": "manifest-digest"},
                payload={"delivery_status": "partial"},
            )
        return None

    monkeypatch.setattr("app.application.projections.delivery.load_workflow_state", fake_state)
    monkeypatch.setattr("app.application.projections.delivery.artifact_queries.read", fake_read)

    view = __import__("asyncio").run(DeliveryProjectionService().map_layers("empty-session"))

    assert view.delivery_status == "no_planning_output"
    assert view.layers == []


def test_map_layers_fails_closed_when_manifest_is_missing_even_if_layers_exist(monkeypatch):
    async def fake_state(_session_id):
        return {"session_id": _session_id}

    async def fake_read(_session_id, key):
        if key == "delivery_spatial_snapshot":
            return ArtifactRead(
                session_id=_session_id,
                artifact_key=key,
                artifact_ref={"digest": "snapshot-digest"},
                payload={"change_summary": {"created": 1}},
            )
        if key == "render_layers":
            return ArtifactRead(
                session_id=_session_id,
                artifact_key=key,
                artifact_ref={"digest": "render-digest"},
                payload=[{
                    "layerType": "facility_point",
                    "data": {"type": "FeatureCollection", "features": [{"type": "Feature"}]},
                }],
            )
        return None

    monkeypatch.setattr("app.application.projections.delivery.load_workflow_state", fake_state)
    monkeypatch.setattr("app.application.projections.delivery.artifact_queries.read", fake_read)
    view = __import__("asyncio").run(DeliveryProjectionService().map_layers("manifestless-session"))

    assert view.delivery_status == "no_planning_output"
    assert view.layers == []
